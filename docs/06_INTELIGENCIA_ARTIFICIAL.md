# Inteligencia artificial, recomendaciones y memoria

Esta fase conserva Royal Stylist, Smart Fit y LookLab de Fluso y corrige sus
límites de entrada, permisos, consentimiento y uso de datos. El asesor cuenta con
un adaptador HTTP compatible con Chat Completions y un modo alternativo de reglas.
**No se verificó una respuesta de un proveedor real en esta entrega**: no se
proporcionó una clave de API. Las respuestas controladas de los tests no son una
evaluación externa del modelo.

## Recorrido del asesor

1. La vista resuelve tienda y titular en servidor; la conversación debe pertenecer
   a ambos. Una cuenta autenticada usa `CustomerIdentity`; el invitado conserva su
   alcance de sesión.
2. `intent-v1` interpreta consulta, categorías, exclusiones y presupuesto. Las
   herramientas consultan el catálogo visible y los servicios de dominio; no
   aceptan una tienda arbitraria enviada por el modelo.
3. Las herramientas de lectura obtienen productos, variantes, inventario, talla,
   recomendaciones, políticas, opciones de envío, preferencias consentidas,
   carrito y pedido autorizado. Los argumentos se validan en servidor incluso
   cuando el proveedor declara un esquema JSON.
4. Una propuesta de agregar al carrito no modifica la compra. `ActionToken` liga
   destinatario, variante, cantidad y cotización, con caducidad y consumo atómico
   de un solo uso. El comprador confirma mediante POST; precio, stock y permiso
   se vuelven a comprobar.
5. El texto se contrasta con hechos obtenidos de herramientas. Las tarjetas
   persistidas se reconstruyen con precio y medios actuales del catálogo.

El modelo no es autoridad sobre precios, existencias, talla garantizada, descuentos,
impuestos, envío ni estado financiero. La validación textual reduce afirmaciones
sin respaldo, pero no constituye una garantía universal contra alucinaciones.
Documentos recuperados y mensajes son datos de contexto, no permisos adicionales.

## Smart Fit y LookLab

Smart Fit aplica tablas versionadas del producto y medidas explícitas o
consentidas. Convierte pulgadas a centímetros antes de evaluar rangos y rechaza
unidades desconocidas, valores negativos, NaN e infinito. La compatibilidad se
explica con las reglas disponibles; una fotografía no reemplaza la medición.

LookLab construye una selección de piezas por ocasión, talla y presupuesto.
Valida identificadores, titular, consentimiento y token de acción antes de añadir
productos. No genera una prueba fotográfica del producto sobre el cuerpo ni
afirma precisión de un probador virtual. Los presupuestos distinguen productos
del total con envío; no se inventa una tarifa para satisfacer el límite.

## Memoria y privacidad

Las conversaciones nuevas comienzan en **«sin guardar»**. El mensaje actual llega
al proveedor cuando está configurado, aunque no se persista historial. Activar
historial es una elección explícita desde ese momento; no recupera mensajes
anteriores del modo efímero.

Medidas y preferencias se leen mediante comprobaciones de consentimiento vigente
por finalidad, perfil, tienda y titular. Revocar consentimiento sella el contexto
anterior del proveedor y elimina derivados afectados. Borrar memoria de un perfil
no equivale a borrar los registros comerciales de un pedido. El modo sin historial
tampoco impide consultar datos estructurados que la persona autorizó por separado.

Al ingresar a una cuenta, importar carrito, perfiles y looks de la visita requiere
marcar una opción no preseleccionada. La importación se serializa, no permite
reclamar otra identidad y rechaza fusiones incompatibles. Tokens de acción y
revisiones anteriores de checkout se invalidan en el cambio de identidad.

## Configuración y límites

La configuración proviene de `config/settings.py` y variables de entorno. No
incluir claves en plantillas, repositorio, capturas o paquetes de distribución.

| Variable / límite | Valor predeterminado | Alcance |
|---|---:|---|
| `REINO_AI_API_KEY` | Vacío | Sin clave se usa selección guiada por reglas |
| `REINO_AI_BASE_URL` | `https://api.openai.com/v1` | HTTPS; HTTP solo para localhost |
| `REINO_AI_MODEL` | `gpt-4o-mini` | Configurable; no validado aquí con cuenta real |
| `REINO_AI_TIMEOUT` | 12 segundos | Tope de 30 segundos por solicitud |
| `REINO_AI_MAX_INPUT_CHARS` | 8000 | Entrada actual completa, sin truncado silencioso a 500 |
| `REINO_AI_MAX_CONTEXT_CHARS` | 32000 | Contexto JSON acotado; hasta 12 mensajes históricos |
| `REINO_AI_MAX_COMPLETION_TOKENS` | 600 | Límite enviado al proveedor |
| Rondas / herramientas | 4 / 12 | Máximos por turno |
| `REINO_AI_SESSION_HOURLY_LIMIT` | 120 | Llamadas de proveedor por titular y tienda por hora |
| `REINO_AI_STORE_DAILY_LIMIT` | 2000 | Llamadas de proveedor por tienda y día |

`AIUsageCounter` guarda contadores en base de datos y reserva cada llamada mediante
actualización condicional dentro de una transacción. Varias instancias web no
pueden evadir la cuota usando cachés independientes. La transacción termina antes
del HTTP. Una cuota agotada, falta de clave o fallo del proveedor devuelve modo de
reglas identificado; no simula que respondió un modelo.

El adaptador limita el cuerpo de respuesta, valida su forma, evita registrar
cuerpos de error o secretos y solicita `store: false`. Este parámetro no sustituye
las políticas contractuales de retención del proveedor elegido. El límite por
tienda es un control de uso, no una garantía exacta de gasto monetario.

Ejecutar periódicamente `python manage.py reino_cleanup_ai` elimina contadores
vencidos y expira propuestas pendientes; no borra pedidos ni todo el historial
comercial. No se instaló un planificador de producción en esta entrega.

## Validación y pendientes

Los módulos `test_ai`, `test_ai_release`, `test_ai_concurrency`, `test_round2`,
`test_customer_accounts`, `test_flow`, `test_fit` y las baterías de evaluación
existentes cubren contratos y regresiones locales. Consultar
[Pruebas y resultados](12_PRUEBAS_Y_RESULTADOS.md) para la ejecución final; este
documento no reutiliza resultados históricos como si fueran nuevos.

`adapter.probe()` realiza una solicitud de texto real; encontrar una clave o listar
modelos no demuestra conectividad. Antes de habilitar IA en producción faltan:
configurar una cuenta autorizada, ejecutar esa prueba, correr la batería con el
modelo elegido y revisar respuestas en español, latencia, costo, errores y casos
adversarios. La narrativa empresarial generada por un modelo no se presenta como
una capacidad validada: el panel actual calcula sus cifras en servicios locales.
