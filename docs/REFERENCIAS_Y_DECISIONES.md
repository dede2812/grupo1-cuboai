> Registro histórico conservado. Las decisiones añadidas en la fase final figuran al final; para estado de proveedores y alcance vigente usar [Trazabilidad](15_ESTADO_FINAL_Y_TRAZABILIDAD.md).

# Referencias y decisiones de implementación

Fecha de consulta: 2026-10-22/23 (sandbox Fluso).

## Fuentes del documento de diseño (R1–R15) y su aplicación real

| Ref | Uso en esta build |
|---|---|
| R1 OpenAI function calling | `reino/ai/schemas.py`: especificaciones de herramientas; orquestador con rondas acotadas |
| R2 Django QuerySet API | `select_for_update` en `services_commerce` (transacciones cortas, orden estable) |
| R3 PostgreSQL RLS | **Planificado para staging** (documentado en 02/05); no activado en SQLite |
| R4 WCAG 2.2 | Criterios aplicados en CSS/markup; auditoría manual pendiente (declarado) |
| R5 Core Web Vitals | Umbrales citados como objetivo; no medidos en sandbox |
| R6 BTCPay | Referencia para F8; no integrado (P1) |
| R7/R8 Stripe availability/Connect | Elegibilidad SV **pendiente**; ningún cobro electrónico habilitado |
| R9 Shippo capabilities | Sin integración logística; matriz de zonas manual P0 |
| R10 Merchant listing | Datos estructurados: pendiente P1 (URLs estables ya existen) |
| R11/R12 Apple/Linear | Referencia estructural de mensajes breves; composición y textos originales |
| R13–R15 Shopify/WooCommerce/Tiendanube | «Tenemos IA» no se presenta como diferenciador; la prueba es el tiempo hasta una variante compatible explicada |

## Licencias de tipografía (verificado al incluir)

- **Fraunces** (titulares): SIL Open Font License 1.1 — familia variable de Undercasetype,
  distribuida por Google Fonts. Subconjuntos latin vendorados en `static/reino/fonts/`.
- **Manrope** (texto/UI): SIL Open Font License 1.1 — de Michael Sharanda, Google Fonts.
- Ambas permiten uso comercial y redistribución con licencia incluida; se recomienda
  copiar el texto OFL en `static/reino/fonts/OFL.txt` al desplegar (tarea registrada en STATUS).
- Respaldo declarado en CSS: Georgia/serif y stack de sistema.

## Imágenes

- Wiener Kingdom: fotografías reales ya presentes en el repositorio (`static/tienda/img/`),
  origen registrado en `ProductMedia.source` = «fotografía real del repositorio».
- Estudio Nube Demo: 7 imágenes generadas con IA para esta demo
  (`static/reino/img/nube/`), marcadas en `source` = «imagen generada — contenido de
  demostración» y en la UI («Tienda demo»). No representan productos reales en venta.
- Política de marca respetada: ninguna caricatura canina; el diagrama Smart Fit es SVG
  geométrico original.

## Decisiones técnicas registradas (resumen; detalle en 01/02)

1. Base = `feature/homepage-premium` (PR #2 integrado); PR #1 (docs) incorporado en `docs/proposal/`.
2. Una app nueva `reino` con servicios en vez de doce apps (permitido por el diseño).
3. `/` se conserva para la home histórica (suite legacy intacta); la plataforma vive en
   `/tiendas/` y `/s/<slug>/`. Adaptación mínima que no rompe pruebas.
4. Catálogo nuevo en DB + flujo Smart Quote legacy preservado como «hecho a medida» (S11).
5. Cuenta comprador por sesión en P0 (invitados); login de compradores = P1.
6. Reserva de 10 min; envío «por calcular» hasta cotizar zona; tarifa SV $3.50 = hipótesis.
7. Proveedor IA: adaptador OpenAI-compatible configurable (`REINO_AI_*`); modelo exacto =
   configuración tras evaluación con la batería preparada (80 casos), no una afirmación previa.
8. SQLite local con `transaction_mode=IMMEDIATE`; PostgreSQL objetivo staging/producción.
9. Fraunces+Manrope (OFL) vendoradas localmente tras verificar licencia — sin CDN en runtime.
10. Ninguna dependencia nueva en `requirements.txt` para la IA (urllib estándar): superficie
    de instalación idéntica a la histórica.


## Decisiones de la fase final

1. Continuar exactamente el fork/rama/commit indicado por el usuario: Fluso
   `feature/fluso-kingdom-mvp`, `2ca48413`; no reconstruir desde main.
2. Conservar Django, plantillas y servicios. Gráficas SVG locales sin dependencias
   de frontend nuevas; tabla accesible como alternativa al gráfico.
3. Reportar cohortes de pedidos a estado actual, con períodos iguales. No llamar
   flujo de caja a importes agrupados por fecha de creación.
4. Seleccionar pedidos completos al filtrar producto/categoría. No repartir
   descuentos, reembolsos o impuestos sin datos de línea que lo permitan.
5. Exigir acción confirmada, mismo carrito y variante realmente comprada para
   atribuir asistencia al asesor; no atribuir por apertura de chat.
6. Persistir identidad de compradores autenticados sin convertir la sesión de
   navegador en credencial de otro usuario. Importación invitada explícita.
7. Mantener adaptadores reales separados del dominio y estados externos no
   verificados claramente identificados. Pruebas HTTP controladas no equivalen
   a una transacción sandbox real.
8. Conservar informes anteriores como historia y consolidar el cierre en docs12,
   docs15 y docs16. No reemplazar resultados fallidos con conteos de otra ronda.
9. Mantener el backend centralizado para cualquier experiencia instalable futura;
   no distribuir un SQLite independiente ni secretos por comprador.
