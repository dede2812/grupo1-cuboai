# Pruebas y resultados de la versión final

Fecha: 25 de octubre de 2026. Base conservada: `2ca48413`, rama
`feature/fluso-kingdom-mvp` del fork `dede2812/grupo1-cuboai` y PR #3.
La revisión abarca `tienda` histórica y `reino`; no se excluyeron módulos de CI.
El commit que incorpora este documento identifica el estado entregado.

## Entorno y resultado final

Windows, Python 3.13.14, Django 5.2.18, SQLite y PostgreSQL 16.15 local.
PostgreSQL de pruebas escuchó solo en `127.0.0.1:55432`. Las bases de prueba
de Django son independientes de la base local de demostración. CI usa Python
3.12 y PostgreSQL 16; el resultado local no se presenta como ejecución remota.

| Validación | Resultado observado |
|---|---|
| Suite completa SQLite | **655 casos: 647 aprobados, 8 omitidos, 0 fallos; 215.088 s** |
| Suite completa PostgreSQL | **655 casos: 654 aprobados, 1 omitido, 0 fallos; 344.168 s** |
| `manage.py check` | Sin problemas, 0 silenciados |
| `makemigrations --check --dry-run` | Sin cambios pendientes |
| `check --deploy` con configuración prod de prueba | Sin problemas, 0 silenciados |
| `collectstatic --noinput` | Finalizado; 42 archivos en el destino local |
| Navegador, sesión de vendedor | **135 comprobaciones**, 0 respuestas >=400, 0 imágenes rotas, 0 desbordes horizontales, 0 errores JS |
| Navegador, sesión anónima de cuenta | **9 comprobaciones**, mismos criterios sin incidencias |
| Lanzador Windows | Arranque, parada, reutilización de instancia y `/salud/` comprobados |
| `git diff --check` | Sin errores de whitespace |

`Ran 655` incluye los casos omitidos. No son 655 aprobados en cada motor.
Las ocho omisiones SQLite corresponden a concurrencia real: dos cuotas IA,
un reembolso simultáneo y cinco casos PostgreSQL de inventario/carrito/pedido.
Se ejecutaron en PostgreSQL. Allí solo se omite
`DatabaseConcurrencyConfigTests.test_sqlite_writes_wait_instead_of_failing`,
que verifica exclusivamente `timeout/IMMEDIATE` de SQLite.

Los mensajes de proveedor 401 y fallos controlados de outbox en los logs son
escenarios negativos esperados, con aserciones aprobadas; no operaciones externas.
Los logs completos están en `.artifacts/sqlite-final.txt` y
`.artifacts/postgres-final.txt` de la copia de trabajo y no se publican porque
pueden contener rutas locales. El resumen verificable se conserva en
[`validation-summary.json`](validation-summary.json).

## Comandos reproducibles

Desde `web`, después de instalar dependencias y aplicar migraciones:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test --noinput -v 2
$env:DATABASE_URL='postgres://reino@127.0.0.1:55432/reino_release'
.\.venv\Scripts\python.exe manage.py test --noinput -v 2
```

El usuario PostgreSQL debe poder crear la base temporal. La URL anterior es del
servidor local de ensayo, sin exposición pública; usar credenciales propias en
otros entornos. Para volver a SQLite, quitar `DATABASE_URL` del proceso.

El chequeo de despliegue usó `REINO_ENV=prod`, un secreto exclusivo de prueba,
`DJANGO_ALLOWED_HOSTS=example.com` y `DATABASE_URL=sqlite:///deploy-check.sqlite3`.
No prueba dominio, TLS, correo ni disponibilidad productiva.

## Navegador y evidencia visual

Se ejecutó Chromium de Google Chrome instalado, controlado por Playwright,
con ventanas de **390, 768 y 1440 px**, altura 960 px. El script
[`scripts/browser_release.cjs`](../scripts/browser_release.cjs) prueba solo
loopback, descubre productos y pedidos locales, registra HTTP, ancho real,
imágenes y errores JavaScript. La segunda ejecución comprobó cuenta/ingreso/
registro sin autenticación. Los 144 casos incluyen la misma pantalla en tres
anchos y estados de sesión distintos; no son 144 rutas únicas.

```powershell
# Desde la raíz; requiere Playwright disponible en Node.
$env:WK_QA_PASSWORD='demo1234' # solo el seed local
node scripts/browser_release.cjs
Remove-Item Env:WK_QA_PASSWORD
$env:WK_QA_ROUTES='/cuenta/'
$env:WK_QA_OUTPUT='.artifacts/browser-anonymous'
node scripts/browser_release.cjs
```

Puede definirse `PLAYWRIGHT_CHROMIUM_EXECUTABLE` para un Chrome instalado.
Los informes completos están en `.artifacts/browser/report.json` y
`.artifacts/browser-anonymous/report.json`. Las capturas seleccionadas se
conservan en [`capturas/final/`](capturas/final/README.md). Se inspeccionaron
visualmente portada, catálogo, componentes, cuenta, panel, Smart Fit y estadísticas.
Esto no equivale a auditoría WCAG completa ni a métricas de campo LCP/INP/CLS.

## Recorridos y clasificación

Los registros creados manualmente llevan `PRUEBA QA LOCAL` y correo
`qa-release@example.test`. Ningún pago ni reembolso movió dinero real. El producto
de ensayo quedó en borrador; el pedido terminó reembolsado y cancelado, con la
unidad no despachada restituida. Los datos del seed no son ventas reales.

| Recorrido | Evidencia | Estado |
|---|---|---|
| Descubrir → producto → talla → carrito → revisión → pedido | Navegador local; pedido de prueba por USD63, pendiente al crearse; `test_flow.test_compra_completa_http` | Aprobado local |
| Solicitud al asesor con límite USD65 | Navegador: dos arneses publicados de USD63; modo guiado explícito. `test_ai`, `test_ai_release` validan acciones y cotizaciones | Guiado aprobado; recorrido con modelo real bloqueado por credencial |
| Smart Fit → talla disponible | Navegador: 36/24/28 cm, resultado por prenda, talla S disponible; `test_smartfit_surface`, `test_fit` y compras HTTP | Evaluación y servicios aprobados; no se afirma una segunda compra completa por UI |
| Crear producto y modificar stock | Navegador: borrador, variante, ajuste auditado de 30 a 32 unidades; `test_merchant_ops` | Aprobado local |
| Recibir y procesar pedido | Navegador: pedido visible al vendedor, pago manual con evidencia y despacho por una unidad; `test_shipping_views` | Aprobado local |
| Reembolso parcial, total y cancelación | Navegador: USD10 parcial, USD63 acumulado total y cancelación/restock; integridad y concurrencia en ambos motores | Aprobado local; pasarelas externas no verificadas |
| Administración y roles | Barrido de más de 100 rutas con usuario autorizado; tests de onboarding, miembros, CSRF y permisos | Aprobado HTTP/servicios |
| Intento de acceso entre negocios | `test_tenancy`, `test_business`, `test_customer_accounts`, `test_release_surface` | Aprobado; incluye membresía revocada |
| Dashboard refleja la operación | Navegador: USD63 cobrado − USD10 reembolsado = USD53 netos; al final reembolso total. CSV y cohortes probados | Aprobado local |
| Fallo de proveedor, timeout y reintento | `test_provider_contracts`, `test_payment_shipping_integrity`, `test_ai_release`; transporte controlado | Aprobado de contrato; no certifica una conexión real |

La suite también verifica respaldo/restauración temporal, outbox, descarga
privada, capacidad de servicios, promociones Bitcoin, compatibilidad histórica,
consentimientos y concurrencia. Sus módulos figuran en la matriz de trazabilidad.

## Defectos reproducidos y corregidos durante la validación

- Componentes y producto nuevo devolvían errores de plantilla; tarjetas mostraban
  comentarios Django como texto y algunos enlaces usaban la tienda equivocada.
- Editor y cuenta desbordaban a 390 px; el encabezado recortaba la marca.
- Smart Fit general aceptaba medidas sin mostrar resultado si no había producto
  en la URL. Ahora permite todas las guías o una prenda, sin guardar por defecto.
- Búsqueda solo por categoría y presupuestos NaN/Infinity fallaban o se ignoraban.
- Reembolsos, envíos repetidos y cancelaciones tras incidencia tenían defectos de
  saldo/idempotencia/restock. Las regresiones reproducen los casos corregidos.
- Las cantidades de reservas de servicios y límites simultáneos de descarga no
  respetaban todos los casos; ahora se validan bajo operaciones atómicas.
- La primera ejecución PostgreSQL de esta fase tuvo 21 regresiones de idioma y
  formato de `tienda`; se corrigió el alcance de locale y se volvió a ejecutar
  todo. No se eliminaron esas pruebas.
- Dos ejecuciones intermedias se interrumpieron para inspeccionar salida
  almacenada en búfer; no cuentan como aprobadas. Las ejecuciones finales de la
  tabla terminaron normalmente. Un barrido durante el reinicio recibió conexión
  rechazada; se repitió tras salud positiva y se aseguró el cierre del navegador.
- Membresía revocada podía habilitar acceso histórico y el login histórico
  eludía la cuota del nuevo login. Ambos casos quedaron cubiertos por regresión.

## Integraciones y empaquetado

No se hicieron solicitudes reales a un modelo, PayPal, Wompi, BTCPay o MyDHL.
Sus adaptadores y errores se prueban mediante transporte controlado. MyDHL
etiquetas/aduana/checkout y conciliación final de payouts BTCPay siguen parciales;
Wompi no ofrece aquí un reembolso automatizado validado.

Se entregan `Iniciar-WienerKingdom.cmd` y `Detener-WienerKingdom.cmd`, probados
en Windows. Son lanzadores del entorno local existente, **no EXE ni instaladores**.
No se empaquetó un backend independiente por comprador ni se publicó producción.

**Veredicto: MVP local aprobado con restricciones**, descritas en
[`15_ESTADO_FINAL_Y_TRAZABILIDAD.md`](15_ESTADO_FINAL_Y_TRAZABILIDAD.md).
No equivale al 100 % de integraciones externas ni autoriza producción.
