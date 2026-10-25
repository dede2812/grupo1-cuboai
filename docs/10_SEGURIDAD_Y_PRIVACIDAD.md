# Seguridad y privacidad

Este documento describe controles del código. Una prueba local no certifica la
seguridad de una infraestructura de producción ni sustituye su configuración.
El alcance y los bloqueos vigentes están en `15_ESTADO_FINAL_Y_TRAZABILIDAD.md`.

## Autorización y aislamiento

La tienda pública se resuelve en servidor mediante `reino.tenancy.get_store`.
Un negocio no activo o una tienda en borrador no se descubre por cambiar un slug.
Catálogo, carrito, checkout, pedido, recomendaciones y datos de mascotas se
consultan dentro de ese alcance. Los identificadores enviados por navegador o
modelo se validan nuevamente; no conceden acceso por sí mismos. Las cuentas usan
`CustomerIdentity`, una clave opaca estable; importar datos de invitado exige una
elección explícita y no permite reclamar la identidad de otra cuenta.

Los paneles requieren usuario autenticado y `MerchantMember` activo del negocio.
Las capacidades de `services_commerce.ROLE_CAPABILITIES` se validan en servidor:

| Rol | Capacidades |
|---|---|
| Propietario | Pedidos, pagos, cumplimiento, catálogo, inventario, configuración y equipo |
| Equipo | Pedidos, cumplimiento, catálogo e inventario |
| Logística | Cumplimiento |
| Operador de plataforma | Permiso separado `reino.operate_platform`; `is_staff` por sí solo no lo concede |

El nuevo dashboard financiero y CSV exigen capacidad `payments`. No basta poder
ver el catálogo o tener una membresía en otra tienda. Las opciones de producto y
categoría se validan contra la tienda autorizada.

Pedidos invitados requieren UUID de pedido y token de acceso, o su relación
autorizada con la sesión. La referencia legible no es una contraseña. Los enlaces
con token deben tratarse como información privada. Los permisos se prueban tanto
en vistas como en servicios; no dependen de ocultar botones.

El aislamiento está implementado en la aplicación. **No hay políticas PostgreSQL
RLS instaladas**. Una nueva consulta de código debe conservar el filtro de tenant.
La existencia de un motor PostgreSQL no implica aislamiento automático.

## Compra, pagos y entregas

El servidor reconstruye precio, descuento, disponibilidad y envío. Los cambios
de carrito invalidan la revisión del checkout. Reservas y escritura de pedidos
usan transacciones, claves idempotentes y bloqueos compatibles con PostgreSQL.
Los estados de pedido, pago, preparación y entrega son independientes.

Los adaptadores de pago conservan referencias y respuestas minimizadas, no PAN,
CVV ni credenciales del cliente. Mostrar un enlace o QR nunca confirma dinero.
Los webhooks verifican autenticidad según el contrato del proveedor y se
deduplican. La confirmación financiera requiere importe, moneda y pedido
coherentes. Reembolsos y restock se registran separadamente; un reembolso parcial
no debe restituir automáticamente todas las unidades.

La validación externa requiere cuentas y credenciales del proveedor. Las pruebas
de contrato con respuestas controladas no prueban cobros o entregas reales.
Consultar `09_PAGOS_Y_LOGISTICA.md` para límites específicos.

## Sesión, formularios y salida

Django aporta autenticación, sesiones, hash de contraseñas, middleware CSRF, ORM
parametrizado y escape predeterminado de plantillas. Los cambios de estado se
realizan por POST con CSRF, salvo webhooks autenticados por su mecanismo externo.
No deben añadirse `safe` o consultas SQL concatenadas a entradas de usuarios.

El CSV financiero neutraliza prefijos que Excel u otras hojas podrían interpretar
como fórmulas. No exporta nombres, emails, direcciones ni tokens de pedido. El
panel y CSV se devuelven con `Cache-Control: private, no-store`.

## Datos recordados y asesor

Medidas, preferencias y memoria requieren consentimiento por finalidad y alcance.
Las consultas de perfil se restringen a identidad/sesión autorizada y tienda.
La revocación impide recuperar información afectada y sella historial previo
según la implementación de `services_memory`. El modo «sin guardar» ofrece
contexto temporal en lugar de reutilizar conversación persistente.

Los documentos recuperados y el texto del comprador son datos, no instrucciones
que puedan elevar permisos. El modelo no fija precios ni inventario. Las
herramientas verifican catálogo, talla, presupuesto y pertenencia; las escrituras
requieren confirmación con token de un solo uso y vencimiento.

Los eventos de analítica guardan una clave técnica de sesión y datos mínimos de
operación. Las búsquedas nuevas guardan conteo de resultados, no texto introducido.
Los reportes agrupan clientes mediante email en minúsculas pero no lo muestran.
No se pretende identificar una persona que usa varios dispositivos o emails.
No existe en esta fase un programa automático general de retención y borrado de
todos los eventos comerciales; el negocio debe definirlo antes de operación real.
Eliminar memoria de personalización no borra por sí solo registros comerciales.

## Archivos y secretos

Las cargas pasan por `services_media`: tamaño y tipo permitido, decodificación de
imagen y rutas controladas. El catálogo registra procedencia de los activos.
LookLab no debe anunciar una simulación fotográfica precisa: su capacidad es una
selección guiada de piezas, talla y ocasión.

Las credenciales se leen del entorno o de `web/.env`, excluido de Git. El archivo
`.env.example` contiene nombres y valores de desarrollo, nunca secretos reales.
No copiar archivos `.env`, backups, bases locales o credenciales de prueba a un
paquete público. Los usuarios del seed son exclusivamente de demostración.

## Configuración de despliegue

En `REINO_ENV=prod` o `staging`, faltan secreto o hosts permitidos ⇒ falla el
arranque. Configurar HTTPS, cookies seguras, CSRF origins, HSTS y el proxy de
confianza conforme a `config/settings.py`. El encabezado de proxy HTTPS solo es
seguro si el proxy elimina cualquier valor externo falsificado.

PostgreSQL, procesos web, worker outbox, medios y backups necesitan permisos y
credenciales propios. Ejecutar `manage.py check --deploy`, aplicar migraciones y
ensayar restauración. No se publicará producción ni se modificará main sin
autorización del propietario del proyecto.

## Evidencia y límites

`/cuenta/ingresar/` y `/panel/login/` comparten el contador de intentos de login.
Los GET no consumen cuota; el agotamiento devuelve 429 antes de verificar otra
contraseña. El panel histórico evalúa membresías activas e históricas: revocar
la última membresía de un negocio no concede acceso a Wiener Kingdom.

Pruebas relevantes: `test_tenancy`, `test_audit`, `test_round2`, `test_ai`, `test_ai_release`, `test_payment_shipping_integrity`,
`test_business` y los casos de autorización de `test_merchant_ops`/`test_ops`.
La lista exacta ejecutada y sus resultados está en `12_PRUEBAS_Y_RESULTADOS.md`.
No se afirma haber realizado pentest externo, certificación de accesibilidad,
auditoría legal o medición de disponibilidad de producción.
