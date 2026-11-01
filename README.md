# Signature Auto Repair

Aplicación web para un taller de vehículos de alta gama. Tiene un sitio público con un asistente de recepción con inteligencia artificial (OpenAI, con tool calling) y un panel privado para gestionar consultas, clientes, vehículos, turnos y seguimiento comercial.

- Producción: http://149.50.152.28 (y https://dwday-124673558.online cuando el DNS esté activo)
- Panel: `/admin`

## Arquitectura

```
frontend/  React 19 + TypeScript + Vite + Tailwind CSS 4 (SPA; el panel y el asistente se cargan aparte)
backend/   FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2 + SQLite (se puede migrar a PostgreSQL)
  app/ai/        orquestador, herramientas, proveedor OpenAI (Responses API) y modo de prueba
  app/services/  disponibilidad, registro, radar de oportunidades, textos con IA
  app/routers/   API pública, asistente, autenticación y administración
deploy/    Nginx, systemd y respaldo
```

Producción: Nginx sirve el frontend compilado y redirige `/api/` a Uvicorn en `127.0.0.1:8000`. Uvicorn lo gestiona systemd y corre con el usuario sin privilegios `signature`.

### Asistente y herramientas

El modelo interpreta el mensaje y pide herramientas; el backend valida cada argumento y ejecuta la acción.

| Herramienta | Qué hace |
|---|---|
| `get_available_services` | Lista los servicios activos y su precio, solo si el taller lo configuró |
| `update_intake` | Guarda los datos recopilados con validación (correo, teléfono, año, VIN, patente) |
| `request_confirmation` | Muestra al cliente un resumen con un botón **Confirmar** |
| `find_customer` / `create_customer` / `create_vehicle` / `create_service_request` | Operan solo con los datos que el cliente confirmó y evitan duplicados |
| `check_availability` | Calcula los horarios libres a partir de la agenda configurada y los turnos existentes |
| `create_appointment` | Crea un turno *solicitado* después de verificar la disponibilidad real |
| `get_customer_requests` | Devuelve el estado de una solicitud; exige el código y el correo asociado |

Garantías:

- El modelo no accede a la base de datos ni a SQL, y no tiene funciones administrativas.
- Hay límites de acciones por conversación y un presupuesto diario de tokens.
- Cada acción queda registrada en la auditoría.
- Con `AI_MODE=mock`, el modo de prueba recorre el mismo circuito sin consumir la API, y la interfaz lo indica.

## Seguridad

- Contraseñas con Argon2id. Bloqueo de cuenta tras 5 intentos fallidos y rate limiting en el login.
- Sesión en una cookie `HttpOnly` y `SameSite=Strict`, más token CSRF y verificación de `Origin`.
- La autorización se verifica en el backend en todas las rutas `/api/admin`.
- La primera cuenta administrativa solo se crea con `ADMIN_SETUP_TOKEN`, un token que existe solo en el servidor.
- Validación estricta con Pydantic y consultas mediante el ORM, con escapado de comodines.
- Límites al tamaño de las solicitudes y al tipo de contenido.
- Cabeceras de seguridad y CSP en Nginx y en la API.
- Los errores no exponen trazas internas.
- Los secretos se guardan en `backend/.env` (permisos 600) y están excluidos de Git.
- Cada visitante accede solo a su conversación, mediante un token aleatorio del que se guarda solo el hash.

## Desarrollo local

```bash
# Backend
cd backend
python -m venv .venv && .venv/Scripts/activate      # Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                                 # completar SECRET_KEY y ADMIN_SETUP_TOKEN
alembic upgrade head && python -m app.cli seed
uvicorn app.main:app --reload
pytest                                               # 17 pruebas de integración

# Frontend (en otra terminal)
cd frontend
npm install
npm run dev                                          # http://localhost:5173 (redirige /api al backend)
```

## Despliegue (Ubuntu 24.04)

1. Crear el usuario de sistema `signature` y copiar `backend/` a `/srv/signature/backend` y `frontend/dist/` a `/srv/signature/frontend`.
2. Crear el entorno virtual, instalar `requirements.txt` y crear `.env` a partir de `.env.example`, con `ENVIRONMENT=production` y `AI_MODE=openai`. El archivo debe tener permisos 600.
3. Ejecutar `alembic upgrade head` y `python -m app.cli seed`.
4. Instalar `deploy/signature-api.service` en systemd y `deploy/nginx-signature.conf` en Nginx.
5. Configurar HTTPS con `certbot --nginx -d dominio -d www.dominio` y luego poner `COOKIE_SECURE=true`.
6. Respaldar a diario con `deploy/backup.sh` (por cron; conserva 14 días). Purgar los datos según la política de retención con `python -m app.cli purge`.
7. Abrir `/admin`, ingresar el `ADMIN_SETUP_TOKEN`, crear la cuenta y después vaciar esa variable.

## Endpoints principales

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Estado del servicio |
| GET | `/api/public/site` | Datos del negocio, horarios y servicios |
| POST | `/api/chat/conversations` | Inicia una conversación (requiere consentimiento) |
| GET | `/api/chat/conversation` | Historial de la conversación (cabecera `X-Conversation-Token`) |
| POST | `/api/chat/messages` | Envía un mensaje al asistente |
| POST | `/api/chat/confirm` | El cliente confirma el resumen |
| POST | `/api/admin/auth/setup` · `login` · `logout` · GET `me` | Autenticación |
| GET | `/api/admin/dashboard` | Métricas reales |
| GET/POST/PATCH | `/api/admin/requests[/{id}]` (+ `/notes`, `/actions`, `/summary`) | Consultas |
| GET/POST/PATCH | `/api/admin/customers`, `/api/admin/vehicles` | Clientes y vehículos |
| GET/POST/PATCH | `/api/admin/appointments`, GET `/api/admin/availability` | Agenda, sin superposiciones |
| GET/POST/PATCH | `/api/admin/services`, GET/PUT `/api/admin/settings` | Servicios y configuración |
| GET/POST/PATCH | `/api/admin/radar`, `/radar/drafts`, `/follow-ups/{id}` | Radar comercial (borrador, aprobado, enviado) |

## Créditos de imágenes

Las imágenes provienen de Wikimedia Commons (CC0 y CC BY-SA 4.0). El detalle de autores está en `/privacidad#creditos`.
