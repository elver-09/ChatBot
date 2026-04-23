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

// Cambiamos el nombre para que coincida con lo que el Bot espera
const getOrdersForBot = async () => {
    try {
        const response = await api.post('/api/bot/get_orders', { jsonrpc: "2.0", params: {} });
        return response.data.result.orders || [];
    } catch (error) {
        console.error('❌ Error API get_orders:', error.message);
        return [];
    }
};

const markAsNotified = async (order_id) => {
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

const incrementReminderCount = async (order_id) => {
    try {
        const response = await api.post('/api/bot/increment_reminder', {
            jsonrpc: "2.0",
            params: { order_id: order_id }
        });
        return response.data?.result?.status === 'success';
    } catch (error) {
        console.error('❌ Error API increment_reminder:', error.message);
        return false;
    }
};

// EXPORTACIÓN: Los nombres deben ser EXACTOS a como los llamas en app.js
module.exports = { getOrdersForBot, markAsNotified, incrementReminderCount };