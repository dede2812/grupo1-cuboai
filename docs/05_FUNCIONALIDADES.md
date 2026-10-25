# Funcionalidades y recorridos

La aplicación nueva usa `reino`; los recorridos históricos de `tienda` se
conservan. Estado de pruebas y limitaciones globales:
`12_PRUEBAS_Y_RESULTADOS.md` y `15_ESTADO_FINAL_Y_TRAZABILIDAD.md`.

| Módulo | Ruta / implementación | Capacidad y límite |
|---|---|---|
| Boutique Wiener Kingdom | `/s/wiener-kingdom/` | Portada, productos publicados y navegación comercial |
| Directorio multi-tienda | `/tiendas/`, `/explorar/` | Descubrimiento con política de visibilidad; demos identificadas |
| Búsqueda | `/buscar/`, `/s/<slug>/coleccion/` | Consulta y filtros sobre catálogo; no se vende como inferencia de IA |
| Ficha de producto | `/s/<slug>/producto/<slug>/` | Medios, variantes, disponibilidad, información y adición validada |
| Comparador | `/comparar/` | 2–4 variantes, diferencias y enlace compartible; valores conocidos del catálogo |
| Smart Fit | `/s/<slug>/tallas/` | Rangos versionados, cm/pulgadas, medidas faltantes e incompatibilidades explícitas |
| LookLab | `/s/<slug>/looklab/` | Selección guiada por perfil, medidas, estilo y ocasión; resultado y adición al carrito; no virtual try-on fotográfico |
| Royal Stylist | `/s/<slug>/asesor/` | Herramientas tipadas, catálogo verificado y acciones confirmadas; reglas sin clave y proveedor real configurable |
| Royal Passport | `/cuenta/` | Mascotas, medidas, consentimiento, preferencias y memoria autorizada |
| Cuenta comprador | `/cuenta/registro/`, `/cuenta/ingresar/` | Identidad persistente entre sesiones; importación de datos invitados solo con elección explícita |
| Contraseña y salida | `/cuenta/contrasena/`, POST `/cuenta/salir/` | Cambio con contraseña actual y cierre de sesión; no se declara recuperación por email verificada |
| Bolsa y checkout | `/s/<slug>/carrito/`, `/s/<slug>/checkout/` | Precios servidor, reservas, revisión, confirmación idempotente y pedido pendiente de pago |
| Pedido | `/s/<slug>/pedido/<uuid>/...` | Estado y acceso autorizado; token invitado o identidad válida |
| Digitales | `/s/<slug>/descargar/<token>/` | Grants autorizados; no requieren envío físico |
| Servicios | Catálogo y `ServiceSlot/Booking` | Franjas con cupo; no deben generar un envío físico |
| Panel de negocio | `/negocio/<slug>/` | Resumen operativo y acceso a catálogo/pedidos/configuración |
| Catálogo e inventario | `/negocio/<slug>/catalogo/` | Crear/editar/publicar, variantes, medios, tablas de talla y ajustes de stock con motivo |
| Pedidos y reembolsos | `/negocio/<slug>/pedidos/` | Transiciones según rol, evidencia financiera y auditoría; estados separados |
| Clientes | `/negocio/<slug>/clientes/` | Datos autorizados del propio negocio; no directorio global de compradores |
| Finanzas | `/negocio/<slug>/finanzas/` | Operaciones del negocio; no contabilidad fiscal completa |
| Logística | `/negocio/<slug>/logistica/` | Entrega y seguimiento manual; proveedores externos según alcance configurado |
| Dashboard empresarial | `/negocio/<slug>/estadisticas/` | Cohortes, cobro neto, series, productos, clientes, asistencia, CSV y datos insuficientes explícitos |
| Diseño y medios | `/negocio/<slug>/diseno/` | Borrador, previsualización, publicación y versiones de tema |
| Configuración | `/negocio/<slug>/configuracion/` | Identidad, zonas, políticas y equipo con capacidades por rol |
| Plataforma | `/plataforma/` | Operador con permiso independiente; alta y activación de negocios |
| Componentes | `/plataforma/componentes/` | Catálogo de componentes UI; no pretende ser una operación de compra |
| Salud y procesos | `/salud/`, comandos management | Verificación operativa, outbox, conciliación, limpieza IA, respaldo/restauración |
| Legacy | `/`, `/productos/`, `/smart-fit/`, `/quote/...`, `/panel/...` | Portada y comercio históricos conservados; datos/reportes no se mezclan automáticamente con tenants nuevos |

## Alcances que no deben confundirse

- Un pedido creado no es un pago confirmado; un pago confirmado no es una entrega.
- Selección guiada por reglas es funcional sin clave, pero no prueba conexión a IA real.
- LookLab compone recomendaciones de catálogo; no representa cómo se verá una prenda
  en una fotografía de la mascota.
- Una zona y tarifa manual son configuraciones del negocio; no datos del transportista.
- El descuento Bitcoin tiene elegibilidad de producto y validación servidor; no existe
  una suite general de campañas, cupones, experimentos y ROI publicitario.
- El dashboard muestra métricas de cohortes; impuestos, asignación de reembolso por
  línea, margen y efecto causal de promociones quedan sin calcular cuando faltan datos.
- El sistema web no equivale a tres aplicaciones Windows empaquetadas y probadas.

Las pruebas HTTP, de permisos y de servicios verifican recorridos concretos. La
inspección visual y los ensayos externos se documentan separadamente, sin inferir
que todas las rutas fueron verificadas por tener tests unitarios aprobados.
