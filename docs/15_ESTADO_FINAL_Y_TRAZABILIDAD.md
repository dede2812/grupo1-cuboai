# Estado final y trazabilidad

Fecha de consolidación: 25 de octubre de 2026. Base de esta fase:
`dede2812/grupo1-cuboai`, rama `feature/fluso-kingdom-mvp`, commit inicial
`2ca484130e7c6bb77dcb7d66002d6d49f5d4bde6`, vinculado al
[PR #3](https://github.com/CUBO-IA/grupo1-cuboai/pull/3).

Se conserva el desarrollo de Fluso y se amplía dentro de Django, sus servicios y
plantillas. No se reconstruyó desde main. La entrega distingue código local
ejecutable, pruebas con dobles de proveedores y operaciones externas comprobadas.
**No corresponde declarar validación externa al 100 %:** no se aportaron las
credenciales ni la infraestructura necesarias para verificar IA, pasarelas,
webhooks públicos y transportista. Tampoco se efectuó publicación en producción.

El registro autoritativo de comandos, resultados completos SQLite/PostgreSQL y
capturas de esta fase es [12_PRUEBAS_Y_RESULTADOS.md](12_PRUEBAS_Y_RESULTADOS.md).
Los conteos de documentos históricos no sustituyen ese registro. La presencia de
un módulo en la tabla siguiente identifica cobertura y evidencia reproducible;
no afirma por sí sola que se ejecutó su última versión.

## Matriz de requisitos

Las rutas de implementación y prueba son relativas a `web/`, salvo que se indique
otra ubicación. «Local» significa implementado para ejecución y validación local;
la aprobación de una instalación productiva requiere sus propios resultados.

| Requisito | Implementación / evidencia | Prueba reproducible | Estado y límite |
|---|---|---|---|
| Continuidad del proyecto | Historial Git; `docs/04_PROCESO_DE_DESARROLLO.md` | Diff contra `2ca48413`; suite completa incluyendo `tienda` | Base indicada preservada; sin merge a main |
| Directorio y tiendas aisladas | `reino/tenancy.py`, `views_platform.py`, `views_storefront.py` | `test_tenancy`, `test_explore`, `test_release_surface` | Local; visibilidad validada en servidor |
| Catálogo, búsqueda y comparador | `views_explore.py`, servicios de ranking y catálogo | `test_explore`, `test_compare`, `test_surface_filters` | Local; precios y disponibilidad desde catálogo |
| Diseño de Wiener Kingdom | `services_theme.py`, `static/reino/css/reino.css`, comando `apply_release_theme` | `test_theme`, `test_release_surface`, `scripts/browser_release.cjs` | Tema preserva otras tiendas y versiones; evidencia visual en docs12 |
| Carrito y checkout | `services_commerce.py`, `views_storefront.py` | `test_commerce`, `test_flow`, `test_postgres`, suites `tienda` | Revisión, reserva e idempotencia; importes del servidor |
| Identidad persistente de comprador | `CustomerIdentity`, `services_identity.py`, `views_auth.py` | `test_customer_accounts` | Registro/login/logout/cambio de contraseña; importación invitada explícita |
| Recuperación de cuenta | Formularios Django implementados en `views_auth.py` | `test_customer_accounts` | Cambio autenticado disponible; recuperación por correo/verificación de email no implementadas |
| Perfil y memoria consentida | `services_memory.py`, `views_account.py` | `test_ai_release`, `test_round2`, `test_customer_accounts` | Lectura por finalidad; revocación y sellado de contexto |
| Smart Fit | `services_fit.py`, tablas `FitRule` | `test_fit`, `test_ai_release`, `test_flow` | Reglas versionadas; unidades y números finitos; sin garantía de ajuste fotográfico |
| LookLab | `views_looklab.py`, `services_recommend.py` | `test_flow`, `test_ai_release`, `test_eval_dataset` | Selección guiada y confirmación; no probador generativo de imágenes |
| Asesor con herramientas | `ai/adapter.py`, `orchestrator.py`, `schemas.py`, `tools.py` | `test_ai`, `test_ai_release`, `test_eval_dataset` | Adaptador y fallback locales; proveedor real sin validar |
| Uso de IA bajo concurrencia | `AIUsageCounter`, `_reserve_provider_call`, `reino_cleanup_ai` | `test_ai_concurrency` en PostgreSQL | Cuotas persistidas; límite de rondas, herramientas y contexto |
| Panel y permisos | `views_merchant.py`, `ROLE_CAPABILITIES`, `tienda/panel.py` | `test_merchant_ops`, `test_tenancy`, `test_release_surface` | Aislamiento por membresía; logística no confirma dinero |
| Estadísticas y exportación | `services_business.py`, `views_business.py`, `business_dashboard.html` | `test_business` | KPI calculados; datos ausentes explícitos; filtros y CSV autorizado |
| Promociones | Regla de descuento Bitcoin e instrumentación analítica | `test_commerce`, `test_business` | Regla existente; no gestor general de campañas/cupones |
| Integridad de pagos | `services_payments.py`, `views_payments.py` | `test_payments`, `test_payment_shipping_integrity` | Intención durable, captura/reembolso atómicos, saldo acumulado e idempotencia |
| PayPal | `payments/paypal.py` | `test_provider_contracts` con HTTP controlado | Crear/consultar/capturar/reembolsar implementado; falta sandbox real |
| Wompi El Salvador | `payments/wompi.py` | `test_provider_contracts` con HTTP controlado | Enlace USD y consulta implementados; reembolso no soportado por contrato público consultado |
| BTCPay | `payments/btcpay.py` | `test_provider_contracts` con HTTP controlado | Factura y firma HMAC; devolución inicia solicitud pendiente, no confirma payout |
| Despacho local y retiro | `services_shipping.py`, `views_shipping.py`, `merchant_shipments.html` | `test_shipping`, `test_shipping_views`, `test_payment_shipping_integrity` | UI por líneas, parciales, actor/evidencia, seguimiento y claves de operación |
| MyDHL | `shipping/mydhl.py` | `test_provider_contracts` con HTTP controlado | Tarifa y tracking como adaptador; compra de etiquetas/aduana/checkout sin completar ni validar externamente |
| Restitución de inventario | `_restock_once`, historial de `ShipmentEvent` | `test_payment_shipping_integrity`, `test_postgres` | Cancelación no repone unidades que salieron, incluso con incidencia posterior |
| Digitales y servicios | `services_fulfillment.py`, snapshots y `Booking.quantity` | `test_fulfillment` y suites de comercio | Permisos de descarga y capacidad por cantidades; recibo físico exige operación explícita |
| Infraestructura y CI | `config/settings.py`, migraciones, `.github/workflows/ci.yml` | `check`, migraciones, suites completas de docs12 | SQLite local y PostgreSQL; CI no excluye `tienda`; sin afirmar ejecución remota no observada |
| Operación y respaldo | Outbox, `backup_reino`, `restore_check`, `/salud/` | `test_outbox`, `test_ops`, `test_round2` | Procedimientos locales; configurar scheduler, correo y backups productivos |
| Instalables Windows | `docs/11_INSTALACION_Y_DESPLIEGUE.md` | Inventario de artefactos reales en docs12 | No se generan EXE/instaladores públicos con backend local separado; etapa posterior a validación requerida |

## Bloqueos concretos

1. **IA real:** falta una clave autorizada y evaluación real del modelo configurado.
   La selección guiada por reglas funciona sin ella; una variable presente no
   equivale a conectividad verificada.
2. **Pasarelas:** faltan cuentas elegibles, secretos y dominio HTTPS con webhooks.
   Los tests sustituyen el transporte HTTP. Es necesario ejecutar creación,
   confirmación, duplicados, fallo y devolución en sandbox con evidencia del
   proveedor antes de habilitar dinero real.
3. **Devoluciones externas:** Wompi SV exige un procedimiento autorizado fuera de
   la API de enlaces aquí implementada; BTCPay requiere conciliar payout final.
   Una solicitud pendiente nunca se suma como dinero devuelto.
4. **MyDHL:** quedan por implementar el recorrido de paquete/origen/aduana,
   compra/recuperación privada de etiqueta y selección de tarifa en checkout,
   además de verificar la cuenta. La gestión manual de despachos no depende de ello.
5. **Operación productiva:** faltan infraestructura central, dominio/TLS, correo
   real, política de respaldo/retención y ensayos en ese entorno. No se instalaron
   políticas RLS de PostgreSQL; el aislamiento actual está en la aplicación.
6. **Alcance de producto:** no hay gestor general de promociones, desglose fiscal
   por línea, recuperación de contraseña por correo ni probador visual generativo.
   El panel deja sin calcular métricas cuyo dato fuente no existe.
7. **Rendimiento y accesibilidad:** las revisiones locales y capturas no equivalen
   a métricas de campo LCP/INP/CLS ni a certificación de accesibilidad externa.
8. **Windows:** la condición previa del encargo exige validar el núcleo y el
   backend central antes de distribuir instaladores. Un lanzador de desarrollo,
   si se incluye, no es un instalador ni una aplicación productiva independiente.

## Índice de los 16 temas documentales

Se reutilizan equivalentes existentes para conservar continuidad y evitar dos
versiones incompatibles del mismo tema.

| Tema solicitado | Documento vigente |
|---|---|
| 01 Visión y alcance | [01_PRODUCTO_Y_DISENO.md](01_PRODUCTO_Y_DISENO.md) |
| 02 Arquitectura | [02_ARQUITECTURA_Y_DATOS.md](02_ARQUITECTURA_Y_DATOS.md) |
| 03 Modelo de datos | Sección de entidades y migraciones en [02_ARQUITECTURA_Y_DATOS.md](02_ARQUITECTURA_Y_DATOS.md) |
| 04 Desarrollo | [04_PROCESO_DE_DESARROLLO.md](04_PROCESO_DE_DESARROLLO.md) |
| 05 Funcionalidades | [05_FUNCIONALIDADES.md](05_FUNCIONALIDADES.md) |
| 06 IA | [06_INTELIGENCIA_ARTIFICIAL.md](06_INTELIGENCIA_ARTIFICIAL.md) |
| 07 UX/UI | [07_DISENO_UX_UI.md](07_DISENO_UX_UI.md); referencias previas en [DIRECCION_VISUAL.md](DIRECCION_VISUAL.md) |
| 08 Empresa | [08_PANEL_EMPRESARIAL.md](08_PANEL_EMPRESARIAL.md) |
| 09 Pagos y logística | [09_PAGOS_Y_LOGISTICA.md](09_PAGOS_Y_LOGISTICA.md) |
| 10 Seguridad | [10_SEGURIDAD_Y_PRIVACIDAD.md](10_SEGURIDAD_Y_PRIVACIDAD.md) |
| 11 Instalación | [11_INSTALACION_Y_DESPLIEGUE.md](11_INSTALACION_Y_DESPLIEGUE.md) |
| 12 Pruebas | [12_PRUEBAS_Y_RESULTADOS.md](12_PRUEBAS_Y_RESULTADOS.md) |
| 13 Decisiones | [REFERENCIAS_Y_DECISIONES.md](REFERENCIAS_Y_DECISIONES.md) |
| 14 Uso | [14_MANUAL_DE_USUARIO.md](14_MANUAL_DE_USUARIO.md) |
| 15 Estado | Este documento |
| 16 Cambios | [16_CAMBIOS_VERSION_FINAL.md](16_CAMBIOS_VERSION_FINAL.md) |

Los informes `STATUS.md`, `07_MATRIZ_AUDITORIA_R01_R13.md`,
`08_MATRIZ_REVISION_2.md` y `09_CIERRE_FINAL.md` conservan evidencia de fases
anteriores; las limitaciones y capacidades nuevas se interpretan con esta matriz.
