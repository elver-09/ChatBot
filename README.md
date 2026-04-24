# 🤖 ChatBot WhatsApp - Integración Odoo + Baileys

<p align="center">
  <img width="300" src="https://i.imgur.com/Oauef6t.png">
</p>

## 📋 Descripción

Bot de WhatsApp automatizado que **sincroniza órdenes desde Odoo** y envía notificaciones proactivas a clientes vía WhatsApp. Perfecto para negocios que necesitan:

✅ **Notificaciones automáticas de órdenes** desde Odoo  
✅ **Recordatorios programados** (cron cada 2 minutos)  
✅ **Integración nativa con Odoo** vía API REST  
✅ **Gestión de estados** (enviado, notificado, recordatorios)  
✅ **Soporte multi-país** (normalización automática de números)  
✅ **Gestión de sesiones** con Baileys  
✅ **Logs detallados** para debugging  

---

## 🚀 Características Principales

### 1. **Sincronización con Odoo**
- Se conecta a tu instancia de Odoo vía API REST
- Obtiene automáticamente órdenes pendientes de notificación
- Actualiza estados en tiempo real (enviado → notificado → recordatorio)

### 2. **Envío Automático de Mensajes**
- Ejecuta un cron cada 2 minutos para revisar órdenes
- Normaliza números telefónicos internacionales
- Envía 1 primer mensaje y hasta 3 recordatorios
- Espera 3 segundos entre envíos (anti-ban)

### 3. **Manejo Inteligente de Estados**
```
Odoo: orden sin notificar
  ↓
Bot: Envía 1er mensaje → Marca "notified"
  ↓
Bot: Envía recordatorios → Incrementa contador
```

### 4. **Conexión WhatsApp**
- Usa **Baileys** (cliente oficial WhatsApp en la nube)
- Almacena sesiones en carpeta `bot_sessions/`
- Se reconecta automáticamente si falla

---

## 📦 Requisitos

- **Node.js** 16.0.0 o superior
- **npm** o **yarn**
- **Instancia Odoo** con API REST configurada
- **Número de WhatsApp** para el bot (no puede ser cuenta personal activa)

---

## 🔧 Instalación

### 1. Clonar y instalar dependencias
```bash
git clone https://github.com/elver-09/ChatBot.git
cd ChatBot
npm install
```

### 2. Configurar variables de Odoo
Edita `odooService.js`:
```javascript
const ODOO_URL = 'https://tu-instancia-odoo.com';  // Tu URL de Odoo
const API_TOKEN = 'tu-token-api';                   // Token de autenticación
```

### 3. Iniciar el bot
```bash
npm start
```

**Primera ejecución:** Te pedirá scannear un código QR con WhatsApp. Después se guardará la sesión automáticamente.

---

## 📝 Estructura del Proyecto

```
ChatBot/
├── app.js                  # Punto de entrada, cron y lógica principal
├── odooService.js          # Funciones de integración con Odoo API
├── bot_sessions/           # Almacenamiento de sesiones WhatsApp
├── package.json            # Dependencias del proyecto
└── Dockerfile              # Para desplegar en contenedores
```

---

## 🔌 Integración Odoo

### Endpoints esperados en Odoo:

**1. Obtener órdenes pendientes:**
```
POST /api/bot/get_orders
Respuesta: { result: { orders: [...] } }
```

**2. Marcar como notificada:**
```
POST /api/bot/mark_sent
Params: { order_id: 123 }
Respuesta: { result: { status: 'success' } }
```

**3. Incrementar recordatorios:**
```
POST /api/bot/increment_reminder
Params: { order_id: 123 }
Respuesta: { result: { status: 'success' } }
```

### Estructura esperada de orden:
```json
{
  "id": 123,
  "order_number": "ORD-001",
  "phone": "987654321",
  "message": "Tu orden está lista",
  "status": "sent"
}
```

---

## 🎯 Casos de Uso

| Caso | Descripción |
|------|-------------|
| 📦 Notificación de entrega | Avisa al cliente cuando su orden está lista |
| 🔔 Recordatorios | Envía hasta 3 recordatorios automáticos |
| 💰 Cobranzas | Notifica estados de pagos pendientes |
| 📊 Confirmación de órdenes | Confirma recepción de pedidos en WhatsApp |

---

## 📊 Flujo de Funcionamiento

```
┌─────────────────────────────────────┐
│   Cron ejecuta cada 2 minutos       │
└────────────────┬────────────────────┘
                 │
         ┌───────▼────────┐
         │ Consulta Odoo  │
         │ get_orders()   │
         └───────┬────────┘
                 │
    ┌────────────┴────────────┐
    │ Para cada orden:        │
    ├─ Normaliza teléfono     │
    ├─ Envía mensaje          │
    ├─ Actualiza estado       │
    └────────────┬────────────┘
                 │
         ┌───────▼────────┐
         │ Espera 3 seg   │
         │ (Anti-ban)     │
         └────────────────┘
```

---

## 🐳 Docker

```bash
docker build -t chatbot-whatsapp .
docker run -v $(pwd)/bot_sessions:/app/bot_sessions chatbot-whatsapp
```

---

## 🔧 Variables Importantes

| Variable | Ubicación | Descripción |
|----------|-----------|-------------|
| `ODOO_URL` | `odooService.js` | URL de tu instancia Odoo |
| `API_TOKEN` | `odooService.js` | Token de autenticación Odoo |
| Cron interval | `app.js` línea 24 | Frecuencia de revisión (actualmente `*/2`) |

---

## 📚 Dependencias Principales

- **@bot-whatsapp/bot** - Framework para el bot
- **@whiskeysockets/baileys** - Cliente WhatsApp
- **axios** - Cliente HTTP para Odoo API
- **node-cron** - Programador de tareas
- **pino** - Logger de eventos

---

## 🐛 Troubleshooting

| Problema | Solución |
|----------|----------|
| Bot no envía mensajes | Verifica que el número tenga WhatsApp activo |
| Error de conexión a Odoo | Revisa `ODOO_URL` y `API_TOKEN` |
| Sesión no se guarda | Verifica permisos en carpeta `bot_sessions/` |
| Ban de WhatsApp | Aumenta espera entre mensajes (línea ~55 de app.js) |

---

## 📝 Logs

El bot genera logs en la consola:
- ✅ Éxito en operaciones
- ❌ Errores de conexión/API
- ⚠️ Advertencias (órdenes sin teléfono)
- 📨 Progreso de envío

---

## 📄 Licencia

Basado en [Bot WhatsApp](https://bot-whatsapp.netlify.app/) framework

---

## 📚 Recursos Adicionales

- [📄 Documentación Bot WhatsApp](https://bot-whatsapp.netlify.app/)
- [🚀 Roadmap](https://github.com/orgs/codigoencasa/projects/1)
- [💻 Discord Community](https://link.codigoencasa.com/DISCORD)
- [Baileys Docs](https://github.com/WhiskeySockets/Baileys)
