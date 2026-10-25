# Panel de inteligencia empresarial

El informe vive en `/negocio/<slug>/estadisticas/`; el CSV en la subruta
`exportar/`. Implementación: `web/reino/services_business.py`,
`views_business.py`, `urls_business.py` y `templates/reino/business_dashboard.html`.
Las cifras se calculan sobre pedidos y eventos persistidos del negocio; no se
siembran ventas de demostración para llenar los gráficos.

## Alcance, período y moneda

El período predeterminado son los últimos 30 días, incluyendo hoy, en la zona
horaria configurada de Django (`America/El_Salvador` por defecto). Las fechas son
inclusivas; internamente se usa un intervalo entre medianoches, con extremo final
exclusivo. Se admite hasta 366 días. El período anterior tiene exactamente la
misma duración y termina el día anterior al inicio seleccionado.

**Es un informe de cohortes por fecha de creación del pedido, valorado con su
estado actual. No es un libro de movimientos de caja por fecha de cobro.** Un
reembolso recibido hoy modifica la cohorte del pedido original. El informe lo
explica en pantalla y no inventa fechas de liquidación.

Los importes se limitan a la moneda configurada de la tienda. Pedidos en otra
moneda se excluyen y su existencia se advierte. No se convierten divisas sin tipo
de cambio registrado. Los pedidos legacy de `tienda.Order` no se mezclan con
`reino.Order`, porque no tienen la misma relación con un tenant.

Los filtros de producto y categoría seleccionan **pedidos completos que contienen
una línea coincidente**. Así se mantienen descuentos, envío y reembolsos a nivel
de pedido, sin inventar una distribución entre líneas. El panel explica este
alcance. El filtro de estado se refiere a `Order.status`, separado del pago.

## Diccionario de indicadores

`V` = pedidos de la cohorte cuyo `payment_status` actual es `paid`,
`partially_refunded` o `refunded`. Los estados pendiente, fallido, vencido y disputa
no se cuentan como ingreso verificado en este informe; las disputas se cuentan
por separado.

| Indicador | Fórmula / fuente | Límite de interpretación |
|---|---|---|
| Productos brutos | Suma `Order.subtotal` en V | Antes de descuentos, envío y devoluciones; no equivale a utilidad |
| Descuentos | Suma `Order.discount_amount` en V | Descuento realmente registrado, no publicidad de campaña |
| Productos tras descuentos | Bruto − descuentos | Antes de reembolsos |
| Envío cobrado | Suma `Order.shipping_amount` en V | No es costo del transportista; un NULL produce desglose insuficiente |
| Total cobrado original | Suma `Order.total` en V | Incluye envío; no sumar nuevamente los intentos de pago |
| Reembolsos | Suma acumulada `Order.refund_amount` en V | No se vuelve a sumar `PaymentAttempt.refunded_amount` |
| Cobro neto | Total cobrado original − reembolsos | Incluye envío; no representa ventas netas de mercancía ni utilidad |
| Ventas netas de productos | Productos tras descuentos, solo si no hay reembolsos | Con reembolsos, datos insuficientes: no existe asignación por línea/envío |
| Impuestos | No desglosados | El esquema actual no tiene importe fiscal separado; no se muestra cero ficticio |
| Ticket promedio original | Total original / número de pedidos en V | Denominador cero: sin datos, nunca 0% |
| Pedidos confirmados | `status` confirmado o cerrado | Independiente de verificación del pago |
| Devoluciones | Pedidos con `delivery_status=returned` | Distinto de reembolso monetario |
| Variación porcentual | `(actual − anterior) / abs(anterior) × 100` | Base anterior cero o desconocida: sin base para calcular |
| Clientes nuevos | Emails distintos en V sin compra verificada anterior al inicio | Se normaliza a minúsculas; no se infieren identidades entre emails |
| Clientes recurrentes | Emails distintos en V con compra verificada anterior al inicio | Repetir dentro de la misma cohorte no los vuelve históricos |
| Participación recurrente | Clientes recurrentes / clientes identificables de V | No es retención causal ni valor de vida |
| Piezas destacadas | Suma de cantidades y subtotales históricos de `OrderItem` en V | Sin asignar descuentos/reembolsos; título y precio del snapshot |
| Ventas por categoría | Subtotales de líneas agrupados por categoría actual | Si desaparece variante/categoría, conserva importe en «Sin categoría disponible» |
| Comprados juntos | Pares de productos distintos en al menos dos pedidos de V | Variantes del mismo producto no son pares; excluye cestas de más de 50 productos para acotar costo |
| Sin ventas | Productos publicados sin líneas en V | Puede reflejar publicación reciente o falta de stock, no desinterés |
| Inventario crítico | Variantes físicas activas publicadas con stock ≤ 2 | Estado actual, antes de reservas temporales; no se reconstruye stock histórico |
| Promociones | Descuentos agrupados por `discount_note` en V | Muestra uso; rentabilidad/incrementalidad requieren costos y grupo de comparación |

Un pedido históricamente marcado como reembolsado sin `refund_amount` produce
**datos insuficientes** para cobro neto, en vez de asumir reembolso cero. El gráfico
interrumpe ese tramo; el CSV conserva la ausencia del importe.

## Eventos y embudo

`AnalyticsEvent` contiene tienda, clave técnica de identidad (cuenta o sesión invitada), nombre, payload
minimizado y `request_id` único. `track_once` deriva una clave SHA-256 en servidor
con tienda + sesión + evento + identidad de operación; reintentar no elimina ni
suprime eventos de otra tienda. El registro tiene savepoint propio y un error de
base de datos de telemetría no convierte una compra confirmada en error HTTP.

| Evento | Momento y deduplicación |
|---|---|
| `product_view` | Una ficha por producto, identidad y día local; refrescar no suma otra vista ese día |
| `search` | Una combinación de búsqueda/filtros por identidad y día; guarda cantidad de resultados y origen, no el texto introducido |
| `cart_added` | Mutación confirmada, por carrito y versión; no intención ni clic fallido |
| `checkout_started` | Primer acceso con carrito abierto, una vez por carrito |
| `checkout_reviewed` | Revisión válida, una vez por sesión de checkout y revisión |
| `order_placed` | Pedido persistido, una vez por UUID del pedido |
| `promotion_applied` | Descuento persistido en pedido, una vez por pedido |
| `advisor_action_confirmed` | Herramienta ejecutada tras confirmar token; carrito, variante y acción verificables |
| `advisor_query`, `advisor_no_match` | Contadores de consultas cuando se instrumentan en el orquestador; no reconstruir consultas anteriores |
| `payment_verified`, `refund_recorded`, `order_cancelled` | Transiciones persistidas por servicios de comercio; el informe financiero usa pedidos como fuente de verdad |

El embudo observado se restringe a la tienda completa, sin filtros de producto,
categoría o estado: identidades con vista de producto → intersección
con adición → checkout → pedido creado → identidad de carrito con pedido verificado.
Una identidad es una cuenta autenticada o una sesión invitada; no mezcla cuentas ajenas. Se excluye la clave vacía. El denominador son identidades con vista de producto,
**no todo el tráfico del sitio ni personas únicas**. Las intersecciones requieren
eventos dentro del período; no reconstruyen orden temporal entre pasos ni eventos
históricos no instrumentados. La pérdida de telemetría reduce la cobertura.

Identidades que añadieron pero no crearon un pedido se presentan como «sin completar
en el período». No se declara abandono definitivo: pueden comprar después o
desde otra sesión.

## Ventas asistidas

La atribución exige `advisor_action_confirmed` anterior a la creación del pedido,
con el mismo UUID de carrito y una variante que figure efectivamente en sus líneas.
El payload debe declarar `action=add_to_cart`. Un pedido cuenta una vez aunque
haya varias acciones. Abrir el chat, ver una recomendación, quitar después la pieza
recomendada o confirmar después del pedido no atribuye una venta.

Se muestra el cobro neto **del pedido asistido completo**, no un importe supuesto
de línea atribuible. Es evidencia de asistencia, no de incremento causado por IA.
La eliminación posterior de una variante puede perder atribución; no se inventa.

## Interfaz, permisos y exportación

Tarjetas, desglose financiero, series día/semana/mes, categorías, tablas, embudo e
inventario se renderizan con Django. El gráfico SVG local permite cambiar métrica,
inspeccionar puntos con ratón/tacto/teclado y consultar la tabla accesible. No se
carga un SDK de analítica ni un CDN de gráficos. Semanas/meses extremos pueden ser
parciales; la comparación se alinea por posición en los períodos.

Dashboard y CSV requieren sesión autenticada, membresía activa del negocio y
capacidad `payments` (actualmente propietario). Staff de catálogo, logística y
miembros ajenos reciben 403. Producto/categoría del formulario se validan contra
el tenant. Respuestas privadas: `Cache-Control: private, no-store`.

CSV UTF-8 con BOM, mismas fechas/filtros/moneda que el panel. Se exportan referencias,
estados y desgloses financieros; no nombres, emails, direcciones ni tokens de
acceso. Se neutralizan celdas que podrían ser fórmulas al abrirlas en una hoja.

La interpretación de tendencias está implementada como reglas sobre métricas
verificables y se etiqueta así. No hay inferencia empresarial con proveedor LLM
verificada ni cambios automáticos de precios/inventario.

## Pruebas reproducibles

```powershell
cd web
.\.venv\Scripts\python.exe manage.py test reino.tests.test_business reino.tests.test_flow reino.tests.test_explore
```

Cobertura: reembolsos completos/parciales y desconocidos, monedas, tenant, filtros,
períodos, denominador cero, clientes, atribución IA, embudo, deduplicación, snapshots,
fórmulas CSV, permisos, privacidad y cantidad de consultas sin N+1 por pedido.
Los resultados de ejecución de cierre se registran en `12_PRUEBAS_Y_RESULTADOS.md`.
