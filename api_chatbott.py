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
                        # Cambiar estado a 'location_received' para detener recordatorios
                        order.write({'whatsapp_bot_status': 'location_received'})
                        updated_orders.append(order.order_number)
                        _logger.info(f"✅ Ubicación guardada para la orden: {order.order_number} | Estado: location_received")
                
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

    @http.route('/api/bot/get_reminder_orders', type='json', auth='none', methods=['POST'], csrf=False)
    def api_get_reminder_orders(self, **kwargs):
        """Obtiene órdenes que necesitan recordatorio (sin ubicación después de X minutos, máximo 2 recordatorios)"""
        token = request.httprequest.headers.get('Authorization')
        if token != 'MiTokenSecreto123': 
            return {'status': 'error'}
        
        from datetime import datetime, timedelta
        
        today = fields.Date.today()
        # Recordatorio después de X minutos (PRUEBA: 1 minuto para debug, cambiar a 30 para producción)
        reminder_minutes = 1
        time_threshold = datetime.now() - timedelta(minutes=reminder_minutes)
        
        _logger.info(f"🔍 Buscando órdenes para recordatorio. Umbral de tiempo: {time_threshold}")
        
        # Órdenes que:
        # - Se enviaron el primer mensaje (notified)
        # - NO tienen ubicación
        # - Hace más de X minutos que se marcaron como notified
        # - Menos de 2 recordatorios enviados
        orders = request.env['trainyl.order'].sudo().search_read([
            ('delivery_date', '=', today),
            ('whatsapp_bot_status', '=', 'notified'),  # Ya se envió primer mensaje (esperando respuesta)
            ('latitude', '=', False),  # Sin latitud
            ('longitude', '=', False),  # Sin longitud
            ('google_maps_url', '=', False),  # Sin URL
            ('write_date', '<=', time_threshold),  # Escribida ANTES del umbral = hace más de 30 minutos
            ('reminder_count', '<', 2)  # Máximo 2 recordatorios
        ], ['id', 'order_number', 'fullname', 'phone', 'reminder_count', 'write_date'])
        
        _logger.info(f"✅ Encontradas {len(orders)} órdenes para recordatorio")
        if orders:
            for order in orders:
                _logger.info(f"   - Orden {order['order_number']}: {order['fullname']} | Recordatorios: {order['reminder_count']} | Última actualización: {order['write_date']}")
        
        return {'status': 'success', 'orders': orders}

    @http.route('/api/bot/increment_reminder_count', type='json', auth='none', methods=['POST'], csrf=False)
    def api_increment_reminder_count(self, **kwargs):
        """Incrementa el contador de recordatorios de una orden"""
        params = request.params
        token = request.httprequest.headers.get('Authorization')
        if token != 'MiTokenSecreto123': 
            return {'status': 'error'}
        
        order_id = params.get('order_id')
        order = request.env['trainyl.order'].sudo().browse(order_id)
        if order.exists():
            current_count = order.reminder_count or 0
            order.write({'reminder_count': current_count + 1})
            _logger.info(f"📬 Recordatorio #{current_count + 1} para orden: {order.order_number}")
            return {'status': 'success', 'reminder_count': current_count + 1}
        return {'status': 'error'}

    @http.route('/api/bot/mark_sent', type='json', auth='none', methods=['POST'], csrf=False)
    def api_mark_sent(self, **kwargs):
        params = request.params
        token = request.httprequest.headers.get('Authorization')
        if token != 'MiTokenSecreto123': 
            return {'status': 'error'}
        
        order_id = params.get('order_id')
        order = request.env['trainyl.order'].sudo().browse(order_id)
        if order.exists():
            # Cambiar de 'sent' a 'notified' después de enviar el primer mensaje
            order.write({'whatsapp_bot_status': 'notified'})
            _logger.info(f"✅ Orden {order.order_number} marcada como notified (primer mensaje enviado)")
            return {'status': 'success'}
        return {'status': 'error'}