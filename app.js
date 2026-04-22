const { createBot, createProvider, createFlow, addKeyword, EVENTS } = require('@bot-whatsapp/bot');
const BaileysProvider = require('@bot-whatsapp/provider/baileys');
const MockAdapter = require('@bot-whatsapp/database/mock');
const cron = require('node-cron');
const { updateTrainylOrderLocation, getOrdersForToday, markWhatsAppAsSent, getReminderOrders, incrementReminderCount } = require('./odooService');

const RECENT_TTL_MS = 30 * 60 * 1000;
const recentNotifiedPhones = new Map();
let globalAdapterProvider = null; // 🔴 GLOBAL para acceso desde flows

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

    // Priorizar formato Perú: 51 + 9 dígitos (EXACTAMENTE 11 dígitos totales)
    const pe = cleaned.find((n) => /^51\d{9}$/.test(n));
    if (pe) {
        console.log(`✅ pickBestPhone: Número Perú válido encontrado: ${pe}`);
        return pe;
    }

    // Fallback: móvil local sin 51 (9 + 8 dígitos)
    const localMobile = cleaned.find((n) => /^9\d{8}$/.test(n));
    if (localMobile) {
        const withPrefix = `51${localMobile}`;
        console.log(`✅ pickBestPhone: Móvil local convertido a: ${withPrefix}`);
        return withPrefix;
    }

    // Rechazar LIDs y números muy largos (> 15 dígitos)
    const valid = cleaned.filter((n) => n.length <= 15);
    
    // Fallback internacional razonable (10-15 dígitos)
    const intl = valid.find((n) => /^\d{10,15}$/.test(n));
    if (intl) {
        console.log(`✅ pickBestPhone: Número internacional: ${intl}`);
        return intl;
    }

    console.log(`⚠️ pickBestPhone: No se encontró número válido. Candidatos: ${JSON.stringify(cleaned)}`);
    return '';
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
    
    // Si extrajimos un número Perú válido, usarlo
    if (peru) {
        console.log(`✅ resolvePhoneForLocation: Número Perú extraído: ${peru}`);
        return peru;
    }

    // Si el número extraído es un LID largo, ignorarlo y usar fallbacks
    const isLID = extracted && extracted.length > 15;
    if (isLID) {
        console.log(`⚠️ resolvePhoneForLocation: Número parece ser LID (${extracted}), usando fallbacks...`);
    }

    // Fallback 1: destinatarios notificados recientemente
    const recentCandidates = getRecentCandidatePhones();
    if (recentCandidates.length === 1) {
        console.log(`✅ resolvePhoneForLocation: Fallback 1 - Número reciente: ${recentCandidates[0]}`);
        return recentCandidates[0];
    }

    // Fallback 2: única orden del día
    const orders = await getOrdersForToday();
    const validPhones = (orders || [])
        .map((o) => toPeruPhone(o?.phone))
        .filter(Boolean);

    const uniquePhones = [...new Set(validPhones)];
    if (uniquePhones.length === 1) {
        console.log(`✅ resolvePhoneForLocation: Fallback 2 - Única orden del día: ${uniquePhones[0]}`);
        return uniquePhones[0];
    }

    // Si hay múltiples órdenes, preferir el número reciente sobre el extraído (si parece LID)
    if (isLID && recentCandidates.length > 0) {
        console.log(`✅ resolvePhoneForLocation: Fallback 3 - Usando número reciente (LID detectado)`);
        return recentCandidates[0];
    }

    console.log(`⚠️ resolvePhoneForLocation: No se pudo determinar número. Extraído: ${extracted}, Recientes: ${recentCandidates.length}, Órdenes hoy: ${uniquePhones.length}`);
    return extracted;
};

// =========================================================
// 1. FLUJO: RESPUESTA CUANDO EL CLIENTE ENVÍA UBICACIÓN
// =========================================================
const flowUbicacionCliente = addKeyword(EVENTS.LOCATION)
    .addAction(async (ctx) => {
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
            const jid = `${phone}@c.us`;

            // ✅ RESPONDER AL CLIENTE CON adapterProvider (igual que CRON)
            console.log('📨 Enviando confirmación con adapterProvider...');
            
            // 🔄 PROCESAR ODOO EN BACKGROUND (sin await = no bloquea)
            (async () => {
                try {
                    const order = await updateTrainylOrderLocation(phone, lat, lon);
                    if (order) {
                        console.log(`✅ Ubicación ACTUALIZADA en Odoo para orden: ${order.order_number}`);
                        
                        // Enviar confirmación DESPUÉS de actualizar Odoo
                        if (globalAdapterProvider) {
                            await globalAdapterProvider.sendText(jid, '✅ ¡Gracias por compartir tu ubicación!\n\nTu ubicación ha sido registrada en nuestro sistema.\n\n🚚 El repartidor usará esta información para encontrarte. ¡Nos vemos pronto!');
                        }
                    } else {
                        console.log(`⚠️ Odoo no encontró orden activa para: ${phone}`);
                    }
                } catch (error) {
                    console.error('❌ Error al actualizar Odoo (background):', error?.message || error);
                }
            })();

        } catch (error) {
            console.error('Error al procesar ubicación:', error || 'sin detalle');
        }
    });

// =========================================================
// 2. FUNCIÓN PRINCIPAL
// =========================================================
const main = async () => {
    const adapterDB = new MockAdapter();
    
    // --- AQUÍ SE CONFIGURA EL LOG SILENCIOSO ---
    const adapterProvider = createProvider(BaileysProvider);
    globalAdapterProvider = adapterProvider; // 🔴 GUARDAR EN GLOBAL

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
            console.log(`📦 getOrdersForToday retornó ${orders.length} órdenes`);
            if (orders.length === 0) {
                console.log('ℹ️ No hay órdenes para enviar');
                return;
            }

            console.log(`📦 Procesando ${orders.length} órdenes...`);

            for (const order of orders) {
                console.log(`📬 Orden: ${order.order_number} | Teléfono: ${order.phone}`);
                if (order.phone) {
                    const phoneStr = String(order.phone).replace(/\D/g, '');
                    const finalPhone = phoneStr.startsWith('51') ? phoneStr : `51${phoneStr}`;
                    const jid = `${finalPhone}@s.whatsapp.net`;
                    const nombre = (order.fullname || 'Cliente').split(' ')[0];
                    const address = order.address || 'No especificada';
                    const district = order.district || 'No especificado';

                    const mensaje = `¡Hola ${nombre}! 👋\nSomos el equipo de entregas de *Trainyl* 🚚\nEstamos preparando la entrega de tu pedido *${order.order_number}*.\n📌 *Dirección registrada:* ${address}\n📌 *Distrito:* ${district}\n📍 Para que nuestro motorizado te ubique fácilmente, por favor comparte tu ubicación usando el botón 📎\n¡Gracias! 💚\n— Equipo de entregas Trainyl`;
                    
                    try {
                        console.log(`📨 Enviando mensaje a ${jid}...`);
                        await adapterProvider.sendText(jid, mensaje);
                        rememberRecentPhone(finalPhone);
                        console.log(`✅ Mensaje enviado. Ahora llamando a markWhatsAppAsSent(${order.id})...`);
                        const marked = await markWhatsAppAsSent(order.id);
                        console.log(`✅ markWhatsAppAsSent retornó: ${marked}`);
                    } catch (err) {
                        console.log(`❌ Error enviando a ${finalPhone}:`, err.message);
                    }
                    await new Promise(r => setTimeout(r, 5000));
                }
            }
        } catch (error) {
            console.error('❌ Error en el CRON:', error);
        }
    });

    // --- CRON: ENVÍO DE RECORDATORIOS (cada 5 minutos - PRUEBA) ---
    cron.schedule('*/3 * * * *', async () => {
        console.log('⏳ CRON RECORDATORIO: Buscando órdenes que necesitan recordatorio...');
        
        try {
            const reminders = await getReminderOrders();
            if (reminders.length === 0) return;

            console.log(`📬 Enviando recordatorios a ${reminders.length} clientes...`);

            for (const order of reminders) {
                if (order.phone) {
                    const phoneStr = String(order.phone).replace(/\D/g, '');
                    const finalPhone = phoneStr.startsWith('51') ? phoneStr : `51${phoneStr}`;
                    const jid = `${finalPhone}@s.whatsapp.net`;
                    const nombre = (order.fullname || 'Cliente').split(' ')[0];
                    const reminderNum = (order.reminder_count || 0) + 1;

                    const mensaje = `¡Hola ${nombre}! 👋\n\nAún no hemos recibido tu ubicación para el pedido *${order.order_number}*.\n\n📍 Por favor comparte tu ubicación usando el botón 📎 para que nuestro motorizado pueda ubicarte sin inconvenientes.\n\n¡Gracias!\n— Equipo de entregas Trainyl 💚`;
                    
                    try {
                        await globalAdapterProvider.sendText(jid, mensaje);
                        // Incrementar contador solo si se envió exitosamente
                        await incrementReminderCount(order.id);
                        console.log(`✅ Recordatorio #${reminderNum} enviado a: ${finalPhone} (${order.order_number})`);
                    } catch (err) {
                        console.log(`❌ Error enviando recordatorio a ${finalPhone}`);
                    }
                    await new Promise(r => setTimeout(r, 3000));
                }
            }
        } catch (error) {
            console.error('❌ Error en el CRON de recordatorios:', error);
        }
    });
};

main().catch((error) => {
    console.error('❌ Error fatal al iniciar el bot:', error);
});