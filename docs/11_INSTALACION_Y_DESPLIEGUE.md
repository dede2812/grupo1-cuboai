# Instalación y operación reproducible

Base de esta fase: fork `dede2812/grupo1-cuboai`, rama
`feature/fluso-kingdom-mvp`, commit inicial `2ca48413`, conservando el trabajo del
[PR #3](https://github.com/CUBO-IA/grupo1-cuboai/pull/3). No partir de una carpeta
vacía ni reemplazar el proyecto con main.

## Requisitos

- Python 3.12 recomendado para coincidir con CI; Django 5.2 según `requirements.txt`.
- Git y navegador moderno.
- SQLite para desarrollo sencillo; PostgreSQL 16 para validar bloqueo y concurrencia.
- Acceso a proveedores solo para pruebas externas explícitas, con sus credenciales.

La aplicación principal es un monolito Django. No necesita Node, React ni un
servicio de modelos local para navegar, usar reglas, administrar catálogo o
comprar mediante verificación manual.

## Windows PowerShell

Desde la copia de la rama indicada:

```powershell
cd web
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Editar .env: secreto de desarrollo propio y opciones del entorno.
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

La ruta comercial nueva es `http://127.0.0.1:8000/s/wiener-kingdom/`.
`/` conserva la portada histórica; `/explorar/` abre el descubrimiento multi-tienda.
`seed_demo` normal es no destructivo. `--reset` es una operación de borrado de
datos de demostración y **no forma parte del arranque normal**.

El seed incluye `demo_staff` / `demo1234` exclusivamente para entorno local de
demostración. No usar estas credenciales en un despliegue compartido. El stock
sembrado es de demostración, no inventario auditado del negocio.

### Abrir y detener la copia local con doble clic

Después de instalar el entorno anterior, ejecutar `Iniciar-WienerKingdom.cmd`
desde la raíz del repositorio. Comprueba Django, aplica las migraciones pendientes,
inicia el servidor en `127.0.0.1:8000` y abre Wiener Kingdom en el navegador.
Si el mismo servidor ya está activo, lo reutiliza sin ejecutar otra instancia.
No reinstala dependencias, no reinicia datos de demostración y no publica el sitio.

`Detener-WienerKingdom.cmd` detiene únicamente el proceso de esta copia del
proyecto que escucha en ese puerto. Los scripts comprueban ejecutable y línea de
comandos; si el puerto pertenece a otro programa, muestran un error y no lo
modifican. Los registros quedan en `.artifacts/server.log` y
`.artifacts/server-error.log`. El PID anotado en `.runtime/server.pid` es
informativo: nunca se usa por sí solo para detener un proceso.

Para comprobar el arranque sin abrir otra ventana:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-WienerKingdom.ps1 -NoBrowser
```

El permiso de ejecución indicado se aplica exclusivamente a ese proceso de
PowerShell; no modifica la política global del equipo. Estos accesos `.cmd` son
lanzadores de desarrollo local, no instaladores `.exe` ni aplicaciones de
producción. Los enlaces dejan de responder cuando se detiene el servidor o se
apaga el equipo; ejecutar el acceso nuevamente vuelve a habilitarlos.

## Linux/macOS

```sh
cd web
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 127.0.0.1:8000
```

## Variables principales

`config/settings.py` lee `web/.env`; las variables reales del proceso tienen
precedencia. No hace falta una dependencia dotenv adicional.

| Variable | Propósito |
|---|---|
| `REINO_ENV` | `dev`, `staging` o `prod` |
| `DJANGO_SECRET_KEY` | Secreto de Django; obligatorio fuera de desarrollo |
| `DJANGO_DEBUG` | `1` local; `0` fuera de desarrollo |
| `DJANGO_ALLOWED_HOSTS` | Hosts separados por coma; obligatorio fuera de desarrollo |
| `DJANGO_CSRF_ORIGINS` | Orígenes HTTPS confiables separados por coma |
| `DATABASE_URL` | PostgreSQL; vacío usa SQLite local |
| `POSTGRES_DB/USER/PASSWORD/HOST/PORT` | Alternativa a URL PostgreSQL |
| `REINO_TIME_ZONE` | Zona de reportes, por defecto `America/El_Salvador` |
| `REINO_AI_API_KEY/BASE_URL/MODEL/TIMEOUT` | Proveedor real del asesor; sin clave opera selección por reglas |
| `REINO_AI_MAX_INPUT_CHARS/MAX_CONTEXT_CHARS/MAX_COMPLETION_TOKENS/MAX_TOOL_CALLS` | Límites de entrada, contexto y ejecución |
| `REINO_AI_SESSION_HOURLY_LIMIT/STORE_DAILY_LIMIT` | Cuotas de solicitudes |
| `REINO_RESERVATION_MINUTES` | Duración de reserva temporal, por defecto 10 minutos |
| `REINO_EMAIL_ENABLED` + `EMAIL_*` | Activación y configuración de correo; SMTP no configurado no se presenta como enviado |
| `REINO_MEDIA_MAX_BYTES` | Máximo de archivos de imagen, 3 MB por defecto |

Las credenciales de PayPal, Wompi, BTCPay y la configuración logística se documentan
en `09_PAGOS_Y_LOGISTICA.md`. La mera presencia de una variable no prueba una
integración real. El operador debe verificar una operación sandbox y conservar su
evidencia sin datos sensibles.

## Pruebas y base de datos

```powershell
cd web
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test --noinput
```

Para PostgreSQL, crear una base y un usuario de pruebas con permiso de crear la
base temporal de Django; definir `DATABASE_URL` en el entorno de ese proceso y
ejecutar **la suite completa**, incluidos `tienda` y `reino`. No asumir que SQLite
valida `SELECT FOR UPDATE`. Los casos específicos PostgreSQL pueden omitirse en
SQLite; en PostgreSQL deben ejecutarse sin exclusiones silenciosas.

CI define trabajos separados para SQLite y PostgreSQL 16. Una configuración de
workflow no constituye prueba de que una ejecución remota se haya aprobado.
Resultados de esta fase: `12_PRUEBAS_Y_RESULTADOS.md`.

## Operación

```sh
python manage.py process_outbox
python manage.py reconcile_payments --help
python manage.py reino_cleanup_ai --help
python manage.py backup_reino --help
python manage.py restore_check --help
```

Usar `--help` para seleccionar rutas, edades y alcance de cada comando antes de
automatizarlo. Programar el outbox en el entorno de despliegue; no se instala un
planificador del sistema automáticamente. `/salud/` permite comprobar el proceso
y la base según su contrato. Los backups contienen datos privados: guardarlos
fuera del directorio público, controlar acceso y ensayar restauración.

En producción usar servidor WSGI, HTTPS, PostgreSQL, archivos estáticos recolectados
y almacenamiento de medios protegido. `runserver` es para desarrollo. Ejecutar
`python manage.py collectstatic --noinput` y `python manage.py check --deploy` con
variables de producción. No activar `DEBUG` para resolver un fallo en producción.

## Aplicaciones Windows

La experiencia comprobable principal es la web. No empaquetar la base SQLite ni
un servidor Django independiente por comprador: rompería el estado central de
pedidos e inventario. Un eventual shell debe apuntar al backend autorizado y
mantener permisos en servidor. La generación y prueba real de instaladores, si
se realiza, debe figurar con rutas de artefactos en `15_ESTADO_FINAL_Y_TRAZABILIDAD.md`;
la ausencia de ese registro significa que no se entregó un `.exe` verificado.
