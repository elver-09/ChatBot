from odoo import models, fields, api
import base64
import io
import barcode
import logging
import re
import requests
from barcode.codex import Code128
from barcode.writer import ImageWriter
from unidecode import unidecode
from odoo.exceptions import ValidationError
from datetime import datetime, date
from odoo.exceptions import UserError
import urllib.parse

barcode.base.Barcode.default_writer_options['write_text'] = False

_logger = logging.getLogger(__name__)

class TrainylOrder(models.Model):
    _name = 'trainyl.order'
    _description = 'Trainyl Order'
    _rec_name = 'order_number'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # INFO TRAINYL
    order_number = fields.Char(string='Numero de Orden', required=True)
    cud_number = fields.Char(string='Número de CUB')
    unique_code = fields.Char(string='Código Único')
    store_id = fields.Char(string='Id Store')
    fullname = fields.Char(string='Nombre del Cliente')
    phone = fields.Char(string='Teléfono')
    email = fields.Char(string='Email')
    address = fields.Char(string='Dirección')
    reference = fields.Char(string='Referencia')
    country = fields.Char(string='País')
    city = fields.Char(string='Ciudad')
    delivery_date = fields.Date(string='Fecha de Planificación', required=True)
    delivery_date_created = fields.Date(string='Fecha de Compromiso', copy=False)
    district = fields.Char(string='Distrito')
    delivery_store = fields.Char(string='Tienda de Delivery')
    working_day = fields.Char(string='Día de Trabajo')
    dispatch_id = fields.Char(string='DNI')
    client_code = fields.Char(string='Código de Cliente(No usar)')
    seller_code = fields.Char(string='Código de Seller(No usar)')
    trainyl_seller_code = fields.Char(string='Código de Seller', required=True)
    trainyl_marketplace_code = fields.Char(string='Código de Marketplace')
    pickup_address = fields.Char(string='Dirección de Recojo')
    expected_status = fields.Selection([
        ('draft', 'BORRADOR'),
        ('in_trainyl', 'EN TRAINYL'),  
        ('ready_for_drivin', 'LISTO PARA DRIVIN'),  
        ('pending', 'PISTOLEADO'),
        ('in_transport', 'EN TRANSPORTE'),
        # PENDIENTE
        ('start_of_route', 'INICIO DE RUTA'),
        # DELIVERED
        ('delivered', 'ENTREGADO'),
        ('in_planification', 'EN PLANIFICACIÓN'),
        ('sent_do_yango', 'ENVIADO POR YANGO'),
        # REJECTED
        ('cancelled', 'RECHAZADO'),
        ('blocked', 'BLOQUEADO'), 
        ('anulled', 'ANULADO'),
        ('returned', 'DEVUELTO A TIENDA'),
        ('hand_to_hand', 'MANO A MANO'),
        ('cancelled_origin', 'CANCELADO DESDE ORIGEN'),
    ], string='Estado de Envio', default='draft')
    new_status_orders = fields.Selection([
        ('draft', 'BORRADOR'),
        ('reprogrammed', 'REPROGRAMADO'),
        ('in_trainyl', 'EN TRAINYL'),
        ('in_planification', 'PLANIFICADO'),
        ('blocked', 'BLOQUEADO'),
        ('in_transport', 'EN TRANSPORTE'),
        ('start_of_route', 'INICIO DE RUTA'),
        ('delivered', 'ENTREGADO'),
        ('cancelled', 'RECHAZADO')], string='Nuevo Estado', default='draft')

    trainyl_done_status = fields.Boolean(string='Se actualizó estado en Tienda?')
    state = fields.Selection([
        ('backlog', 'Backlog'),
        ('to_do', 'Por Hacer'),
        ('in_progress', 'En Proceso'),
        ('to_approve', 'Para Aprobar'),
        ('done', 'Terminado'),
        ('blocked', 'Bloqueado')
    ], string='Estado')
    partner_id = fields.Many2one('res.partner', string='Cliente Trainyl', domain="[('trainyl_enabled_client', '=', True)]")
    date_pickup= fields.Date(string='Fecha Pick Up')
    barcode_img = fields.Binary(string='Codigo de Barras', compute="_generate_barcode", store=True)
    seller= fields.Char(string="Seller")
    log_ids = fields.One2many('trainyl.log', 'order_id', string='Logs')
    mobile_log_ids = fields.One2many('trainyl.mobile.log', 'order_id', string='Logs Mobile')
    order_line_ids= fields.One2many('trainyl.order.line', 'order_id', string='Lineas de pedido')
    area_id = fields.Many2one('l10n_pe.res.city.district', string='Distrito Real' )
    driver_id = fields.Many2one('hr.employee', string='Conductor', domain="[('job_id', '=', 'Conductor')]")
    fleet_id = fields.Many2one('trainyl.fleet', string='Flota')
    route_id = fields.Many2one('trainyl.logistics.line', string='Ruta', domain="[('logistics_id.date_planning', '=', delivery_date), ('logistics_id.order_type', '=', order_type_id.code)]")
    order_type_id = fields.Many2one('trainyl.service.type', string='Tipo de Orden')
    logistics_line_id = fields.Many2one('trainyl.logistics.line', string='Línea de Planificación', domain="[('logistics_id.date_planning', '=', delivery_date), ('logistics_id.order_type', '=', order_type_id.code)]")
    vehicle_type = fields.Many2one('trainyl.fleet.type', string='Tipo de Vehículo')
    order_size = fields.Selection([
        ('small', 'Pequeño'),
        ('medium', 'Mediano'),
        ('large', 'Grande'),
    ], string='Tamaño de Orden')
    check_rescheduled = fields.Boolean(string='Reprogramado', default=False, readonly=True)
    planning_status = fields.Selection([
        ('planned', 'PLANIFICADO'),
        ('confirmed', 'CONFIRMADO'),
        ('delivered', 'ENTREGADO'),
        ('cancelled', 'CANCELADO'),
    ], string='Estado de Planificación')
    store_selection = fields.Selection([
        ('1189', 'SFS Comas'),
        ('1024', 'SFS Los Olivos'),
        ('1157', 'SFS San Juan de Lurigancho'),
        ('20024', 'Los Olivos'),
        ('20089', 'Comas'),
        ('20057', 'San Juan Lurigancho'),
    ], string='Tienda de Envío',
    compute='_compute_store_selection_computed',
    store=True)
    google_maps_url = fields.Char(string='Google Maps Cliente URL')
    latitude = fields.Char(string='Latitud')
    longitude = fields.Char(string='Longitud')
    google_maps_generated = fields.Boolean(string='JSON', default=False)
    google_maps_json = fields.Text(string='JSON')
    route_sequence = fields.Integer(string='Secuencia en Ruta', help='Orden de entrega en la ruta (1=primero, 2=segundo, etc)')
    distance_from_pickup = fields.Float(string='Distancia desde Recojo (km)', compute='_compute_distance_from_pickup', store=True, help='Distancia en km desde el punto de recojo')
    address_default = fields.Boolean(string='Dirección por Defecto')
    location_url = fields.Char(string='Ubicación Cliente', widget='url')
    location_url_status = fields.Selection([
        ('with_url', 'Tiene URL'),
        ('without_url', 'Sin URL')
    ], string='Estado de URL', default='without_url')
    delivery_date_str = fields.Char(string='Fecha Compromiso Formateada', compute='_compute_delivery_date_str', store=False)
    location_received = fields.Boolean(string='Ubicación recibida', default=False)
    pending_whatsapp = fields.Boolean(default=True, string="WhatsApp pendiente")
    create_date = fields.Datetime(string='Fecha de Creación', readonly=True)
    import_json = fields.Text(string="Datos de importación (JSON)")
    send_to_yango = fields.Boolean(string='Enviar a Yango', default=False)
    whatsapp_first_sent = fields.Boolean(string='Primer WhatsApp enviado', default=False)
    route_id = fields.Many2one('trainyl.routes.extra', string = 'Rutas', ondelete='set null')
    zone_id = fields.Many2one('trainyl.zone', string='Zona')
    repro_entry = fields.Selection([
        ('entry', 'Ingreso'),
        ('reprogramming', 'Reprogramación')], string='Entrada', default='entry', readonly=True)

    reason_rejection_id = fields.Many2one('trainyl.rejection.reason', string='Razón de Rechazo')
    comment_rejection = fields.Text(string='Comentario de Rechazo')
    rejection_count = fields.Integer(string='Veces Rechazada', store=True, readonly=True)
    scanned = fields.Boolean(string='Orden escaneada', default=False, readonly=True)
    not_scanned = fields.Boolean(string='Orden sin escanear', default=False, readonly=True)
    is_multipack = fields.Boolean(string='¿Es multibulto?', default=False)
    multipack_count = fields.Integer(string='Contador multibulto', default=0, readonly=True)
    # CAMPO PARA CONTROLAR EL BOT DE WHATSAPP
    whatsapp_bot_status = fields.Selection([
        ('pending', 'Pendiente (Ignorar)'),
        ('sent', 'Autorizado para Enviar'), # 👈 Tú seleccionas este en Odoo
        ('notified', 'Mensaje Enviado por el Bot') # 👈 El bot lo cambia a este
    ], string='Estado WhatsApp Bot', default='pending', tracking=True)

    def _sync_route_cart_line_state(self):
        """
        Sincroniza el estado de las líneas del carrito según el estado de la orden:
        - new_status_orders == 'in_transport' -> assigned
        - en cualquier otro caso -> in_cart
        """
        line_model = self.env['trainyl.route.cart.line']
        for order in self:
            target_state = 'assigned' if order.new_status_orders == 'in_transport' else 'in_cart'
            lines = line_model.search([
                ('order_id', '=', order.id),
                ('state', '!=', target_state),
            ])
            if lines:
                lines.write({'state': target_state})

    def action_send_whatsapp(self):
        self.ensure_one()
        
        if not self.phone:
            raise UserError("No se puede enviar el WhatsApp porque el campo de Teléfono está vacío.")
        
        # Obtener el nombre del cliente (solo primera palabra)
        customer_name = self.fullname.split()[0] if self.fullname else ""
        
        # Obtener el nombre del partner para mostrar en el pedido (ej: Ripley)
        partner_name = self.partner_id.name if self.partner_id else "Tienda"
        
        # Construir el mensaje personalizado
        message = (
            f"Hola {customer_name}, somos el equipo de entregas de Trainyl. "
            f"Estamos preparando tu entrega para mañana y necesitamos tu ubicación para llegar sin inconvenientes.\n"
            f"Pedido(s): {self.order_number} ({partner_name})\n"
            f"Dirección registrada: {self.address or 'No especificada'}\n"
            f"Distrito: {self.district or 'No especificado'}\n"
            f"¿Podrías compartirnos tu ubicación, por favor?\n"
            f"— Equipo de entregas Trainyl"
        )
        
        encoded_message = urllib.parse.quote(message)
        
        number = ''.join(filter(str.isdigit, self.phone))

        self.whatsapp_first_sent = True
        
        whatsapp_url = f"https://wa.me/{number}?text={encoded_message}"
        
        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }

    def action_send_whatsapp_location_short(self):
        self.ensure_one()

        if not self.phone:
            raise UserError("No se puede enviar el WhatsApp porque el campo de Teléfono está vacío.")

        customer_name = self.fullname.split()[0] if self.fullname else "cliente"

        message = (
            f"Hola {customer_name}, ¿nos podrías compartir tu ubicación, por favor? "
            f"Esto nos ayudará a hacer efectiva tu entrega.\n"
            f"— Equipo de entregas Trainyl"
        )

        encoded_message = urllib.parse.quote(message)

        number = ''.join(filter(str.isdigit, self.phone))

        if not number:
            raise UserError("No se encontró un número de teléfono válido para enviar WhatsApp.")

        whatsapp_url = f"https://wa.me/{number}?text={encoded_message}"

        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }

    def action_set_in_trainyl(self):
        for record in self:
            if record.new_status_orders in ['draft', 'reprogrammed']:
                record.new_status_orders = 'in_trainyl'
                record._log_change("Estado cambiado a 'EN TRAINYL' por acción manual.")
    
    def _create_mobile_log(self, message, driver_id=None, vehicle_id=None, new_status_orders=None, reason_rejection_id=None, reason_for_rejection=None, photo_1=None, photo_2=None, photo_3=None):
        """Método helper para crear logs móviles"""
        self.ensure_one()
        resolved_driver_id = (
            driver_id
            or (self.driver_id.id if self.driver_id else False)
            or (self.route_id.driver_id.id if self.route_id and self.route_id.driver_id else False)
        )
        resolved_vehicle_id = (
            vehicle_id
            or (self.fleet_id.id if self.fleet_id else False)
            or (self.route_id.fleet_id.id if self.route_id and self.route_id.fleet_id else False)
        )
        self.env['trainyl.mobile.log'].create({
            'order_id': self.id,
            'driver_id': resolved_driver_id,
            'vehicle_id': resolved_vehicle_id,
            'new_status_orders': new_status_orders or self.new_status_orders,
            'message': message,
            'reason_rejection_id': reason_rejection_id,
            'reason_for_rejection': reason_for_rejection,
            'photo_1': photo_1,
            'photo_2': photo_2,
            'photo_3': photo_3,
        })

    def _create_mobile_log_wrong_route_attempt(self, attempted_driver_id=None, attempted_route_id=None):
        """Crear log cuando se intenta escanear una orden en una ruta incorrecta"""
        self.ensure_one()
        
        attempted_driver = self.env['hr.employee'].browse(attempted_driver_id) if attempted_driver_id else None
        attempted_route = self.env['trainyl.routes.extra'].browse(attempted_route_id) if attempted_route_id else None
        correct_driver = self.route_id.driver_id if self.route_id else None
        correct_route = self.route_id
        
        attempted_route_name = attempted_route.name if attempted_route else 'N/A'
        attempted_driver_name = attempted_driver.name if attempted_driver else 'N/A'
        correct_route_name = correct_route.name if correct_route else 'Sin asignar'
        correct_driver_name = correct_driver.name if correct_driver else 'Sin asignar'
        
        message = (
            f"⚠️ INTENTO DE ESCANEO EN LA RUTA '{attempted_route_name}' CON CONDUCTOR '{attempted_driver_name}' | "
            f"Orden pertenece a: RUTA '{correct_route_name}' CON CONDUCTOR '{correct_driver_name}'"
        )
        
        self.env['trainyl.mobile.log'].create({
            'order_id': self.id,
            'driver_id': attempted_driver_id or False,
            'vehicle_id': attempted_route.fleet_id.id if attempted_route and attempted_route.fleet_id else False,
            'new_status_orders': self.new_status_orders,
            'message': message,
            'reason_rejection_id': False,
            'reason_for_rejection': False,
            'photo_1': False,
            'photo_2': False,
            'photo_3': False,
        })
    
    def write(self, vals):
        _logger.info("Escribiendo Orden - delivery_date en vals: %s", vals.get('delivery_date'))
        """Registra cambios relevantes en el log y actualiza el área si cambia la ciudad."""
        # Evitar que la fecha congelada de creación se modifique luego de creada la orden
        # vals.pop('delivery_date_created', None)

        # Lista de campos relevantes para registrar en el log
        relevant_fields = ['drivin_order_status', 'expected_status']

        # Actualizar el área si cambia la ciudad
        if 'district' in vals:
            if vals['district']:  # Verificar si 'district' tiene un valor
                district = self.search_district(vals['district'])
                if district:
                    _logger.info("Distrito encontrado en write: %s", district.name)
                    vals['area_id'] = district.id
                else:
                    _logger.warning("No se encontró un distrito coincidente para: %s", vals['district'])
                    # No sobrescribir area_id si no se encuentra un distrito
                    vals.pop('area_id', None)
            else:
                # Si district es None o vacío, no modificar area_id
                vals.pop('area_id', None)

        # --- Lógica para actualizar líneas de planificación si cambia la ruta ---
        for order in self:
            old_logistics_line = order.logistics_line_id
            old_area = order.area_id

            # Guardar el nuevo logistics_line_id si viene en vals
            new_logistics_line_id = vals.get('logistics_line_id', False)
            # Si se está cambiando la ruta y es diferente a la anterior
            if new_logistics_line_id and new_logistics_line_id != (old_logistics_line.id if old_logistics_line else False):
                new_logistics_line = self.env['trainyl.logistics.line'].browse(new_logistics_line_id)

                # Quitar punto y distrito de la línea anterior si corresponde
                if old_logistics_line:
                    old_logistics_line.point = max(0, old_logistics_line.point - 1)
                    # Si ya no hay órdenes de ese distrito en la línea, quitar el distrito
                    distritos_restantes = old_logistics_line.order_ids.filtered(lambda o: o.area_id == old_area and o.id != order.id)
                    if not distritos_restantes and old_area:
                        old_logistics_line.district_ids = [(3, old_area.id, 0)]

                # Sumar punto y agregar distrito a la nueva línea si corresponde
                if new_logistics_line:
                    new_logistics_line.point += 1
                    if order.area_id and order.area_id.id not in new_logistics_line.district_ids.ids:
                        new_logistics_line.district_ids = [(4, order.area_id.id, 0)]

        # Registrar cambios relevantes en el log y detectar cambios a "delivered"
        for order in self:
            # 🔥 REGISTRAR CAMBIOS EN MOBILE LOG
            # Detectar cambio de conductor
            if 'driver_id' in vals and vals['driver_id'] != (order.driver_id.id if order.driver_id else False):
                new_driver = self.env['hr.employee'].browse(vals['driver_id']) if vals['driver_id'] else False
                if new_driver:
                    order._create_mobile_log(
                        message=f"Conductor asignado: {new_driver.name}",
                        driver_id=new_driver.id,
                        vehicle_id=vals.get('fleet_id') or (order.fleet_id.id if order.fleet_id else False)
                    )
                else:
                    order._create_mobile_log(
                        message="Conductor removido",
                        vehicle_id=order.fleet_id.id if order.fleet_id else False,
                    )
            
            # Detectar cambio de vehículo
            if 'fleet_id' in vals and vals['fleet_id'] != (order.fleet_id.id if order.fleet_id else False):
                new_vehicle = self.env['trainyl.fleet'].browse(vals['fleet_id']) if vals['fleet_id'] else False
                if new_vehicle:
                    order._create_mobile_log(
                        message=f"Vehículo asignado: {new_vehicle.license_plate}",
                        driver_id=order.driver_id.id if order.driver_id else False,
                        vehicle_id=new_vehicle.id
                    )
            
            # Detectar cambio de ruta
            if 'route_id' in vals and vals['route_id'] != (order.route_id.id if order.route_id else False):
                old_route = order.route_id
                new_route = self.env['trainyl.routes.extra'].browse(vals['route_id']) if vals['route_id'] else False
                
                if new_route:
                    order._create_mobile_log(
                        message=f"Orden planificada en ruta: {new_route.name}",
                        driver_id=new_route.driver_id.id if new_route.driver_id else False,
                        vehicle_id=new_route.fleet_id.id if new_route.fleet_id else False,
                    )
                    # ✨ Crear log en la ruta
                    new_route._create_route_log(
                        action_type='order_added',
                        message=f"Orden {order.order_number} agregada a la ruta",
                        order_id=order.id
                    )
                else:
                    order._create_mobile_log(
                        message="Orden removida de la ruta",
                        driver_id=order.driver_id.id if order.driver_id else False,
                        vehicle_id=order.fleet_id.id if order.fleet_id else False,
                    )
                    # ✨ Crear log en la ruta anterior si existe
                    if old_route:
                        old_route._create_route_log(
                            action_type='order_removed',
                            message=f"Orden {order.order_number} removida de la ruta",
                            order_id=order.id
                        )
                        # 🗑️ Eliminar ruta si quedó vacía después de remover la orden
                        # Usar intent sin el after() que no existe en psycopg2
                        if old_route.order_ids and len(old_route.order_ids) == 0:
                            old_route.unlink()
            
            # Detectar cambio de estado
            if 'new_status_orders' in vals and vals['new_status_orders'] != order.new_status_orders:
                status_labels = dict(order._fields['new_status_orders'].selection)
                old_status = status_labels.get(order.new_status_orders, order.new_status_orders)
                new_status = status_labels.get(vals['new_status_orders'], vals['new_status_orders'])
                
                # Incrementar contador si el nuevo estado es 'cancelled' (RECHAZADO)
                if vals['new_status_orders'] == 'cancelled':
                    vals['rejection_count'] = order.rejection_count + 1
                    _logger.info(f"Orden {order.order_number} rechazada. Contador actualizado a {vals['rejection_count']}")
                
                order._create_mobile_log(
                    message=f"Estado cambiado de '{old_status}' a '{new_status}'",
                    driver_id=order.driver_id.id if order.driver_id else False,
                    vehicle_id=order.fleet_id.id if order.fleet_id else False,
                    new_status_orders=vals['new_status_orders']
                )
            
            # Detectar cambio de razón de rechazo
            if 'reason_rejection_id' in vals:
                reason = self.env['trainyl.rejection.reason'].browse(vals['reason_rejection_id']) if vals['reason_rejection_id'] else False
                if reason:
                    order._create_mobile_log(
                        message=f"Razón de rechazo: {reason.name}",
                        driver_id=order.driver_id.id if order.driver_id else False,
                        vehicle_id=order.fleet_id.id if order.fleet_id else False,
                        reason_rejection_id=reason.id,
                        reason_for_rejection=vals.get('reject_comment', '')
                    )
            
            # Log para cambios genéricos en el sistema antiguo
            changes = []
            for field_name, new_value in vals.items():
                # Verificar si el campo es relevante
                if field_name not in relevant_fields:
                    continue

                old_value = order[field_name]
                # Registrar solo si el valor realmente cambió
                if old_value != new_value:
                    if isinstance(order._fields[field_name], (fields.Many2one, fields.One2many, fields.Many2many)):
                        changes.append(f"{field_name}: [Valor cambiado]")
                    else:
                        changes.append(f"{field_name}: {old_value} -> {new_value}")

            if changes:
                order._log_change("\n".join(changes))

        # Normalizar el teléfono peruano si se proporciona          
        if 'phone' in vals and vals['phone']:
            vals['phone'] = self._normalize_peru_phone(vals['phone'])

        # Actualizar el estado de URL si se modifica google_maps_url
        if 'google_maps_url' in vals:
            vals['location_url_status'] = 'with_url' if (vals.get('google_maps_url') and vals['google_maps_url'].strip()) else 'without_url'

            # Si llega URL, intentar autocompletar lat/lon
            if vals.get('google_maps_url') and vals['google_maps_url'].strip():
                lat, lon = self._extract_coords_from_google_maps_url(vals['google_maps_url'])
                if lat and lon:
                    vals['latitude'] = lat
                    vals['longitude'] = lon
                    vals['google_maps_generated'] = True

        # Asignar zona automáticamente si se actualiza area_id
        if 'area_id' in vals and vals['area_id']:
            zone_line = self.env['trainyl.zone.line'].search([
                ('district_id', '=', vals['area_id'])
            ], limit=1)
            if zone_line:
                vals['zone_id'] = zone_line.zone_id.id
                _logger.info("Zona actualizada automáticamente para el distrito ID %s: %s", vals['area_id'], zone_line.zone_id.name)
            else:
                _logger.warning("No se encontró una zona para el distrito ID: %s", vals['area_id'])
                vals['zone_id'] = False
        elif 'area_id' in vals and not vals['area_id']:
            # Si se limpia area_id, también limpiar zone_id
            vals['zone_id'] = False

        result = super(TrainylOrder, self).write(vals)

        if 'new_status_orders' in vals:
            self._sync_route_cart_line_state()

        return result
    
    def unlink(self):
        """Eliminar rutas vacías después de eliminar órdenes"""
        routes_to_check = self.mapped('route_id').filtered(lambda r: r)
        result = super(TrainylOrder, self).unlink()
        # Verificar y eliminar rutas que quedaron vacías
        for route in routes_to_check:
            route.action_delete_if_empty()
        return result
    
    def _log_change(self, message):
        """ Crea un registro en trainyl.log """
        self.ensure_one()
        self.env['trainyl.log'].create({
            'message': message,
            'order_id': self.id,
        })

    def action_import_orders(self):
        pass

    @api.model
    def create(self, vals):
        _logger.info("Creando Orden - delivery_date: %s", vals.get('delivery_date'))

        # Congelar la fecha de compromiso al momento de crear la orden
        # (si no viene explícitamente, copiar la delivery_date inicial)
        if not vals.get('delivery_date_created') and vals.get('delivery_date'):
            vals['delivery_date_created'] = vals['delivery_date']

        if 'order_number' in vals and vals['order_number'] and 'trainyl_seller_code' in vals and vals['trainyl_seller_code']:
            existing_order = self.search([
                ('order_number', '=', vals['order_number']),
                ('trainyl_seller_code', '=', vals['trainyl_seller_code'])
            ], limit=1)
            if existing_order:
                _logger.warning("Ya existe una orden con el número %s y trainyl_seller_code %s. No se creará una nueva.", vals['order_number'], vals['trainyl_seller_code'])
                return existing_order

        if 'district' in vals:
            district = self.search_district(vals['district'])
            vals['area_id'] = district.id if district else False
        else:
            vals['area_id'] = False

        # Asignar zona automáticamente si se proporciona area_id
        if vals.get('area_id'):
            zone_line = self.env['trainyl.zone.line'].search([
                ('district_id', '=', vals['area_id'])
            ], limit=1)
            if zone_line:
                vals['zone_id'] = zone_line.zone_id.id
                _logger.info("Zona asignada automáticamente para el distrito: %s", zone_line.zone_id.name)
            else:
                vals['zone_id'] = False

        if 'phone' in vals and vals['phone']:
            vals['phone'] = self._normalize_peru_phone(vals['phone'])

        # Actualizar el estado de URL al crear
        if 'google_maps_url' in vals:
            vals['location_url_status'] = 'with_url' if (vals.get('google_maps_url') and vals['google_maps_url'].strip()) else 'without_url'

            # Si llega URL al crear, intentar autocompletar lat/lon
            if vals.get('google_maps_url') and vals['google_maps_url'].strip():
                lat, lon = self._extract_coords_from_google_maps_url(vals['google_maps_url'])
                if lat and lon:
                    vals['latitude'] = lat
                    vals['longitude'] = lon
                    vals['google_maps_generated'] = True

        order = super(TrainylOrder, self).create(vals)
        #order.action_get_geolocation()
        #_logger.info("Se creó la URL de Google Maps: %s", order.google_maps_url or "No generada")

        order._sync_route_cart_line_state()

        return order

    def start_route(self):
        """Actualiza las órdenes a 'start_of_route' y las agrega a la cola."""
        for record in self:
            if True:
                record.expected_status = 'start_of_route'
                _logger.info("Orden %s actualizada a 'start_of_route'.", record.order_number)
                record._log_change(f"Se inició la ruta de la orden {record.order_number}.")
                _logger.info("Contenido del record start_route: %s", record.read()[0])
                # Crear un registro en la cola
                self.env['trainyl.queue'].create({
                    'order_id': record.id,
                    'state_to_send': 'start_of_route',
                    'priority': 1,
                    'delivery_date': record.delivery_date,
                })
                record._log_change(f"Se envió la orden {record.order_number} a la cola con estado 'En ruta'.")

    def set_in_trainyl(self):
        for record in self:
            if record.expected_status in ['draft', 'pending']:
                record.expected_status = 'in_trainyl'

    def action_update_orders_in_store(self):
        pass
    
    def action_update_format_label(self):
        pass
    
    @api.depends("order_number")
    def _generate_barcode(self):
        for record in self:
            if record.order_number:
                # Limpiar caracteres no válidos del número de orden
                sanitized_order_number = record.order_number
                try:
                    barcode_io = io.BytesIO()
                    barcode_obj = Code128(sanitized_order_number, writer=ImageWriter())
                    barcode_obj.write(barcode_io, options=dict(font_size=0))

                    record.barcode_img = base64.b64encode(barcode_io.getvalue())
                except barcode.errors.IllegalCharacterError as e:
                    _logger.error(f"Error al generar el código de barras para '{record.order_number}': {str(e)}")
                    record.barcode_img = False
            else:
                record.barcode_img = False

    def _get_report_values(self, docids, data=None):
        docs = self.env['trainyl.order'].browse(docids)
        def group_records(records, group_size=2):
            """Agrupa los registros en sublistas de tamaño group_size"""
            return [records[i:i+group_size] for i in range(0, len(records), group_size)]
        grouped_docs = group_records(docs, 2)
        return {
            'doc_ids': docids,
            'doc_model': 'trainyl.order',
            'docs': docs,
            'docs_grouped': grouped_docs,
            'res_company': self.env.company,
        }
    
    def _calculate_distance_haversine(self, lat1, lon1, lat2, lon2):
        """
        Calcula la distancia en kilómetros entre dos puntos usando la fórmula Haversine.
        Parámetros:
            lat1, lon1: Latitud y longitud del punto de recojo (en grados decimales)
            lat2, lon2: Latitud y longitud de la orden/entrega (en grados decimales)
        Retorna: Distancia en kilómetros
        """
        from math import radians, cos, sin, asin, sqrt
        
        try:
            # Convertir strings a float
            lat1 = float(lat1) if lat1 else 0
            lon1 = float(lon1) if lon1 else 0
            lat2 = float(lat2) if lat2 else 0
            lon2 = float(lon2) if lon2 else 0
            
            if lat1 == 0 and lon1 == 0 or lat2 == 0 and lon2 == 0:
                return 0
            
            # Radio de la Tierra en kilómetros
            R = 6371
            
            # Convertir grados a radianes
            lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
            
            # Diferencias
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            
            # Fórmula Haversine
            a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
            c = 2 * asin(sqrt(a))
            distance = R * c
            
            return round(distance, 2)
        except (ValueError, TypeError):
            _logger.warning(f"Error calculando distancia con coordenadas: {lat1}, {lon1}, {lat2}, {lon2}")
            return 0

    @api.depends('order_type_id', 'latitude', 'longitude')
    def _compute_distance_from_pickup(self):
        """Calcula la distancia desde el punto de recojo (pickup_origin) hasta la orden."""
        for record in self:
            if record.order_type_id and record.order_type_id.pickup_origin_id:
                pickup = record.order_type_id.pickup_origin_id
                if record.latitude and record.longitude:
                    record.distance_from_pickup = self._calculate_distance_haversine(
                        pickup.latitude, 
                        pickup.longitude, 
                        record.latitude, 
                        record.longitude
                    )
                else:
                    record.distance_from_pickup = 0
            else:
                record.distance_from_pickup = 0

    @staticmethod
    def _normalize_text(text):
        """Normaliza el texto eliminando mayúsculas, tildes y espacios extra."""
        return unidecode(text.strip().lower()) if text else ''
    
    def search_district(self, district_name):
        """Busca un distrito en Lima o Callao por nombre normalizado."""
        if not district_name:
            return False

        normalized_input = self._normalize_text(district_name)
        # IDs de ciudad Lima y Callao
        lima_city = self.env.ref('l10n_pe.city_pe_1501', raise_if_not_found=False)
        callao_city = self.env.ref('l10n_pe.city_pe_0701', raise_if_not_found=False)
        city_ids = []
        if lima_city:
            city_ids.append(lima_city.id)
        if callao_city:
            city_ids.append(callao_city.id)
        domain = [('city_id', 'in', city_ids)] if city_ids else []
        districts = self.env['l10n_pe.res.city.district'].search(domain)
        for district in districts:
            if normalized_input == self._normalize_text(district.name):
                return district
        return False

    @api.onchange('district')
    def _onchange_district(self):
        """Actualiza el campo area_id basado en el valor ingresado en district."""
        if self.district:
            district = self.search_district(self.district)
            if district:
                _logger.info("Distrito encontrado en onchange: %s", district.name)
                self.area_id = district.id
            else:
                _logger.warning("No se encontró un distrito coincidente para: %s", self.district)
                self.area_id = False
        else:
            self.area_id = False

    @api.onchange('area_id')
    def _onchange_area_id_zone(self):
        """Actualiza zone_id automáticamente cuando cambia area_id basándose en trainyl.zone.line."""
        if self.area_id:
            # Buscar la zona que contiene este distrito en trainyl.zone.line
            zone_line = self.env['trainyl.zone.line'].search([
                ('district_id', '=', self.area_id.id)
            ], limit=1)
            if zone_line:
                _logger.info("Zona encontrada para el distrito %s: %s", self.area_id.name, zone_line.zone_id.name)
                self.zone_id = zone_line.zone_id.id
            else:
                _logger.warning("No se encontró una zona para el distrito: %s", self.area_id.name)
                self.zone_id = False
        else:
            self.zone_id = False

    def action_cancel_order(self):
        for record in self:
            _logger.info(f"--- INICIO action_cancel_order para orden {record.order_number} (ID: {record.id}) ---")

            # 2.1 Cambiar estado
            record.expected_status = 'returned'
            record._log_change(f"Se canceló la orden {record.order_number} a través del Menu Action.")

            # Log básico
            partner = record.partner_id
            partner_email = partner.email if partner else None
            partner_name = partner.name if partner else "Sin partner"

            _logger.info(f"Partner Name: {partner_name}")
            _logger.info(f"Partner Email: {partner_email}")

            # 2.4 Detectar si es Ripley
            is_ripley = partner_name and "RIPLEY" in partner_name.upper()
            _logger.info(f"¿Es Ripley? {is_ripley}")

            # ➤ Correos según la orden
            if is_ripley:
                # Correos principales SOLO para Ripley
                email_to = "scaceresl@ripley.com.pe,gpapa@ripley.com.pe,jriosa@ripley.com.pe"
            else:
                # Correos para cliente Trainyl (validación)
                if not (partner_email and partner_email.strip()):
                    _logger.warning(f"El cliente '{partner_name}' no tiene correo válido.")
                    raise ValidationError(f"El cliente '{partner_name}' no tiene un correo electrónico válido.")
                
                email_to = partner_email
            # 2.3 Copias internas SIEMPRE
            email_cc = "churtado@trainyl.com,operaciones@trainyl.com,adezar@trainyl.com"

            _logger.info(f"Email TO: {email_to}")
            _logger.info(f"Email CC: {email_cc}")

            # 2.2 Obtener plantilla existente
            try:
                template = self.env.ref('trainyl_base.email_template_trainyl_returned')
            except Exception as e:
                _logger.error(f"No se encontró la plantilla de correo: {e}")
                raise

            # Enviar correo usando la plantilla pero con email_to + CC personalizados
            try:
                _logger.info(f"Enviando correo para la orden {record.order_number}")

                template.send_mail(
                    record.id,
                    force_send=True,
                    email_values={
                        "email_to": email_to,
                        "email_cc": email_cc,
                    }
                )

                _logger.info("Correo enviado correctamente.")
            except Exception as e:
                _logger.error(f"Error al enviar el correo: {e}")
                raise

            _logger.info(f"--- FIN action_cancel_order para orden {record.order_number} ---")
    
    def action_return_hand_to_hand(self):
        for record in self:
            _logger.info(f"--- INICIO action_return_hand_to_hand para orden {record.order_number} (ID: {record.id}) ---")

            # Cambiar estado
            record.expected_status = 'hand_to_hand'
            record._log_change(f"Se devolvió mano a mano la orden {record.order_number}.")

            partner = record.partner_id
            partner_email = partner.email if partner else None
            partner_name = partner.name if partner else "Sin partner"

            _logger.info(f"Partner Name: {partner_name}")
            _logger.info(f"Partner Email: {partner_email}")

            # Detectar si es Ripley
            is_ripley = partner_name and "RIPLEY" in partner_name.upper()
            _logger.info(f"¿Es Ripley? {is_ripley}")

            # Correos principales
            if is_ripley:
                email_to = "scaceresl@ripley.com.pe,gpapa@ripley.com.pe,jriosa@ripley.com.pe"
            else:
                if not (partner_email and partner_email.strip()):
                    _logger.warning(f"El cliente '{partner_name}' no tiene correo válido.")
                    raise ValidationError(f"El cliente '{partner_name}' no tiene un correo electrónico válido.")
                email_to = partner_email

            # Copias internas
            email_cc = "churtado@trainyl.com,operaciones@trainyl.com,adezar@trainyl.com"

            _logger.info(f"Email TO: {email_to}")
            _logger.info(f"Email CC: {email_cc}")

            # Obtener plantilla (se reutiliza la misma)
            try:
                template = self.env.ref('trainyl_base.email_template_trainyl_returned')
            except Exception as e:
                _logger.error(f"No se encontró la plantilla: {e}")
                raise

            # Envío
            try:
                template.send_mail(
                    record.id,
                    force_send=True,
                    email_values={
                        "email_to": email_to,
                        "email_cc": email_cc,
                    }
                )
                _logger.info("Correo enviado correctamente.")
            except Exception as e:
                _logger.error(f"Error al enviar correo: {e}")
                raise

            _logger.info(f"--- FIN action_return_hand_to_hand para orden {record.order_number} ---")

    def action_cancel_from_origin(self):
        """Anula la orden y actualiza el estado a 'CANCELADO DESDE ORIGEN'."""
        for record in self:
            record.expected_status = 'cancelled_origin'
            record._log_change(f"Se anuló la orden {record.order_number} desde el origen a través del Menu Action.")

    @api.depends('store_id')
    def _compute_store_selection_computed(self):
        for record in self:
            if record.store_id and record.store_id in dict(self._fields['store_selection'].selection):
                record.store_selection = record.store_id
            else:
                record.store_selection = False

    @api.depends('delivery_date')
    def _compute_delivery_date_str(self):
        for rec in self:
            if rec.delivery_date:
                rec.delivery_date_str = rec.delivery_date.strftime('%d-%m-%Y')
            else:
                rec.delivery_date_str = ''

    @api.onchange('google_maps_url')
    def _onchange_google_maps_url(self):
        """Actualiza el estado de URL en tiempo real cuando se escribe en google_maps_url."""
        self.location_url_status = 'with_url' if (self.google_maps_url and self.google_maps_url.strip()) else 'without_url'
        
        # Intentar autocompletar coordenadas desde la URL de Google Maps
        if self.google_maps_url and self.google_maps_url.strip():
            lat, lon = self._extract_coords_from_google_maps_url(self.google_maps_url)
            if lat and lon:
                self.latitude = lat
                self.longitude = lon
                self.google_maps_generated = True

    def _clean_address(self, address):
        # Elimina referencias, pisos, departamentos, etc.
        address = re.split(r'Referencia:|/|piso|departamento|Depto|Dpto|esquina|Esq', address, flags=re.IGNORECASE)[0]
        return address.strip()

    def _parse_coords_text(self, text):
        """Extrae lat/lon desde un texto en formato 'lat,lon'."""
        if not text:
            return False, False

        match = re.search(r'(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)', str(text))
        if not match:
            return False, False

        try:
            lat = float(match.group(1))
            lon = float(match.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return str(lat), str(lon)
        except (TypeError, ValueError):
            return False, False

        return False, False

    def _resolve_short_url(self, short_url):
        """Resuelve URLs cortas de Google Maps (maps.app.goo.gl) siguiendo redirecciones."""
        if not short_url:
            return short_url
        
        try:
            # Solo intentar resolver si es una URL corta conocida
            if 'maps.app.goo.gl' not in str(short_url):
                return short_url
            
            # Intentar resolver con HEAD request
            try:
                response = requests.head(short_url, allow_redirects=True, timeout=5)
                resolved_url = response.url
                _logger.info(f"URL corta resuelta con HEAD: {short_url} -> {resolved_url}")
                return resolved_url
            except Exception as head_error:
                _logger.warning(f"HEAD request falló para {short_url}: {head_error}")
                
                # Intentar con GET request si HEAD falla
                try:
                    response = requests.get(short_url, allow_redirects=True, timeout=5, stream=True)
                    resolved_url = response.url
                    _logger.info(f"URL corta resuelta con GET: {short_url} -> {resolved_url}")
                    return resolved_url
                except Exception as get_error:
                    _logger.warning(f"GET request falló para {short_url}: {get_error}")
                    return short_url
        
        except Exception as e:
            _logger.warning(f"No se pudo resolver URL corta {short_url}: {e}")
            return short_url

    def _extract_coords_from_google_maps_url(self, maps_url):
        """Intenta extraer coordenadas de una URL de Google Maps en formatos comunes."""
        if not maps_url:
            return False, False

        try:
            original_url = maps_url
            # 0) Resolver URLs cortas primero
            if 'maps.app.goo.gl' in str(maps_url):
                _logger.info(f"Detectada URL corta, intentando resolver: {maps_url}")
                maps_url = self._resolve_short_url(maps_url)
                _logger.info(f"URL después de resolución: {maps_url}")
            
            decoded_url = urllib.parse.unquote(str(maps_url).strip())
            _logger.info(f"URL decodificada: {decoded_url}")
            parsed = urllib.parse.urlparse(decoded_url)
            query = urllib.parse.parse_qs(parsed.query)

            # 1) Parámetros de query: q, query, ll, destination, origin
            address_from_url = None
            for key in ['q', 'query', 'll', 'destination', 'origin']:
                value = query.get(key, [False])[0]
                if value:
                    _logger.info(f"Parámetro '{key}': {value}")
                    lat, lon = self._parse_coords_text(value)
                    if lat and lon:
                        _logger.info(f"✅ Coordenadas encontradas en query param '{key}': lat={lat}, lon={lon}")
                        return lat, lon
                    # Si no son coordenadas, podría ser una dirección
                    if key == 'q' and not address_from_url:
                        address_from_url = value

            # 2) Formato con @lat,lon,zoom
            match_at = re.search(r'@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)', decoded_url)
            if match_at:
                _logger.info(f"Patrón @lat,lon encontrado: {match_at.group(1)}, {match_at.group(2)}")
                lat, lon = self._parse_coords_text(f"{match_at.group(1)},{match_at.group(2)}")
                if lat and lon:
                    _logger.info(f"✅ Coordenadas extraídas formato @lat,lon: lat={lat}, lon={lon}")
                    return lat, lon

            # 3) Formato interno con !3dLAT!4dLON
            match_data = re.search(r'!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)', decoded_url)
            if match_data:
                _logger.info(f"Patrón !3d/!4d encontrado: {match_data.group(1)}, {match_data.group(2)}")
                lat, lon = self._parse_coords_text(f"{match_data.group(1)},{match_data.group(2)}")
                if lat and lon:
                    _logger.info(f"✅ Coordenadas extraídas formato !3d/!4d: lat={lat}, lon={lon}")
                    return lat, lon

            # 4) Caso en el que el usuario pega directamente "lat,lon"
            lat, lon = self._parse_coords_text(decoded_url)
            if lat and lon:
                _logger.info(f"✅ Coordenadas extraídas formato directo lat,lon: lat={lat}, lon={lon}")
                return lat, lon
            
            # 5) Si se encontró una dirección en el parámetro 'q', usar Geocoding API como último recurso
            if address_from_url:
                _logger.info(f"Se encontró dirección en URL: {address_from_url}. Usando Google Geocoding API...")
                lat, lon = self._geocode_address(address_from_url)
                if lat and lon:
                    _logger.info(f"✅ Coordenadas obtenidas de Geocoding API: lat={lat}, lon={lon}")
                    return lat, lon
            
            _logger.warning(f"❌ No se encontraron coordenadas en ninguno de los formatos soportados para: {original_url}")

        except Exception as e:
            _logger.error(f"❌ Excepción al extraer coordenadas de {maps_url}: {e}", exc_info=True)

        return False, False
    
    def _geocode_address(self, address):
        """Usa Google Geocoding API para convertir una dirección a coordenadas."""
        if not address:
            return False, False
        
        try:
            api_key = self.env['ir.config_parameter'].sudo().get_param('trainyl_base.google_maps_api_key')
            if not api_key:
                _logger.warning("API Key de Google Maps no configurada. No se puede geolocalizar la dirección.")
                return False, False
            
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                "address": address,
                "key": api_key
            }
            
            _logger.info(f"Llamando Geocoding API con dirección: {address}")
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                datos = response.json()
                if datos.get("results"):
                    location = datos["results"][0]["geometry"]["location"]
                    lat = location["lat"]
                    lon = location["lng"]
                    _logger.info(f"✅ Geocoding exitoso: {address} -> lat={lat}, lon={lon}")
                    return str(lat), str(lon)
                else:
                    _logger.warning(f"Geocoding API no encontró resultados para: {address}")
                    return False, False
            else:
                _logger.error(f"Error en Geocoding API: {response.status_code}")
                return False, False
        
        except Exception as e:
            _logger.error(f"Error al llamar Geocoding API: {e}")
            return False, False

    # funcion para obtener geolocalización de Google Maps de las ordenes
    def action_get_geolocation(self):
        for record in self:
            lat, lon = False, False
            
            # 1. Intentar extraer desde la URL de Google Maps si ya existe
            if record.google_maps_url and record.google_maps_url.strip():
                lat, lon = record._extract_coords_from_google_maps_url(record.google_maps_url)
            
            # 2. Si no hay coordenadas de la URL, usar la Dirección + Distrito
            if not lat or not lon:
                if record.address:
                    direccion_partes = [record.address]
                    if record.area_id:
                        direccion_partes.append(record.area_id.name)
                    if record.city:
                        direccion_partes.append(record.city)
                    if record.country:
                        direccion_partes.append(record.country)
                    else:
                        direccion_partes.append("Perú")
                    
                    direccion_completa = ", ".join(filter(None, direccion_partes))
                    _logger.info(f"Buscando coordenadas por dirección: {direccion_completa}")
                    lat, lon = record._geocode_address(direccion_completa)
                else:
                    raise UserError(f"La orden {record.order_number} no tiene 'URL de Google Maps' ni 'Dirección' para geolocalizar.")
            
            # 3. Guardar las coordenadas y generar el enlace
            if lat and lon:
                record.latitude = lat
                record.longitude = lon
                record.google_maps_generated = True
                record.google_maps_url = f"https://www.google.com/maps?q={lat},{lon}"
                record.location_url_status = 'with_url'
                _logger.info(f"Coordenadas obtenidas y guardadas para la orden {record.order_number}: lat={lat}, lon={lon}")
            else:
                raise UserError(f"No se pudo obtener coordenadas para la orden {record.order_number}. Verifique la dirección ingresada.")

    # funcion para enviar mensaje de WhatsApp masivo
    def action_send_whatsapp_massive(self):
        for order in self:
            try:
                order.send_whatsapp_order_message()
                order.pending_whatsapp = False
            except Exception as e:
                _logger.error(f"Error enviando WhatsApp masivo para la orden {order.order_number}: {e}")

    # funcion para enviar mensaje de WhatsApp con plantilla
    def send_whatsapp_order_message(self):
        for order in self:
            # 1. Nombre del cliente
            nombre_cliente = order.fullname or order.partner_id.name or "cliente"
            # 2. Fecha de compromiso
            fecha_compromiso = order.delivery_date.strftime('%d-%m-%Y') if order.delivery_date else "Fecha no disponible"
            # 3. Numero de la orden
            numero_orden = order.order_number or "Número de orden no disponible"
            # 4. Detalle del pedido
            productos_list = []
            for linea in order.order_line_ids:
                des = linea.product_des
                cantidad = linea.quantity
                try:
                    cantidad_float = float(cantidad or 0)
                    if not des or cantidad_float <= 0:
                        continue
                    productos_list.append(f"- {des} (x{cantidad_float})")
                except ValueError:
                    continue

            productos_plain = " • ".join(productos_list) if productos_list else "Sin productos registrados"
            productos_html = "<br>".join(productos_list) if productos_list else "Sin productos registrados"

            telefono = self._normalize_peru_phone(order.phone)
            _logger.info(f"Enviando mensaje plantilla WhatsApp a {telefono} para {nombre_cliente}")

            try:
                self.env['whatsapp.api'].send_message_template(
                    telefono,
                    'trainyl_prd_01',
                    nombre_cliente,
                    fecha_compromiso,
                    numero_orden,
                    productos_plain.strip(),
                    lang_code='es'
                )

                order.message_post(
                    body=f"📤 Mensaje WhatsApp enviado a {telefono}:{productos_html}",
                    subtype_xmlid="mail.mt_note"
                )

            except Exception as e:
                _logger.error(f"Error al enviar mensaje WhatsApp: {e}")
                order.message_post(
                    body=f"<span style='color:red'>❌ Error al enviar WhatsApp a {telefono}: {e}</span>",
                    subtype_xmlid="mail.mt_note"
                )

    # función para normalizar el teléfono peruano
    def _normalize_peru_phone(self, phone):
        """Devuelve el teléfono en formato +51XXXXXXXXX solo para celulares peruanos."""
        if not phone:
            return ""
        # Convertir a string por si viene como número
        phone = str(phone).strip()
        # Si hay múltiples números separados por "/" o similar, buscar el primero válido peruano
        if '/' in phone:
            phone_parts = phone.split('/')
            for part in phone_parts:
                part = part.strip()
                if part:
                    # Limpiar la parte y verificar si es un número peruano válido
                    cleaned_part = "".join(filter(str.isdigit, part))
                    
                    # Verificar si es potencialmente peruano
                    if self._is_potential_peru_number(cleaned_part):
                        phone = cleaned_part
                        break
            else:
                # Si no se encontró ningún número peruano válido, usar el último que tenga contenido
                phone_parts_filtered = [p.strip() for p in phone_parts if p.strip()]
                if phone_parts_filtered:
                    phone = "".join(filter(str.isdigit, phone_parts_filtered[-1]))
        
        # Eliminar caracteres no numéricos (incluyendo "/" al inicio)
        phone = "".join(filter(str.isdigit, phone))
        # Si está vacío después de limpiar, retornar vacío
        if not phone:
            return ""
        # Eliminar prefijos no estándar (ceros al inicio)
        while phone.startswith("0") and len(phone) > 9:
            phone = phone[1:]
        # Si es un número local (9 dígitos), agregar código de país
        if phone.startswith("9") and len(phone) == 9:
            phone = "51" + phone
        # Verificar que cumple con el formato correcto
        if phone.startswith("51") and len(phone) == 11 and phone[2] == "9":
            return f"+{phone}"
        # No cumple con formato válido
        _logger.warning(f"Teléfono no válido después de normalizar: {phone}")
        return ""

    def _is_potential_peru_number(self, phone):
        """Verifica si un número podría ser peruano."""
        if not phone:
            return False
        # Remover ceros al inicio
        while phone.startswith("0") and len(phone) > 9:
            phone = phone[1:]

        if phone.startswith("9") and len(phone) == 9:
            return True
        if phone.startswith("51") and len(phone) == 11 and phone[2] == "9":
            return True
        
        return False
    
    # función para enviar WhatsApp pendiente desde cron
    @api.model
    def cron_send_pending_whatsapp(self):
        today = date.today()
        
        # 1️ Buscar órdenes candidatas SOLO de hoy en estado borrador o pistoleadas
        candidate_orders = self.search([
            ('pending_whatsapp', '=', True),
            ('delivery_date', '=', today),                           # Solo las de hoy
            ('expected_status', 'in', ['draft', 'pending']),         # Borrador O pistoleadas
            ('phone', '!=', False),                                  # Que tengan teléfono
            ('phone', '!=', ''),
        ], order='delivery_date ASC, id ASC')                       # Por fecha de compromiso

        if not candidate_orders:
            _logger.info("📭 No hay órdenes en borrador/pistoleadas de WhatsApp pendientes para hoy")
            return
        
        _logger.info(f"📋 Encontradas {len(candidate_orders)} órdenes borrador/pistoleadas candidatas para WhatsApp de hoy")
        
        # 2️ Filtrar por cliente único (teléfono normalizado)
        processed_phones = set()
        unique_orders = []
        
        for order in candidate_orders:
            phone_normalized = order._normalize_peru_phone(order.phone)
            if phone_normalized and phone_normalized not in processed_phones:
                processed_phones.add(phone_normalized)
                unique_orders.append(order)
                status_name = "borrador" if order.expected_status == 'draft' else "pistoleada"
                _logger.info(f"📞 Agregada orden {status_name} {order.order_number} para {phone_normalized} (entrega: {order.delivery_date})")
            else:
                _logger.info(f"📞 Saltada orden {order.order_number} - teléfono duplicado o inválido")

        # 3️ Procesar solo 30 órdenes por ejecución (lotes)
        orders_to_process = unique_orders[:30]  # ✅ Solo 30 por vez

        _logger.info(f"🔄 Procesando {len(orders_to_process)} órdenes únicas de WhatsApp (borrador/pistoleadas)")
        
        success_count = 0
        error_count = 0
        sent_phones = []  # Lista para guardar teléfonos exitosos

        # 4️ Enviar mensajes
        for order in orders_to_process:
            try:
                order.send_whatsapp_order_message()
                order.pending_whatsapp = False  # Marcar como enviado
                sent_phones.append(order.phone)  # Guardar teléfono exitoso
                success_count += 1
                status_name = "borrador" if order.expected_status == 'draft' else "pistoleada"
                _logger.info(f"✅ WhatsApp enviado a orden {status_name} {order.order_number}")
                
            except Exception as e:
                error_count += 1
                _logger.error(f"❌ Error enviando WhatsApp para orden {order.order_number}: {e}")
                # No marcar como False si hay error, para reintentarlo después
        
        # 5️ Log de resumen
        remaining_today = self.search_count([
            ('pending_whatsapp', '=', True),
            ('delivery_date', '=', today),
            ('expected_status', 'in', ['draft', 'pending'])  # Solo contar borrador/pistoleadas
        ])
        
        _logger.info(f"📊 Resumen WhatsApp: {success_count} enviados, {error_count} errores, {remaining_today} pendientes hoy")
        
        # 6️ Marcar órdenes duplicadas del mismo día como enviadas
        if sent_phones:  # ✅ Solo si hubo envíos exitosos
            duplicate_orders = self.search([
                ('pending_whatsapp', '=', True),
                ('delivery_date', '=', today),
                ('expected_status', 'in', ['draft', 'pending']),     # Solo duplicadas borrador/pistoleadas
                ('phone', 'in', sent_phones)                         # CORRECTO: usar teléfonos exitosos
            ])
            
            if duplicate_orders:
                duplicate_orders.write({'pending_whatsapp': False})
                _logger.info(f"🔄 Marcadas {len(duplicate_orders)} órdenes duplicadas como enviadas")

    def action_create_yango_order(self):
        pass

    def action_print_return_pdf(self):
        self.ensure_one()
        return self.env.ref('trainyl_base.trainyl_return_report_action').report_action(self)

    def action_open_revert_status_wizard(self):
        """Abre el wizard para revertir el estado de la orden."""
        self.ensure_one()
        return {
            'name': 'Revertir Estado de la Orden',
            'type': 'ir.actions.act_window',
            'res_model': 'wizard.revert.order.status',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id},
        }

    def action_open_change_route_wizard(self):
        """Abre el wizard para cambiar la ruta de la orden."""
        self.ensure_one()
        return {
            'name': 'Cambiar Ruta de la Orden',
            'type': 'ir.actions.act_window',
            'res_model': 'wizard.change.order.route',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id},
        }

    def action_block_orders(self):
        """
        Bloquea las órdenes que están en estado 'in_transport' y las cambia a 'blocked'.
        Se ejecuta desde la acción de menú en la vista lista.
        """
        blocked_count = 0
        for order in self:
            if order.new_status_orders == 'in_transport':
                order.new_status_orders = 'blocked'
                order._log_change(f"Orden {order.order_number} bloqueada desde el menú de acciones.")
                blocked_count += 1
                _logger.info(f"Orden {order.order_number} cambiada a estado BLOQUEADO.")
        
        # Retorna notificación al usuario
        if blocked_count > 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Órdenes Bloqueadas',
                    'message': f'{blocked_count} orden(es) bloqueada(s) exitosamente.',
                    'sticky': False,
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Sin cambios',
                    'message': 'No hay órdenes en estado "EN TRANSPORTE" para bloquear.',
                    'sticky': False,
                    'type': 'warning',
                }
            }

    def action_send_to_yango(self):
        """
        Crea órdenes en 'trainyl.order.yango' a partir de las órdenes seleccionadas en 'trainyl.order'.
        """
        yango_order_model = self.env['trainyl.order.yango']
        created_orders = self.env['trainyl.order.yango']

        success_count = 0

        for order in self:
            # Verificar si ya existe una orden en Yango para este pedido
            existing_yango_order = yango_order_model.search([('trainyl_order_id', '=', order.id)], limit=1)
            if existing_yango_order:
                order._log_change(f"Intento de envío: Ya existe orden Yango {existing_yango_order.id}. Saltando.")
                continue

            # Preparar los datos para la nueva orden de Yango (Incluye las correcciones de errores anteriores)
            try:
                yango_order_vals = {
                    'trainyl_order_id': order.id,
                    'yango_cud_number': order.cud_number,
                    'yango_order_number': order.order_number,
                    'yango_fullname': order.fullname,
                    'yango_phone': order.phone,
                    'yango_email': order.email,
                    'yango_address': order.address,
                    'yango_district': order.district,
                    'yango_city': order.city,
                    'yango_country': order.country,
                    'yango_delivery_date': order.delivery_date,
                    'yango_seller_code': order.trainyl_seller_code,
                    'yango_seller': order.seller,
                    'yango_marketplace_code': order.trainyl_marketplace_code,
                    # Corrección: Pasar el ID del Many2one
                    'yango_partner_id': order.partner_id.id if order.partner_id else False,
                    
                    'yango_order_line_ids': [(0, 0, {
                        'product_name': line.product_des,
                        # Corrección: Asegurar que la cantidad sea un entero
                        'product_quantity': int(float(line.quantity or 0)), 
                        'product_price': line.product_price,
                    }) for line in order.order_line_ids],
                }

                # Crear la orden en Yango
                new_yango_order = yango_order_model.create(yango_order_vals)
                created_orders |= new_yango_order
                success_count += 1
                
                _logger.info(f"Orden {order.order_number} enviada a Yango. Nuevo ID: {new_yango_order.id}")

                # Actualizar estado y booleano en la orden original (¡REQUERIDO POR EL USUARIO!)
                order.write({
                    'expected_status': 'sent_do_yango',
                    'send_to_yango': True,
                })
                order._log_change(f"Orden enviada a Yango exitosamente. Estado actualizado a 'ENVIADO POR YANGO'.")
                
            except Exception as e:
                _logger.error(f"Error al crear la orden Yango para {order.order_number}: {e}")
                order.message_post(body=f"❌ Error al intentar enviar a Yango: {str(e)}", subtype_xmlid="mail.mt_note")
                # El estado y el booleano no se actualizan si falla la creación.


        # Retorno de acción para la interfaz de usuario
        if success_count > 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Envío a Yango',
                    'message': f'{success_count} orden(es) enviada(s) a Yango con éxito.',
                    'sticky': False,
                }
            }
        
        # Si no se creó ninguna orden, simplemente cierra la acción sin notificar si el error ya se registró en el chatter
        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def register_multipack_scan(self, barcode, package_count=2):
        """
        Marca la orden como multibulto cuando en frontend se confirma
        un escaneo repetido del mismo order_number.
        """
        barcode = (barcode or '').strip()
        if not barcode:
            return {'success': False, 'message': 'Código vacío.'}

        order = self.search([('order_number', '=', barcode)], limit=1)
        if not order:
            return {
                'success': False,
                'message': f'No existe la orden: {barcode}',
            }

        safe_count = max(int(package_count or 2), 2)
        order.write({
            'is_multipack': True,
            'multipack_count': safe_count,
        })

        order._log_change(
            f"Escaneo multibulto confirmado por {self.env.user.name} "
            f"({safe_count} bultos)."
        )

        return {
            'success': True,
            'message': f'Orden {barcode} marcada como multibulto.',
            'is_multipack': True,
            'multipack_count': safe_count,
        }
    
    @api.model
    def process_barcode_scan(self, barcode):
        """
        Busca la orden escaneada, la pasa a in_trainyl y retorna
        datos enriquecidos para el historial del frontend.
        """
        barcode = barcode.strip() if barcode else ''

        if not barcode:
            return {'success': False, 'message': 'Código vacío.'}

        order = self.search([('order_number', '=', barcode)], limit=1)

        if not order:
            return {
                'success': False,
                'message': f'No existe la orden: {barcode}',
                'order_info': None,
                'allow_multipack': False,
                'force_multipack_prompt': False,
            }

        # Datos para mostrar en el historial del frontend
        size_labels = {'small': 'Pequeño', 'medium': 'Mediano', 'large': 'Grande'}
        order_info = {
            'fullname':   order.fullname   or '—',
            'district':   order.district   or order.city or '—',
            'order_size': size_labels.get(order.order_size, '—'),
        }

        if order.new_status_orders == 'in_trainyl':
            return {
                'success': False,
                'message': f'La orden {barcode} YA estaba en Trainyl.',
                'order_info': order_info,
                'allow_multipack': True,
                'force_multipack_prompt': bool(order.is_multipack),
                'multipack_count': order.multipack_count or 0,
            }

        if order.new_status_orders not in ['draft', 'reprogrammed']:
            estado = dict(self._fields['new_status_orders'].selection).get(
                order.new_status_orders, order.new_status_orders
            )
            return {
                'success': False,
                'message': f'La orden {barcode} está en estado: {estado}.',
                'order_info': order_info,
                'allow_multipack': True,
                'force_multipack_prompt': bool(order.is_multipack),
                'multipack_count': order.multipack_count or 0,
            }

        # Actualizar estado
        write_vals = {'new_status_orders': 'in_trainyl'}
        if not order.multipack_count:
            write_vals['multipack_count'] = 1
        order.write(write_vals)

        # Log en chatter con usuario y timestamp
        order._log_change(
            f"Pistoleado por {self.env.user.name} → estado 'in_trainyl'."
        )

        return {
            'success':    True,
            'message':    f'¡{barcode} procesada! — {order_info["fullname"]}',
            'order_info': order_info,
            'allow_multipack': True,
            'force_multipack_prompt': bool(order.is_multipack),
            'multipack_count': order.multipack_count or 1,
        }

    @api.model
    def _find_order_by_scan_code(self, code):
        code = (code or '').strip()
        if not code:
            return self.browse()

        order = self.search([('order_number', '=', code)], limit=1)
        if order:
            return order

        order = self.search([('unique_code', '=', code)], limit=1)
        if order:
            return order

        order = self.search([('cud_number', '=', code)], limit=1)
        return order

    @api.model
    def _get_multipack_expected_packages(self, order):
        """Retorna el total de bultos esperados para la orden en planning scan."""
        if order.is_multipack and (order.multipack_count or 0) > 1:
            return int(order.multipack_count)
        return 1

    @api.model
    def planning_scan_preview(self, barcode):
        """
        Previsualiza el escaneo para planificación y valida que la orden
        pertenezca a una ruta del día de hoy.
        """
        order = self._find_order_by_scan_code(barcode)
        if not order:
            return {
                'success': False,
                'message': f'No existe la orden: {barcode}',
            }

        if not order.route_id:
            return {
                'success': False,
                'message': f'La orden {order.order_number} no tiene ruta asignada.',
            }

        today = fields.Date.context_today(self)
        route = order.route_id
        route_date = route.planificacion_id.fecha_planificacion or route.ruta_date

        if route_date != today:
            route_date_text = route_date.strftime('%d/%m/%Y') if route_date else 'Sin fecha'
            today_text = today.strftime('%d/%m/%Y') if today else 'hoy'
            return {
                'success': False,
                'message': (
                    f'La orden {order.order_number} pertenece a {route.name}, '
                    f'pero su planificación es del {route_date_text} (hoy: {today_text}).'
                ),
            }

        card_model = self.env['trainyl.route.cart']
        line_model = self.env['trainyl.route.cart.line']
        card = card_model.search([
            ('date', '=', today),
            ('route_id', '=', route.id),
        ], limit=1)

        existing_line = line_model.search([
            ('order_id', '=', order.id),
        ], order='id desc', limit=1)

        expected_packages = self._get_multipack_expected_packages(order)
        scanned_packages = int((existing_line.scanned_packages or 1) if existing_line else 0)
        remaining_packages = max(expected_packages - scanned_packages, 0)

        already_in_target = bool(
            card and existing_line and existing_line.route_card_id.id == card.id and scanned_packages >= expected_packages
        )
        partial_in_target = bool(
            card and existing_line and existing_line.route_card_id.id == card.id and scanned_packages < expected_packages
        )
        requires_move = bool(existing_line and (not card or existing_line.route_card_id.id != card.id))

        message = f'Esta orden pertenece a la {route.name}'
        if partial_in_target and expected_packages > 1:
            message = (
                f'Orden multibulto en progreso: {scanned_packages}/{expected_packages} '
                f'bultos en {route.name}. Faltan {remaining_packages}.'
            )
        elif already_in_target and expected_packages > 1:
            message = (
                f'Orden multibulto COMPLETA en {route.name}: '
                f'{scanned_packages}/{expected_packages} bultos.'
            )

        return {
            'success': True,
            'message': message,
            'order_id': order.id,
            'order_number': order.order_number,
            'route_id': route.id,
            'route_name': route.name,
            'already_in_target': already_in_target,
            'partial_in_target': partial_in_target,
            'requires_move': requires_move,
            'is_multipack': bool(order.is_multipack),
            'expected_packages': expected_packages,
            'scanned_packages': scanned_packages,
            'remaining_packages': remaining_packages,
            'from_card_sequence': existing_line.route_card_id.sequence if existing_line else False,
            'from_route_name': existing_line.route_card_id.route_id.name if existing_line and existing_line.route_card_id.route_id else False,
        }

    @api.model
    def planning_scan_accept(self, order_id, force_move=False):
        """
        Crea (si no existe) trainyl.route.cart para hoy y ruta,
        y agrega la orden escaneada en sus líneas con estado in_cart.
        """
        order = self.browse(order_id).exists()
        if not order:
            return {'success': False, 'message': 'Orden no encontrada.'}

        if not order.route_id:
            return {
                'success': False,
                'message': f'La orden {order.order_number} no tiene ruta asignada.',
            }

        today = fields.Date.context_today(self)
        route = order.route_id
        route_date = route.planificacion_id.fecha_planificacion or route.ruta_date

        if route_date != today:
            route_date_text = route_date.strftime('%d/%m/%Y') if route_date else 'Sin fecha'
            today_text = today.strftime('%d/%m/%Y') if today else 'hoy'
            return {
                'success': False,
                'message': (
                    f'La orden {order.order_number} pertenece a {route.name}, '
                    f'pero su planificación es del {route_date_text} (hoy: {today_text}).'
                ),
            }

        card_model = self.env['trainyl.route.cart']
        line_model = self.env['trainyl.route.cart.line']

        card = card_model.search([
            ('date', '=', today),
            ('route_id', '=', route.id),
        ], limit=1)

        if not card:
            card = card_model.create({
                'date': today,
                'route_id': route.id,
            })

        existing_line = line_model.search([
            ('order_id', '=', order.id),
        ], order='id desc', limit=1)

        expected_packages = self._get_multipack_expected_packages(order)

        if existing_line and existing_line.route_card_id.id == card.id:
            current_scanned = int(existing_line.scanned_packages or 1)

            if current_scanned < expected_packages:
                new_scanned = current_scanned + 1
                remaining = max(expected_packages - new_scanned, 0)
                existing_line.write({
                    'date_time': fields.Datetime.now(),
                    'planner_id': self.env.user.id,
                    'state': 'in_cart',
                    'scanned_packages': new_scanned,
                })
                return {
                    'success': True,
                    'message': (
                        f'Bulto {new_scanned}/{expected_packages} registrado para '
                        f'{order.order_number} en {route.name}.'
                    ),
                    'route_name': route.name,
                    'card_sequence': card.sequence,
                    'is_multipack': bool(order.is_multipack),
                    'expected_packages': expected_packages,
                    'scanned_packages': new_scanned,
                    'remaining_packages': remaining,
                    'multipack_in_progress': remaining > 0,
                }

            return {
                'success': False,
                'message': f'La orden {order.order_number} ya está en el carrito de {route.name}.',
                'code': 'already_in_target',
                'route_name': route.name,
                'card_sequence': card.sequence,
                'is_multipack': bool(order.is_multipack),
                'expected_packages': expected_packages,
                'scanned_packages': current_scanned,
                'remaining_packages': max(expected_packages - current_scanned, 0),
            }

        if existing_line and existing_line.route_card_id.id != card.id and not force_move:
            from_card = existing_line.route_card_id
            from_route_name = from_card.route_id.name if from_card.route_id else 'Sin ruta'
            return {
                'success': False,
                'code': 'needs_move',
                'message': (
                    f'La orden {order.order_number} ya está en el carrito {from_card.sequence} '
                    f'({from_route_name}). ¿Deseas moverla a {card.sequence} ({route.name})?'
                ),
                'from_card_sequence': from_card.sequence,
                'from_route_name': from_route_name,
                'to_card_sequence': card.sequence,
                'to_route_name': route.name,
            }

        if existing_line and existing_line.route_card_id.id != card.id and force_move:
            current_scanned = int(existing_line.scanned_packages or 1)
            new_scanned = min(current_scanned + 1, expected_packages)
            remaining = max(expected_packages - new_scanned, 0)
            existing_line.write({
                'route_card_id': card.id,
                'date_time': fields.Datetime.now(),
                'planner_id': self.env.user.id,
                'state': 'in_cart',
                'scanned_packages': new_scanned,
            })
            return {
                'success': True,
                'message': (
                    f'Orden {order.order_number} movida a {route.name} '
                    f'en carrito {card.sequence}. '
                    f'Bultos: {new_scanned}/{expected_packages}.'
                ),
                'route_name': route.name,
                'card_sequence': card.sequence,
                'moved': True,
                'is_multipack': bool(order.is_multipack),
                'expected_packages': expected_packages,
                'scanned_packages': new_scanned,
                'remaining_packages': remaining,
                'multipack_in_progress': remaining > 0,
            }

        line_model.create({
            'route_card_id': card.id,
            'date_time': fields.Datetime.now(),
            'order_id': order.id,
            'planner_id': self.env.user.id,
            'state': 'in_cart',
            'scanned_packages': 1,
        })

        remaining = max(expected_packages - 1, 0)

        return {
            'success': True,
            'message': (
                f'Orden {order.order_number} agregada a {route.name} '
                f'en carrito {card.sequence}. '
                f'Bultos: 1/{expected_packages}.'
            ),
            'route_name': route.name,
            'card_sequence': card.sequence,
            'is_multipack': bool(order.is_multipack),
            'expected_packages': expected_packages,
            'scanned_packages': 1,
            'remaining_packages': remaining,
            'multipack_in_progress': remaining > 0,
        }
    
    # Cambia @api.model por @api.returns o simplemente nada si usas self
    def update_location_from_bot(self, lat, lon, maps_url):
        """
        Actualiza la ubicación de la orden desde el bot de WhatsApp.
        Esta función está diseñada para ser llamada por el controlador API.
        Usa sudo() para evitar restricciones de permisos.
        """
        self.ensure_one()
        
        _logger.info(f"🤖 Actualizando ubicación para orden {self.order_number} con lat: {lat}, lon: {lon}, url: {maps_url[:50] if maps_url else 'None'}...")

        vals_to_write = {
            'latitude': str(lat),
            'longitude': str(lon),
            'google_maps_url': maps_url,
            'location_received': True,
            'google_maps_generated': bool(maps_url)
        }

        _logger.info(f"📝 Valores a escribir: {vals_to_write}")

        try:
            # Usar sudo() para evitar restricciones de permisos
            self.sudo().write(vals_to_write)
            _logger.info(f"✅ Ubicación guardada exitosamente para {self.order_number}.")
            return True
        except Exception as e:
            _logger.error(f"❌ Error al escribir la ubicación en la orden {self.order_number}: {str(e)}", exc_info=True)
            raise