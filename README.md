# Wiener Kingdom · Reino Commerce

Boutique para dachshunds sobre una plataforma de comercio multi-tienda en Django.
Conserva el catálogo y los flujos históricos, y añade compra tradicional, perfiles
consentidos, Smart Fit, LookLab, asesor de compras y operación empresarial.

Esta fase continúa **`feature/fluso-kingdom-mvp` del fork
`dede2812/grupo1-cuboai`, desde `2ca48413`**, preservando el trabajo de Fluso del
[PR #3](https://github.com/CUBO-IA/grupo1-cuboai/pull/3). No es una reconstrucción.

El estado actual y los bloqueos se registran en
[Estado final y trazabilidad](docs/15_ESTADO_FINAL_Y_TRAZABILIDAD.md).
Los resultados históricos de rondas anteriores no sustituyen los de
[Pruebas y resultados de esta fase](docs/12_PRUEBAS_Y_RESULTADOS.md).

## Qué hace

- Tiendas aisladas, catálogo por variantes y precios/inventario validados en servidor.
- Carrito, revisión de checkout, reservas, pedidos y estados separados de pago/entrega.
- Smart Fit con reglas versionadas, LookLab con selección guiada y Royal Passport.
- Royal Stylist con proveedor configurable, herramientas controladas y confirmación
  explícita antes de añadir piezas. Sin credenciales utiliza reglas etiquetadas.
- Cuentas de comprador, perfiles y memoria con consentimiento; compra invitada preservada.
- Catálogo, stock, pedidos, equipo, configuración y temas administrables según rol.
- Dashboard con cohortes, reembolsos, series interactivas, clientes, productos,
  atribución verificable del asesor y CSV privado.
- Adaptadores de pagos, logística, outbox y herramientas operativas con límites explícitos.

**Validación externa:** no se declara IA real conectada, pagos capturados ni envíos
confirmados sin una operación verificable del proveedor. Las pruebas locales de
contrato no sustituyen esa evidencia. No se publicará producción ni se hará merge
a main como parte de este cierre.

## Inicio rápido en Windows

Python 3.12 recomendado; dependencias en `web/requirements.txt`.

```powershell
cd web
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Editar `.env` con configuración propia. `seed_demo` sin `--reset` conserva datos
existentes; el stock sembrado es de demostración. Usuario local de panel:
`demo_staff` / `demo1234` (solo demostración; no usar en producción).

- Boutique: [Wiener Kingdom local](http://127.0.0.1:8000/s/wiener-kingdom/).
- Plataforma: [Explorar](http://127.0.0.1:8000/explorar/) y [Tiendas](http://127.0.0.1:8000/tiendas/).
- Negocio: [Panel](http://127.0.0.1:8000/negocio/wiener-kingdom/) y [Estadísticas](http://127.0.0.1:8000/negocio/wiener-kingdom/estadisticas/).
- `/` mantiene la portada histórica; `/productos/`, `/smart-fit/`, `/quote/...`
  y `/panel/...` mantienen los recorridos legacy.

Instalación Linux/macOS, PostgreSQL, configuración segura, pruebas y procesos:
[Instalación y despliegue](docs/11_INSTALACION_Y_DESPLIEGUE.md).

## Validación

```powershell
cd web
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test --noinput
```

CI ejecuta la suite completa en SQLite y PostgreSQL 16. No se excluye `tienda`
del trabajo PostgreSQL. Los casos de concurrencia requieren PostgreSQL; una
omisión esperada en SQLite no debe presentarse como prueba aprobada de bloqueo.
Cifras, comandos y evidencia visual: [Resultados](docs/12_PRUEBAS_Y_RESULTADOS.md).

## Documentación de revisión

Se reutilizan documentos equivalentes del desarrollo existente para evitar
reescribir o atribuir nuevamente el trabajo previo.

| Tema solicitado | Documento vigente / equivalente |
|---|---|
| Visión y alcance | [Producto y diseño](docs/01_PRODUCTO_Y_DISENO.md) + [Estado vigente](docs/15_ESTADO_FINAL_Y_TRAZABILIDAD.md) |
| Arquitectura y modelo de datos | [Arquitectura y datos](docs/02_ARQUITECTURA_Y_DATOS.md) |
| Proceso de desarrollo | [Proceso](docs/04_PROCESO_DE_DESARROLLO.md) |
| Funcionalidades | [Módulos y rutas](docs/05_FUNCIONALIDADES.md) |
| Inteligencia artificial | [IA de esta fase](docs/06_INTELIGENCIA_ARTIFICIAL.md) + [Diseño previo](docs/03_IA_MEMORIA_Y_RECOMENDACIONES.md) |
| Diseño UX/UI | [Diseño de la versión final](docs/07_DISENO_UX_UI.md) + [Dirección visual anterior](docs/DIRECCION_VISUAL.md) |
| Panel empresarial | [Métricas y definiciones](docs/08_PANEL_EMPRESARIAL.md) |
| Pagos y logística | [Integraciones y estados](docs/09_PAGOS_Y_LOGISTICA.md) |
| Seguridad y privacidad | [Controles y límites](docs/10_SEGURIDAD_Y_PRIVACIDAD.md) |
| Instalación y despliegue | [Guía reproducible](docs/11_INSTALACION_Y_DESPLIEGUE.md) |
| Pruebas y resultados | [Evidencia de esta fase](docs/12_PRUEBAS_Y_RESULTADOS.md) |
| Decisiones técnicas | [Decisiones y referencias](docs/REFERENCIAS_Y_DECISIONES.md) |
| Manual de usuario | [Cliente, negocio y plataforma](docs/14_MANUAL_DE_USUARIO.md) |
| Estado final y trazabilidad | [Matriz y bloqueos](docs/15_ESTADO_FINAL_Y_TRAZABILIDAD.md) |
| Cambios de la versión | [Cambios de esta fase](docs/16_CAMBIOS_VERSION_FINAL.md) |

Los informes `00_AUDITORIA_INICIAL`, `07_MATRIZ_AUDITORIA_R01_R13`,
`08_MATRIZ_REVISION_2`, `09_CIERRE_FINAL` y `docs/proposal/` conservan evidencia e
historia anterior. Sus cronologías y conteos no se presentan como nuevos.
No se ha creado una presentación académica ni comercial.

## Estructura

```text
web/
  config/                    configuración, rutas y WSGI
  tienda/                    aplicación histórica preservada
  reino/
    models.py                entidades de plataforma y comercio
    services_*.py            dominio, pagos, memoria, analítica y logística
    ai/                      proveedor, intención, herramientas y orquestador
    payments/                adaptadores de cobro
    shipping/                adaptadores de entrega
    views_*.py               vistas por responsabilidad
    tests/                   pruebas de servicios, permisos y recorridos
    management/commands/     seed, outbox, conciliación, respaldo y limpieza
  templates/                 páginas Django
  static/                    estilos, JS, fuentes y medios del proyecto
```

El Salvador · 2026
