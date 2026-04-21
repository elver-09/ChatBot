from odoo import http, fields
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class TrainylBotController(http.Controller):

    @http.route('/api/bot/update_location', type='json', auth='none', methods=['POST'], csrf=False)
    def api_update_location(self, **kwargs):
        # Los datos JSON-RPC siempre vienen dentro de 'params'
        params = request.params
        
        token = request.httprequest.headers.get('Authorization')
        if token != 'MiTokenSecreto123':
            return {'status': 'error', 'message': 'Unauthorized'}

        phone_raw = params.get('phone')
        lat = params.get('lat')
        lon = params.get('lon')
        maps_url = params.get('maps_url')

        # --- LÓGICA DE LIMPIEZA DE TELÉFONO ---
        # 1. Quitamos cualquier caracter que no sea número
        clean_phone = "".join(filter(str.isdigit, str(phone_raw))) if phone_raw else ''
        
        # 2. Obtenemos los últimos 9 dígitos (estándar Perú) para evitar problemas con el '51'
        short_phone = clean_phone[-9:] if len(clean_phone) >= 9 else clean_phone
        
        _logger.info(f"🤖 Bot procesando ubicación. Original: {phone_raw} | Limpio: {short_phone}")

        if not short_phone:
            return {'status': 'error', 'message': 'No phone provided'}

        # Buscamos TODAS las órdenes del cliente que NO tengan ubicación:
        # Usamos 'ilike' con '%' para que encuentre el número aunque en Odoo esté guardado con espacios o +51
        orders = request.env['trainyl.order'].sudo().search([
            ('phone', 'ilike', '%' + short_phone),
            ('whatsapp_bot_status', 'in', ['sent', 'notified']),
            ('delivery_date', '=', fields.Date.today()),  # Solo de hoy
            ('latitude', '=', False),  # Sin latitud
            ('longitude', '=', False),  # Sin longitud
            ('google_maps_url', '=', False)  # Sin URL
        ], order='id desc')

        if orders:
            try:
                updated_orders = []
                # Actualizar TODAS las órdenes encontradas
                for order in orders:
                    success = order.sudo().update_location_from_bot(lat, lon, maps_url)
                    if success:
                        updated_orders.append(order.order_number)
                        _logger.info(f"✅ Ubicación guardada para la orden: {order.order_number}")
                
                if updated_orders:
                    return {'status': 'success', 'orders': updated_orders, 'count': len(updated_orders)}
                else:
                    _logger.error(f"❌ No se pudo actualizar ninguna orden")
                    return {'status': 'error', 'message': 'Failed to update locations'}
            except Exception as e:
                _logger.error(f"❌ Exception en update_location_from_bot: {str(e)}")
                return {'status': 'error', 'message': str(e)}
        
        _logger.warning(f"⚠️ No se encontró orden activa en Odoo para el número: {short_phone}")
        return {'status': 'not_found'}

    @http.route('/api/bot/get_orders', type='json', auth='none', methods=['POST'], csrf=False)
    def api_get_orders(self, **kwargs):
        token = request.httprequest.headers.get('Authorization')
        if token != 'MiTokenSecreto123': 
            return {'status': 'error'}
        
        today = fields.Date.today() 
        # Solo buscamos órdenes que estén en estado 'sent' (listas para el primer contacto)
        orders = request.env['trainyl.order'].sudo().search_read([
            ('delivery_date', '=', today),
            ('whatsapp_bot_status', '=', 'sent')
        ], ['id', 'order_number', 'fullname', 'phone', 'address', 'district', 'partner_id'])
        
        return {'status': 'success', 'orders': orders}

    @http.route('/api/bot/mark_sent', type='json', auth='none', methods=['POST'], csrf=False)
    def api_mark_sent(self, **kwargs):
        params = request.params
        token = request.httprequest.headers.get('Authorization')
        if token != 'MiTokenSecreto123': 
            return {'status': 'error'}
        
        order_id = params.get('order_id')
        order = request.env['trainyl.order'].sudo().browse(order_id)
        if order.exists():
            # Cambiamos a 'notified' para que el CRON no la vuelva a procesar
            order.write({'whatsapp_bot_status': 'notified'})
            return {'status': 'success'}
        return {'status': 'error'}