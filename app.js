const { createBot, createProvider, createFlow } = require('@bot-whatsapp/bot');
const BaileysProvider = require('@bot-whatsapp/provider/baileys');
const MockAdapter = require('@bot-whatsapp/database/mock'); 
const cron = require('node-cron');

// Importamos las funciones exactas desde odooService
const { 
    getOrdersForBot, 
    markAsNotified, 
    incrementReminderCount 
} = require('./odooService');

let globalAdapterProvider = null;

const main = async () => {
    try {
        const adapterFlow = createFlow([]);
        const adapterProvider = createProvider(BaileysProvider);
        const adapterDB = new MockAdapter();

        globalAdapterProvider = adapterProvider;

        await createBot({
            flow: adapterFlow,
            provider: adapterProvider,
            database: adapterDB,
        });

        console.log('✅ Bot inicializado y conectado.');
        console.log('📡 Cron programado cada 3 minutos para pruebas.');

        // CRON: Ejecución cada 3 minutos
        cron.schedule('*/2 * * * *', async () => {
            console.log('🤖 Cron: Revisando pendientes en Odoo...');
            
            try {
                const orders = await getOrdersForBot();
                
                if (!orders || orders.length === 0) {
                    return console.log('😴 Sin órdenes pendientes en Odoo.');
                }

                for (const order of orders) {
                    try {
                        const label = order.order_number || `ID:${order.id}`;
                        let cleanPhone = order.phone ? order.phone.replace(/\D/g, '') : '';
                        
                        if (!cleanPhone) {
                            console.log(`⚠️ Orden ${label} saltada: No tiene teléfono.`);
                            continue;
                        }

                        // Asegurar formato internacional (Ej: Perú 51)
                        if (cleanPhone.length === 9 && !cleanPhone.startsWith('51')) {
                            cleanPhone = `51${cleanPhone}`;
                        }
                        
                        const jid = `${cleanPhone}@s.whatsapp.net`;
                        console.log(`📨 Enviando a ${label} (${cleanPhone})...`);

                        // Enviar el mensaje que Odoo ya redactó
                        await globalAdapterProvider.sendText(jid, order.message);

                        // Actualizar estado en Odoo según el flujo
                        if (order.status === 'sent') {
                            await markAsNotified(order.id);
                            console.log(`✅ Primer mensaje marcado en Odoo para ${label}`);
                        } else if (order.status === 'notified') {
                            await incrementReminderCount(order.id);
                            console.log(`⏰ Recordatorio registrado en Odoo para ${label}`);
                        }

                        // Esperar 3 segundos entre envíos (Anti-Ban)
                        await new Promise(r => setTimeout(r, 3000));

                    } catch (sendError) {
                        console.error(`❌ Error enviando mensaje de orden ${order.id}:`, sendError.message);
                    }
                }
                console.log('🏁 Ciclo de cron finalizado.');
            } catch (error) {
                console.error('❌ Error crítico en la petición a Odoo:', error.message);
            }
        });

    } catch (initError) {
        console.error('💥 Error fatal al arrancar el bot:', initError.message);
    }
};

main();