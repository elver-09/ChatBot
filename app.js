const { createBot, createProvider, createFlow, addKeyword, EVENTS } = require('@bot-whatsapp/bot');
const BaileysProvider = require('@bot-whatsapp/provider/baileys');
const MockAdapter = require('@bot-whatsapp/database/mock');
const cron = require('node-cron');
const { updateTrainylOrderLocation, getOrdersForToday, markWhatsAppAsSent } = require('./odooService');

const RECENT_TTL_MS = 30 * 60 * 1000;
const recentNotifiedPhones = new Map();

process.on('unhandledRejection', (reason) => {
    console.error('❌ Rechazo no manejado:', reason);
});

process.on('uncaughtException', (error) => {
    console.error('❌ Excepción no capturada:', error);
});

const normalizeDigits = (value) => String(value || '').replace(/\D/g, '');

const pickBestPhone = (candidates = []) => {
    const cleaned = candidates
        .map((v) => normalizeDigits(String(v).split('@')[0]))
        .filter(Boolean);

    // Priorizar formato Perú: 51 + 9 dígitos
    const pe = cleaned.find((n) => /^51\d{9}$/.test(n));
    if (pe) return pe;

    // Fallback internacional razonable
    const intl = cleaned.find((n) => /^\d{10,15}$/.test(n));
    return intl || '';
};

const extractPhoneFromCtx = (ctx = {}) => {
    const msg = ctx.message || {};
    const key = ctx.key || {};
    const candidates = [
        ctx.from,
        key.remoteJid,
        key.participant,
        key.participantPn,
        msg?.key?.remoteJid,
        msg?.key?.participant,
        msg?.sender,
        msg?.participant,
    ];

    return pickBestPhone(candidates);
};

const toPeruPhone = (value) => {
    const digits = normalizeDigits(value);
    if (!digits) return '';

    // 51 + 9 dígitos
    if (/^51\d{9}$/.test(digits)) return digits;
    // 9 dígitos local
    if (/^9\d{8}$/.test(digits)) return `51${digits}`;
    // Números largos con prefijos extra: tomar los últimos 9 si parecen móvil PE
    if (digits.length > 9) {
        const tail9 = digits.slice(-9);
        if (/^9\d{8}$/.test(tail9)) return `51${tail9}`;
    }

    return '';
};

const rememberRecentPhone = (phone) => {
    const normalized = toPeruPhone(phone);
    if (!normalized) return;

    const now = Date.now();
    recentNotifiedPhones.set(normalized, now);

    for (const [p, ts] of recentNotifiedPhones.entries()) {
        if (now - ts > RECENT_TTL_MS) recentNotifiedPhones.delete(p);
    }
};

const getRecentCandidatePhones = () => {
    const now = Date.now();
    const candidates = [];
    for (const [p, ts] of recentNotifiedPhones.entries()) {
        if (now - ts <= RECENT_TTL_MS) candidates.push(p);
    }
    return candidates;
};

const resolvePhoneForLocation = async (ctx = {}) => {
    const extracted = extractPhoneFromCtx(ctx);
    const peru = toPeruPhone(extracted);
    if (peru) return peru;

    // Fallback 1: destinatarios notificados recientemente
    const recentCandidates = getRecentCandidatePhones();
    if (recentCandidates.length === 1) {
        console.log('ℹ️ Fallback de número aplicado desde envío reciente:', recentCandidates[0]);
        return recentCandidates[0];
    }

    // Fallback: cuando WhatsApp envía LID en vez de número telefónico.
    const orders = await getOrdersForToday();
    const validPhones = (orders || [])
        .map((o) => toPeruPhone(o?.phone))
        .filter(Boolean);

    const uniquePhones = [...new Set(validPhones)];
    if (uniquePhones.length === 1) {
        console.log('ℹ️ Fallback de número aplicado desde orden única del día:', uniquePhones[0]);
        return uniquePhones[0];
    }

    return extracted;
};

// =========================================================
// 1. FLUJO: RESPUESTA CUANDO EL CLIENTE ENVÍA UBICACIÓN
// =========================================================
const flowUbicacionCliente = addKeyword(EVENTS.LOCATION)
    .addAction(async (ctx, { flowDynamic }) => {
        try {
            // --- EXTRAER EL NÚMERO REAL ---
            const phone = await resolvePhoneForLocation(ctx);

            if (!phone) {
                console.log('❌ No se pudo determinar el número del remitente.');
                console.log('DEBUG ctx.from:', ctx?.from);
                console.log('DEBUG key.remoteJid:', ctx?.key?.remoteJid);
                console.log('DEBUG key.participant:', ctx?.key?.participant);
                return;
            }

            console.log('📍 Ubicación recibida de (Número Procesado):', phone);

            const location = ctx.message?.locationMessage ||
                             ctx.message?.liveLocationMessage ||
                             ctx.message?.viewOnceMessageV2?.message?.locationMessage;

            if (!location) {
                console.log('❌ No se pudo extraer coordenadas del mensaje.');
                return;
            }

            const { degreesLatitude: lat, degreesLongitude: lon } = location;

            // ✅ RESPONDER AL CLIENTE (captura errores pero continúa)
            try {
                await flowDynamic('⏳ Guardando tu ubicación en el sistema de Trainyl...');
                await flowDynamic([
                    `✅ ¡Gracias por compartir tu ubicación!`,
                    `Tu ubicación ha sido registrada en nuestro sistema.`,
                    `🚚 El repartidor usará esta información para encontrarte. ¡Nos vemos pronto!`
                ]);
            } catch (err) {
                console.warn('⚠️ Error al enviar confirmación:', err?.message || err);
            }

            // 🔄 PROCESAR ODOO EN BACKGROUND (sin await = no bloquea al cliente)
            (async () => {
                try {
                    const order = await updateTrainylOrderLocation(phone, lat, lon);
                    if (order) {
                        console.log(`✅ Ubicación ACTUALIZADA en Odoo para orden: ${order.order_number}`);
                    } else {
                        console.log(`⚠️ Odoo no encontró orden activa para: ${phone}`);
                    }
                } catch (error) {
                    console.error('❌ Error al actualizar Odoo (background):', error?.message || error);
                }
            })();

        } catch (error) {
            console.error('Error al procesar ubicación:', error || 'sin detalle');
            try {
                await flowDynamic('❌ Hubo un error al procesar tu ubicación, pero fue registrada.');
            } catch (e) {
                console.error('No se pudo enviar mensaje de error al cliente:', e);
            }
        }
    });

// =========================================================
// 2. FUNCIÓN PRINCIPAL
// =========================================================
const main = async () => {
    const adapterDB = new MockAdapter();
    
    // --- AQUÍ SE CONFIGURA EL LOG SILENCIOSO ---
    const adapterProvider = createProvider(BaileysProvider);

    const adapterFlow = createFlow([flowUbicacionCliente]);

    await createBot({
        flow: adapterFlow,
        provider: adapterProvider,
        database: adapterDB,
    });

    console.log('🤖 Bot Trainyl iniciado y activo.');

    // --- CRON: ENVÍO DEL PRIMER MENSAJE ---
    cron.schedule('* * * * *', async () => {
        console.log('⏳ CRON: Buscando órdenes para envío inicial...');
        
        try {
            const orders = await getOrdersForToday();
            if (orders.length === 0) return;

            console.log(`📦 Procesando ${orders.length} órdenes...`);

            for (const order of orders) {
                if (order.phone) {
                    const phoneStr = String(order.phone).replace(/\D/g, '');
                    const finalPhone = phoneStr.startsWith('51') ? phoneStr : `51${phoneStr}`;
                    const jid = `${finalPhone}@s.whatsapp.net`;
                    const nombre = (order.fullname || 'Cliente').split(' ')[0];

                    const mensaje = `¡Hola ${nombre}! 👋\nSomos el equipo de entregas de *Trainyl*.\n\nHoy tenemos programada la entrega de tu pedido *${order.order_number}*.\n\nPor favor envíanos tu *Ubicación Actual* usando el botón del clip (📎). 🚚💨`;
                    
                    try {
                        await adapterProvider.sendText(jid, mensaje);
                        rememberRecentPhone(finalPhone);
                        await markWhatsAppAsSent(order.id);
                        console.log(`✅ Primer mensaje enviado a: ${finalPhone}`);
                    } catch (err) {
                        console.log(`❌ Error enviando a ${finalPhone}`);
                    }
                    await new Promise(r => setTimeout(r, 5000));
                }
            }
        } catch (error) {
            console.error('❌ Error en el CRON:', error);
        }
    });
};

main().catch((error) => {
    console.error('❌ Error fatal al iniciar el bot:', error);
});