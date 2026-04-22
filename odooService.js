const axios = require('axios');

const ODOO_URL = 'https://trainyl.digilab.pe';
const API_TOKEN = 'MiTokenSecreto123';

const api = axios.create({
    baseURL: ODOO_URL,
    headers: { 
        'Authorization': API_TOKEN,
        'Content-Type': 'application/json' 
    }
});

const getOrdersForToday = async () => {
    try {
        const response = await api.post('/api/bot/get_orders', { jsonrpc: "2.0", params: {} });
        return response.data.result.orders || [];
    } catch (error) {
        console.error('❌ Error API get_orders:', error.message);
        return [];
    }
};

const updateTrainylOrderLocation = async (phone, lat, lon) => {
    try {
        // Formato estándar de URL que contiene el @lat,lon para el regex de Odoo
        const googleMapsUrl = `https://www.google.com/maps?q=${lat},${lon}&z=17&t=k&ll=@${lat},${lon}`;
        
        console.log(`📡 Enviando ubicación a Odoo - phone: ${phone}, lat: ${lat}, lon: ${lon}`);
        
        const response = await api.post('/api/bot/update_location', {
            jsonrpc: "2.0",
            params: { 
                phone: phone, 
                lat: lat, 
                lon: lon,
                maps_url: googleMapsUrl 
            }
        });
        
        console.log(`📬 Respuesta de Odoo:`, JSON.stringify(response.data, null, 2));
        
        const res = response.data.result;
        
        // Si Odoo responde pero no fue exitoso (ej. not_found), devolvemos null para el flujo normal.
        if (!res || res.status !== 'success') {
            console.warn(`⚠️ Respuesta no exitosa de Odoo para update_location (phone: ${phone}):`, res);
            return null;
        }
        
        return { order_number: res.order_number };

    } catch (error) {
        const statusCode = error.response?.status || 'N/A';
        const errorData = error.response?.data;
        const errorMsg = error.response?.data?.result?.message || 
                        error.response?.data?.message || 
                        error.message || 
                        'Error desconocido en API update_location';
        
        console.error(`❌ Error API update_location (phone: ${phone}, status: ${statusCode})`);
        console.error(`   Mensaje: ${errorMsg}`);
        console.error(`   Respuesta completa:`, JSON.stringify(errorData, null, 2));
        
        // Rechazamos la promesa con un error explícito para evitar el 'undefined'
        throw new Error(`API Error: ${errorMsg} (Status: ${statusCode})`);
    }
};

const markWhatsAppAsSent = async (order_id) => {
    try {
        const response = await api.post('/api/bot/mark_sent', {
            jsonrpc: "2.0",
            params: { order_id: order_id }
        });
        return response.data?.result?.status === 'success';
    } catch (error) {
        console.error('❌ Error API mark_sent:', error.message);
        return false;
    }
};

const getReminderOrders = async () => {
    try {
        const response = await api.post('/api/bot/get_reminder_orders', { jsonrpc: "2.0", params: {} });
        const orders = response.data.result.orders || [];
        console.log(`📬 getReminderOrders retornó ${orders.length} órdenes:`, JSON.stringify(orders, null, 2));
        return orders;
    } catch (error) {
        console.error('❌ Error API get_reminder_orders:', error.message);
        if (error.response?.data) {
            console.error('   Respuesta Odoo:', JSON.stringify(error.response.data, null, 2));
        }
        return [];
    }
};

const incrementReminderCount = async (order_id) => {
    try {
        const response = await api.post('/api/bot/increment_reminder_count', {
            jsonrpc: "2.0",
            params: { order_id: order_id }
        });
        return response.data?.result?.status === 'success';
    } catch (error) {
        console.error('❌ Error API increment_reminder_count:', error.message);
        return false;
    }
};

module.exports = { getOrdersForToday, updateTrainylOrderLocation, markWhatsAppAsSent, getReminderOrders, incrementReminderCount };