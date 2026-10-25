# Pagos y logística — cierre verificable

## Estado real

El código incorpora adaptadores HTTP de **PayPal Orders v2/Payments v2**, **Wompi El Salvador** y **BTCPay Greenfield**, con cuenta y entorno separados por tienda. Las pruebas de contrato usan transporte HTTP sustituido: **no demuestran conexión ni certificación externa**. En esta entrega no se proporcionaron credenciales, no se ejecutaron cobros reales, no se publicaron webhooks y no se compraron etiquetas.

MyDHL implementa consulta de tarifa para un paquete medido y seguimiento autenticado. **La compra y descarga de etiquetas MyDHL siguen deshabilitadas**: faltan el flujo completo de paquete/origen/aduana y validación con la cuenta transportista. No se presentan como operativas.

## Integridad corregida

- Cada clave de intento está vinculada a pedido, proveedor, cuenta y entorno. Un intento activo bloquea otro cobro del mismo pedido. Importes y moneda provienen del pedido histórico.
- Intento capturado, importe capturado, pedido pagado y permisos digitales se actualizan en una misma transacción. Un fallo revierte todo el cambio local; la conciliación recupera una confirmación externa.
- La intención de creación/reembolso se guarda antes del HTTP. Un timeout deja operación pendiente/ambigua; no se repite un POST a ciegas.
- Reembolsos consultan el saldo bajo bloqueo, aceptan clave idempotente, acumulan cantidades y devuelven por defecto sólo el saldo restante. Un reembolso manual o un pull payment BTCPay queda pendiente y no incrementa dinero devuelto.
- Una confirmación de reembolso que llega mientras se espera HTTP prevalece sobre un error o estado pendiente posterior. El resultado no retrocede ni se vuelve a enviar. Declarar reembolso total exige cubrir todo el cobro.
- El webhook público rechaza el adaptador fake. No permite estados arbitrarios ni usa parámetros de retorno como comprobantes. La consulta autenticada comprueba referencia, cuenta, pedido, importe y moneda.
- Despachos normalizan líneas, rechazan líneas duplicadas/digitales/ajenas y repeticiones exactas devuelven el envío existente. Las respuestas ambiguas conservan la reserva de despacho. Un error definitivo la libera.
- Cancelar un pedido con un envío ya recogido/en tránsito/entregado no repone esas unidades automáticamente. El tipo físico/digital utiliza el snapshot histórico de la línea.
- Una incidencia posterior conserva evidencia de salida física: no permite cancelar el envío como si nunca hubiera salido ni reponer automáticamente sus unidades. Los cambios locales dejan actor y motivo en la auditoría del pedido.

## Gestión manual desde el panel

Desde el detalle del pedido, **Gestionar despachos y seguimiento** abre
`/negocio/<slug>/pedidos/<UUID>/envios/`. Propietario, equipo y logística operan según
la capacidad `fulfilment`; usuarios ajenos al negocio no pueden leer ni modificar
estos datos. El formulario permite elegir cantidades físicas pendientes por línea,
registrar un paquete y actualizar estado, referencia de seguimiento y evidencia.
La dirección y modalidad vienen del pedido histórico, no del formulario.

Cada formulario de creación lleva una autorización firmada ligada a usuario,
pedido y una clave de operación. Repetir ese POST devuelve el mismo envío; volver
a la pantalla genera una operación nueva para despachar las unidades restantes.
Dos parciales iguales, por ejemplo 1 + 1 de una línea comprada con cantidad 2,
son posibles sin duplicar un doble clic. El servicio persiste la clave en
`ShipmentEvent` dentro del bloqueo del pedido antes de llamar al adaptador.

`create_shipment(..., idempotency_key=...)` exige claves nuevas para operaciones
nuevas y conserva la comparación de líneas para llamadores históricos sin clave.
Una clave existente no admite cambiar proveedor, servicio, líneas o dirección.
Una operación ambigua sigue reservada; una fallida definitivamente puede reintentarse
con una nueva clave tras revisar el resultado.

Se ofrecen retiro y entrega local manual conforme al pedido. Los estados de cada
despacho y el estado global del pedido son dimensiones separadas. Registrar una
devolución no repone inventario: primero debe verificarse físicamente la recepción
y registrar el ajuste con motivo. Este panel no compra etiquetas MyDHL ni convierte
una referencia escrita por el equipo en tracking confirmado por el transportista.

## Configuración por tienda

Inyectar JSON como variables de entorno del proceso o como diccionarios de settings. No se leen claves desde campos del navegador ni se guardan secretos en modelos o respuestas. Una clave configurada **no** implica conexión comprobada.

`REINO_PAYMENT_ACCOUNTS`:

```json
{
  "paypal": {
    "wiener-kingdom": {
      "ENVIRONMENT": "test",
      "ACCOUNT_REF": "ID_MERCHANT_RECEPTOR",
      "CLIENT_ID": "OBTENER_EN_PAYPAL",
      "CLIENT_SECRET": "INYECTAR_COMO_SECRETO",
      "WEBHOOK_ID": "ID_WEBHOOK_REGISTRADO",
      "RETURN_URL": "https://DOMINIO/pagos/retorno/paypal/",
      "CANCEL_URL": "https://DOMINIO/tiendas/"
    }
  },
  "wompi": {
    "wiener-kingdom": {
      "ENVIRONMENT": "test",
      "ACCOUNT_REF": "ID_APLICATIVO",
      "CLIENT_ID": "MISMO_ID_APLICATIVO",
      "CLIENT_SECRET": "INYECTAR_COMO_SECRETO",
      "WEBHOOK_URL": "https://DOMINIO/pagos/webhook/wompi/",
      "RETURN_URL": "https://DOMINIO/pagos/retorno/wompi/"
    }
  },
  "btcpay": {
    "wiener-kingdom": {
      "ENVIRONMENT": "test",
      "ACCOUNT_REF": "STORE_ID_BTCPAY",
      "BASE_URL": "https://INSTANCIA_BTCPAY_DE_PRUEBA",
      "API_KEY": "INYECTAR_COMO_SECRETO",
      "WEBHOOK_SECRET": "INYECTAR_COMO_SECRETO"
    }
  }
}
```

Sustituir `wiener-kingdom` por el slug real. `ENVIRONMENT` acepta `test` o `live`; PayPal cambia de host. Wompi controla el entorno por aplicativo y el adaptador comprueba `estaProductivo`/`esReal`. BTCPay requiere una instancia y wallet de prueba apropiadas: el campo `test` no convierte una instancia mainnet en sandbox.

`REINO_SHIPPING_ACCOUNTS`:

```json
{
  "mydhl": {
    "wiener-kingdom": {
      "ENVIRONMENT": "test",
      "ACCOUNT_REF": "NUMERO_CUENTA_DHL",
      "USERNAME": "USUARIO_API",
      "PASSWORD": "INYECTAR_COMO_SECRETO"
    }
  }
}
```

MyDHL `quote(origin, destination, packages, service)` requiere `origin.store_slug`, país ISO, ciudad, código postal, fecha de despacho, y un paquete con peso kg y dimensiones cm positivos. La tarifa es estimada, no una promesa de entrega. Solicitar servicio concreto; no elegir silenciosamente un producto distinto. Se requiere integrar la cotización con el flujo de compra antes de anunciar envíos DHL automáticos.

## Flujo HTTP del comprador

En el pedido privado se muestran únicamente métodos configurados de esa tienda, claramente marcados cuando están en pruebas. Iniciar pago y consultar/capturar son POST protegidos por CSRF y sesión propietaria o token privado de pedido. Los botones usan importes del servidor.

La URL de retorno lleva estado firmado; exige la sesión que inició ese intento y, en PayPal, coincidencia con el ID de orden externo persistido. El retorno GET sólo regresa al pedido. El botón **Confirmar pago autorizado** realiza la consulta/captura PayPal por servidor. Wompi y BTCPay se confirman mediante webhook/consulta autenticada; BTCPay permite volver al pedido y usar **Comprobar pago**.

Registrar webhooks HTTPS en `/pagos/webhook/paypal/`, `/pagos/webhook/wompi/` y `/pagos/webhook/btcpay/`. PayPal usa verificación oficial de firma. BTCPay verifica HMAC SHA-256 sobre los bytes exactos y el Store ID. La documentación pública Wompi SV consultada no ofrece firma: su notificación es una señal sin autoridad financiera; el servidor consulta el enlace por OAuth y valida aplicativo, entorno, referencia e importe. Aplicar protección de tasa a este endpoint en el proxy de producción.

## Límites pendientes de proveedor y producto

- Registrar las cuentas, configurar secretos y dominio HTTPS, ejecutar pruebas reales de sandbox y conservar IDs/evidencia antes de declarar conexión comprobada.
- Wompi SV no publica en el contrato consultado un endpoint de reembolso de enlaces ordinarios. Su operación devuelve un error explícito; tramitar devolución en el panel autorizado y conciliar evidencia. No usar el endpoint Visa Direct para ese fin.
- BTCPay crea una solicitud de devolución, no una devolución completada. Falta incorporar eventos de payout/conciliación final para declarar dinero devuelto automáticamente.
- Las operaciones externas ambiguas sin referencia requieren conciliación en el panel del proveedor; el sistema bloquea recreación automática.
- MyDHL: completar creación/recuperación privada de etiquetas, paquetes/aduana, selección de tarifa en checkout y verificación externa. La consulta de tarifas/seguimiento por sí sola no cumple ese recorrido.
- Pruebas locales no sustituyen concurrencia real en PostgreSQL ni pruebas del proveedor; ejecutar ambas antes de producción.

## Fuentes oficiales consultadas

- [PayPal Orders v2](https://developer.paypal.com/api/orders/v2)
- [PayPal Payments v2, reembolsos](https://developer.paypal.com/api/payments/v2/captures-refund)
- [PayPal verificación de webhooks](https://developer.paypal.com/api/rest/webhooks/rest/)
- [Wompi SV, esquema OpenAPI](https://api.wompi.sv/swagger/v1/swagger.json)
- [Wompi SV, enlaces de pago](https://docs.wompi.sv/metodos-api/enlace-de-pago)
- [Wompi SV, webhook](https://docs.wompi.sv/webhook/definicion-webhook.md)
- [BTCPay Greenfield](https://docs.btcpayserver.org/API/Greenfield/v1/)
- [MyDHL oficial](https://developer.dhl.com/api-reference/dhl-express-mydhl-api)

## Pruebas reproducibles

Desde `web`:

```text
python manage.py test reino.tests.test_payments reino.tests.test_shipping reino.tests.test_shipping_views reino.tests.test_payment_shipping_integrity reino.tests.test_provider_contracts reino.tests.test_commerce --noinput
```

Los tests de proveedor comprueban solicitudes, referencia idempotente, importe de servidor, aislamiento de tienda, rechazo de otra cuenta/entorno, firmas, retorno falso, permisos y CSRF con HTTP simulado, explícitamente identificado como tal.
