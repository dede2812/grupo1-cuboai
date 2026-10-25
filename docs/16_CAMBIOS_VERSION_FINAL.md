# Cambios de la fase final

Esta lista describe el trabajo posterior a `2ca48413` en
`feature/fluso-kingdom-mvp`. La plataforma multi-tienda, el catálogo, checkout,
Smart Fit, LookLab, Royal Stylist, editor de temas y contratos comerciales ya
existían en el desarrollo de Fluso. Se preservan y no se atribuyen nuevamente a
esta fase. El commit de cierre identifica el diff final; este documento no
anticipa un hash ni una publicación remota.

## Integridad comercial y proveedores

- Se conserva el tipo de oferta en cada `OrderItem` para que una edición posterior
  del catálogo no cambie el significado de una compra histórica.
- Pagos guardan intención antes de hacer HTTP, validan cuenta, entorno, pedido,
  referencia, importe y moneda, y actualizan intento y pedido atómicamente.
  El webhook fake público se deshabilitó.
- Reembolsos reservan saldo bajo bloqueo y usan claves idempotentes. La confirmación
  verificada que llega durante el HTTP prevalece incluso si la respuesta posterior
  falla. Se rechaza marcar reembolso total con importe inferior al cobro.
- Se añadieron adaptadores HTTP PayPal, Wompi SV y BTCPay y rutas de inicio,
  consulta/captura y retorno. Los métodos mostrados en checkout y pedido comparten
  configuración. El regreso del navegador no confirma dinero.
- MyDHL dispone de llamadas de tarifa y tracking. La compra de etiquetas sigue
  deshabilitada de forma explícita; no se declara validación externa.
- Los despachos validan líneas y cantidades históricas. La clave opcional de
  operación permite dos parciales idénticos y conserva el comportamiento de
  reintento de callers anteriores, sin una nueva tabla.
- Se añadió gestión manual de despachos al panel del pedido: cantidades por línea,
  retiro/entrega local, seguimiento, evidencia y actor. La acción lleva un token
  firmado por pedido/usuario y exige permiso de logística, POST y CSRF.
- El historial de salida física se conserva al pasar a incidencia. Una cancelación
  posterior no repone unidades despachadas; las devoluciones requieren recepción
  e inventario explícitos. Los estados del despacho y pedido siguen separados.
- Las reservas de servicios cuentan cantidades agregadas por horario;
  `Booking.quantity` conserva la ocupación. Las descargas comprueban elegibilidad
  financiera, activo y límite de usos mediante actualización condicional.

## Identidad, asesor y memoria

- `CustomerIdentity` aporta propietario opaco persistente para usuarios
  autenticados. Se agregaron registro, login, logout y cambio de contraseña con
  formularios Django y cuotas de intentos en base de datos.
- La importación de una visita invitada exige una elección explícita. Fusiones de
  carritos se serializan y rechazan conflictos; se invalidan revisiones y permisos
  de acción previos al cambio de identidad.
- El modo sin guardar conserva el mensaje actual para el proveedor y las
  conversaciones nuevas comienzan con historial desactivado.
- Se endurecieron validación de herramientas y respuestas, presupuestos,
  identificadores, conversión de medidas y manejo de NaN/infinito. Las tarjetas
  guardadas se rehidratan desde datos actuales.
- `AIUsageCounter` limita llamadas por titular/tienda y día de manera compartida
  entre procesos. Contexto, salida, rondas, herramientas y timeout quedan acotados;
  `reino_cleanup_ai` elimina contadores vencidos y expira propuestas.
- La comprobación del proveedor usa una solicitud real de texto cuando hay clave;
  no se ejecutó con credenciales reales en esta entrega.

## Analítica empresarial

- Se añadió dashboard de estadísticas y CSV por tienda con permisos financieros,
  filtros, comparación de períodos, gráficas SVG y tablas.
- Cobros, reembolsos acumulados, neto, ticket y cohortes se calculan con datos
  persistidos. Impuestos o importes desconocidos no se representan como cero.
- Eventos de producto, búsqueda, carrito, checkout y asesor se deduplican según
  su operación. No se registra el texto crudo de búsqueda en los eventos nuevos.
- La atribución al asesor exige una acción confirmada, el mismo carrito y una
  variante comprada. Abrir el chat no atribuye ventas.
- El CSV neutraliza fórmulas y evita exportar información personal de pedidos.
  El período representa creación de pedidos a su estado actual; no un libro de
  caja por fecha de cobro.

## Interfaz, operación y compatibilidad

- Wiener Kingdom adopta azul marino, carmín, marfil y plata mediante versiones de
  tema. `apply_release_theme` preserva otras tiendas e historial publicado.
- Se corrigieron comentarios de plantilla visibles, enlaces de tarjetas fuera de
  contexto, recursos de baja resolución, encabezado móvil y desbordes del editor.
- Se corrigió el formulario de alta de producto, se añadieron límites de campos,
  ajustes de inventario bajo bloqueo y paginación de listas operativas.
- El panel histórico limita acceso de miembros de otros negocios y conserva el
  funcionamiento de la aplicación `tienda`.
- Las membresías revocadas siguen contando para esa restricción. Ambos accesos
  de usuario comparten la cuota de intentos; el login histórico no la elude.
- Smart Fit general funciona sin perfil ni producto en la URL, muestra existencias
  tras reservas, conserva cm/pulgadas y evita resultados silenciosos.
- El detalle de pedido ofrece estados permitidos con etiquetas legibles y el
  inventario muestra unidades antes del ajuste. Se eliminaron avisos duplicados.
- Se entregan lanzadores Windows de arranque/parada local, probados sin duplicar
  servidor. No son instaladores ni incluyen un backend para cada comprador.
- Zona horaria y formato monetario se adaptan a la plataforma en español mediante
  middleware, conservando compatibilidad de rutas y pruebas históricas.
- CI ejecuta ambos módulos en SQLite y PostgreSQL; se corrigieron bloqueos de
  consultas con joins anulables y tamaño de eventos históricos. El resultado de
  una ejecución remota no se infiere del archivo de configuración.
- Se añadieron pruebas de regresión, barrido de rutas, script de navegador y
  documentación vigente con separación entre trabajo local y bloqueo externo.

## Migraciones de esta fase

| Migración | Cambio |
|---|---|
| `reino/0016_orderitem_offer_type.py` | Snapshot del tipo de oferta histórico |
| `reino/0017_customer_identity_ai_limits.py` | Identidad de comprador y contadores de uso |
| `reino/0018_booking_quantity.py` | Cantidades ocupadas por reserva de servicio |
| `tienda/0021_alter_orderevent_to_value.py` | Capacidad del valor auditado en eventos históricos |

El registro completo de pruebas está en
[12_PRUEBAS_Y_RESULTADOS.md](12_PRUEBAS_Y_RESULTADOS.md). Las diferencias de
alcance, credenciales faltantes y funciones aún no completadas se mantienen en
[15_ESTADO_FINAL_Y_TRAZABILIDAD.md](15_ESTADO_FINAL_Y_TRAZABILIDAD.md). No se
publicaron ni certificaron cobros, envíos o IA reales a partir de pruebas simuladas.
