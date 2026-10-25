# Manual de uso

Ejemplos locales con la tienda `wiener-kingdom`; otros negocios usan su propio
slug. Las tiendas demo y su inventario están identificados como demostración.

## Comprar sin asistente

1. Abrir `/s/wiener-kingdom/` y entrar a la colección. Filtrar o buscar por las
   opciones disponibles; no es obligatorio conversar con el asesor.
2. Abrir una pieza, revisar materiales, precio, opciones y disponibilidad. Para
   prendas compatibles, consultar Smart Fit e introducir medidas y unidad.
3. Seleccionar variante y cantidad, añadir a la bolsa y revisar el resumen.
   Una talla sin medidas suficientes debe confirmarse, no asumirse compatible.
4. Iniciar checkout, completar contacto y elegir modalidad/zona disponible.
   La cotización y la revisión deben corresponder al carrito actual.
5. Confirmar la creación del pedido. Guardar su enlace privado. El pedido queda
   pendiente de pago hasta que se verifique el cobro por el mecanismo habilitado.
6. Consultar el pedido para pago, preparación y entrega. Un envío manual solo
   muestra seguimiento cuando el negocio registra información real.

Si cambia precio, stock, carrito o cotización, volver a revisar. Un fallo de pago
no debe resolverse creando pedidos repetidos; revisar primero el pedido existente.
Los archivos digitales usan su enlace autorizado y los servicios reservan la
franja seleccionada; no necesitan un envío físico.

## Royal Stylist, LookLab y Smart Fit

En `/s/wiener-kingdom/asesor/`, explicar ocasión, estilo, presupuesto y restricciones.
El modo visible indica si se usa proveedor de IA o selección por reglas.
Las recomendaciones remiten a productos del negocio. Verificar variante y talla;
confirmar expresamente cualquier propuesta de añadir al carrito.

El asesor no cobra, no modifica precios y no garantiza entrega sin evidencia.
Si no hay coincidencias, modificar criterios o explorar el catálogo; no esperar
que invente existencias. Ante fallo de proveedor, el flujo tradicional sigue
disponible y el modo alternativo debe estar identificado.

LookLab permite elegir perfil, medidas, personalidad y ocasión para recibir una
selección de catálogo y continuar a la bolsa. No es una simulación exacta sobre
una fotografía. Smart Fit utiliza rangos aprobados por producto; una medida
incompleta o fuera de rango genera incertidumbre o incompatibilidad explícita.

## Cuenta, mascotas y consentimiento

En `/cuenta/registro/` crear una cuenta; en `/cuenta/ingresar/` iniciar sesión.
La cuenta mantiene una identidad de comprador entre navegadores autenticados.
La compra como invitado sigue disponible.

Si se ofrecen datos de la visita invitada, elegir explícitamente conservarlos.
Esta elección importa la información elegible de esa sesión, no la de otra cuenta.
Una combinación de carritos incompatible se informa y no debe truncar cantidades
silenciosamente. Al salir o cambiar de cuenta, los datos de la anterior permanecen
privados. El cierre de sesión se realiza mediante el botón, que envía un POST.

En `/cuenta/` crear/activar perfiles, registrar medidas y revisar finalidades de
consentimiento. Guardar medidas no equivale a autorizar cualquier uso de IA.
Se pueden revocar finalidades o eliminar memoria según los controles disponibles.
El modo «sin guardar» evita reutilizar historial persistente en ese modo.

En `/cuenta/contrasena/` cambiar contraseña introduciendo la actual. La recuperación
por correo no se considera operativa sin un flujo y envío externos verificados.
No compartir enlaces privados de pedidos ni contraseñas demo en uso real.

## Operar un negocio

Entrar al panel autorizado `/negocio/<slug>/`. Tener una cuenta de comprador no
concede membresía comercial. El propietario administra capacidades del equipo.

- **Catálogo:** crear producto, completar información y precio, añadir variantes,
  medios y reglas de talla. Revisar antes de publicar; sin variante válida no se
  debe ofrecer un producto comprable.
- **Inventario:** usar ajuste de stock e indicar motivo. No corregir saldos
  directamente en la base ni simular disponibilidad.
- **Pedidos:** abrir pedido, revisar estado financiero y preparar solo según el
  proceso acordado. Confirmar pagos manuales con referencia/evidencia. Registrar
  reembolso por su importe real; la reposición es una decisión separada.
- **Logística:** en un pedido, abrir **Gestionar despachos y seguimiento**. Elegir
  cantidades de las líneas físicas y pulsar **Registrar despacho manual**. Usar
  otro formulario para el siguiente parcial. Después registrar estado, referencia
  de seguimiento y evidencia; se conserva quién realizó el cambio. Los estados
  del despacho y pedido son independientes. Un envío que salió no puede cancelarse
  como no despachado; una devolución requiere comprobar recepción y ajustar stock
  por separado. Un evento manual no implica confirmación externa del transportista.
- **Configuración:** administrar identidad, políticas, zonas y equipo. Mantener
  borradores fuera del directorio público hasta cumplir los requisitos.
- **Diseño:** editar un borrador, previsualizar y publicar. Los cambios visibles
  corresponden a una versión de tema, no a editar CSS manualmente.

## Leer estadísticas

El propietario abre `/negocio/<slug>/estadisticas/`, elige fechas y agrupa por día,
semana o mes. Producto/categoría seleccionan pedidos completos que contienen esas
piezas. El informe muestra moneda y comparación con un período de igual duración.

«Cobro neto» incluye envío y descuenta reembolsos; no es utilidad. Si faltan
impuestos, costos o reparto de devoluciones, se indica ausencia de datos.
Los puntos del gráfico responden a ratón, tacto y foco de teclado; la tabla
proporciona los mismos valores. CSV exporta la selección autorizada sin contactos
de clientes. Ver `08_PANEL_EMPRESARIAL.md` para todas las fórmulas.

Las observaciones se basan en métricas, sin modificar automáticamente productos,
precios o inventario. Las ventas asistidas requieren una acción confirmada del
asesor que corresponda al carrito y variante comprados.

## Administrar la plataforma

Un operador con permiso `reino.operate_platform` entra a `/plataforma/`, revisa
negocios, realiza alta y valida activación. Ser `staff` de una tienda no concede
administración global. Configurar proveedores exige credenciales del entorno;
una clave guardada no demuestra conexión. No activar cobros reales hasta realizar
un ensayo sandbox verificable y confirmar la configuración del negocio.

## Problemas frecuentes

| Situación | Acción |
|---|---|
| Producto agotado o talla incompatible | Elegir alternativa o corregir medidas; no forzar el precio/stock del navegador |
| Checkout vencido o carrito modificado | Volver a la bolsa y generar revisión vigente |
| Asesor en reglas | Revisar estado visible; un operador puede configurar el proveedor, sin bloquear compra tradicional |
| Pago pendiente tras abrir enlace/QR | Consultar pedido y verificación; abrir el enlace no confirma dinero |
| Acceso denegado al panel | Revisar membresía, rol y tienda; no utilizar credenciales ajenas |
| Informe vacío | Ajustar período/filtros; cero operaciones no es un error ni debe rellenarse con datos inventados |
| Error externo o red | Reintentar operación existente según estado; no duplicar cobro/envío sin comprobar referencia |

Para instalación, backups y diagnósticos técnicos consultar
`11_INSTALACION_Y_DESPLIEGUE.md`.
