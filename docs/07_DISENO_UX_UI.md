# 07 · Diseño UX/UI de la versión final

La interfaz conserva las plantillas Django y el trabajo visual de Fluso. Los
ajustes de esta fase se concentran en coherencia de la tienda Wiener Kingdom,
legibilidad, navegación móvil y estados comerciales verificables. El catálogo
utiliza las fotografías ya disponibles en el proyecto; no se presentan imágenes
generadas como fotografías de productos reales.

## Identidad y componentes

| Recurso | Aplicación real |
|---|---|
| Navy `#101E36` | Texto y estructura de Wiener Kingdom |
| Carmine `#AF3635` | Acciones principales |
| Burgundy `#842F34` | Token complementario disponible |
| Steel Blue `#366A91` | Foco de teclado |
| Silver `#C5CBD5` | Acento de marca |
| Ivory `#FAF8F6` | Fondo de la tienda |
| Fraunces + Manrope | Titulares editoriales y lectura/controles; fuentes locales |

Los valores iniciales viven en `services_theme.default_config`. Otras tiendas
conservan su propia identidad; no reciben fotografías o textos de Wiener
Kingdom. `apply_release_theme` actualiza únicamente el tema anterior reconocible
de Wiener Kingdom y crea una versión nueva. Un tema ya personalizado se conserva.
El editor valida formato hexadecimal y contraste de texto/fondo, texto/tarjeta
y texto/acción antes de publicar. Restaurar una versión genera otra versión;
no sobrescribe el historial.

La base compartida incluye encabezado, acceso a cuenta/bolsa, enlace para saltar
al contenido, estados de demostración, mensajes y pie. Las tarjetas de producto
y tienda reutilizan parciales; sus enlaces se resuelven con la tienda de cada
producto. La ruta `/plataforma/componentes/` muestra componentes reales y
productos visibles para revisar su apariencia.

## Recorridos y estados

- Descubrimiento → colección → producto → bolsa → revisión → pedido conserva
  la compra tradicional. Los precios y la disponibilidad son valores del servidor.
- La búsqueda mantiene filtros de categoría y presupuesto en el formulario;
  precios inválidos se explican, y una búsqueda sin resultados no relaja filtros.
- Smart Fit presenta compatibilidad según medidas y reglas; una medida faltante
  no se convierte en una garantía de talla. La pantalla general permite evaluar
  todas las guías publicadas o una prenda, también sin perfil. Los resultados
  distinguen talla compatible y existencias después de reservas activas; las
  medidas temporales no se guardan y el enlace permite elegir en la ficha.
  LookLab ofrece combinaciones, sin
  prometer un probador fotográfico preciso.
- El asesor identifica el modo disponible y requiere confirmación antes de
  incorporar productos. La memoria persistente necesita consentimiento.
- Pedido y pagos distinguen pendiente, fallido, expirado, disputa y reembolso;
  un regreso de la pasarela no se presenta como confirmación de dinero recibido.
- El panel prioriza pagos pendientes e inventario bajo. Catálogo y pedidos
  tienen paginación; los filtros de estado se conservan al cambiar de página.
- Finanzas y clientes descuentan reembolsos acumulados. Si falta el importe
  histórico, muestran datos insuficientes. Monedas diferentes no se suman sin
  conversión verificada. Los informes detallan período y definición del indicador.

## Adaptabilidad y accesibilidad

`web/static/reino/css/reino.css` contiene controles con altura mínima de 44 px,
foco visible, elementos de cuadrícula que pueden encogerse y tablas con
desplazamiento contenido. En móvil, la marca ocupa una fila completa y la
navegación empresarial se desplaza dentro de su región. Los controles del
editor de diseño no deben ampliar el ancho de la página.

Se conservan etiquetas de formulario, nombres de navegación, texto alternativo
y reducción de movimiento. Los gráficos del panel empresarial ofrecen datos
tabulares y controles de período. Estos controles no constituyen por sí solos
una certificación WCAG: el alcance y los resultados comprobados del navegador
se registran en [Pruebas y resultados](12_PRUEBAS_Y_RESULTADOS.md).

Los errores reparados incluyen comentarios Django multilínea que aparecían
como texto en tarjetas, enlaces incorrectos en la biblioteca de componentes,
el formulario de producto nuevo que intentaba leer un producto inexistente y
el ancho móvil del editor. La evidencia antigua en `docs/capturas/` permanece
como historia; no debe confundirse con capturas de validación de esta fase.

## Documentos equivalentes conservados

Se mantiene la nomenclatura existente cuando cubre el contenido solicitado:

| Documento solicitado | Equivalente vigente |
|---|---|
| `01_VISION_Y_ALCANCE.md` | [Producto y diseño](01_PRODUCTO_Y_DISENO.md), con alcance actual en [trazabilidad](15_ESTADO_FINAL_Y_TRAZABILIDAD.md) |
| `02_ARQUITECTURA.md` | [Arquitectura y datos](02_ARQUITECTURA_Y_DATOS.md) |
| `03_MODELO_DE_DATOS.md` | Secciones de modelo, aislamiento, índices y migraciones en [Arquitectura y datos](02_ARQUITECTURA_Y_DATOS.md) |
| `13_DECISIONES_TECNICAS.md` | [Referencias y decisiones](REFERENCIAS_Y_DECISIONES.md), sección de la fase final |

La [dirección visual anterior](DIRECCION_VISUAL.md) documenta decisiones del
desarrollo previo. Este documento identifica lo que cambió durante el cierre.
