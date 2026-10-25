> Nota de cierre: este documento conserva la visión y decisiones originales de Fluso. El alcance implementado y las limitaciones vigentes están en [Funcionalidades](05_FUNCIONALIDADES.md) y [Estado final](15_ESTADO_FINAL_Y_TRAZABILIDAD.md). No interpretar capacidades planificadas como verificadas externamente.

# 01 · Producto y diseño (F1)

Adaptación del documento de diseño («WIENER KINGDOM — Diseño de producto y plan de
construcción», v2, 22-oct-2026) a la base real del repositorio.

## Visión implementada

- **Wiener Kingdom**: boutique digital de moda para dachshunds. Promesa: «Estilo propio.
  Medidas que importan.» Universo: «Cada pequeño rey merece su reino.»
- **Reino Commerce** (nombre de trabajo): la tecnología multi-tienda común. Wiener Kingdom
  es su primera tienda; **Estudio Nube Demo** (papelería ficticia, marcada como datos de
  prueba, sin cobros reales) demuestra que la plataforma no depende de medidas caninas.
- LookLab convierte medidas/ocasión/estilo/presupuesto en un look revisable y comprable.
- Royal Stylist es el asesor conversacional conectado a un modelo real (ver 03).
- Royal Passport guarda, con permiso, perfiles y medidas reutilizables.

## Mapa de pantallas construido (rutas reales)

| ID | Pantalla | Ruta real | Estado |
|---|---|---|---|
| S01 | Inicio de tienda | `/s/{slug}/` | verificado |
| S02 | Colección/búsqueda | `/s/{slug}/coleccion/` | verificado |
| S03 | Producto | `/s/{slug}/producto/{slug}/` | verificado |
| S04 | LookLab (4 pasos + revelación) | `/s/{slug}/looklab/` | verificado |
| S05 | Guía de tallas / Smart Fit | `/s/{slug}/tallas/` | verificado |
| S06 | Royal Stylist | `/s/{slug}/asesor/` | verificado (modo rules sin clave) |
| S07 | Carrito | `/s/{slug}/carrito/` | verificado |
| S08 | Checkout (3 pasos) | `/s/{slug}/checkout/` | verificado |
| S09 | Confirmación y seguimiento | `/s/{slug}/pedido/{id}/` + token | verificado |
| S10 | Cuenta / Royal Passport | `/cuenta/` | verificado |
| S11 | Cotización (Smart Quote) | `/quote/...` (flujo histórico preservado) | verificado (suite legacy) |
| S12 | Ayuda / políticas | `/s/{slug}/ayuda/` | verificado |
| S13 | Lookbook | — | **P1**, no construido (guardar look básico sí, P0) |
| M01 | Para negocios | `/para-negocios/` | verificado |
| M02 | Alta de comercio | — | P0 mínimo diferido: alta por seed/invitación |
| M03 | Resumen | `/negocio/{slug}/` | verificado |
| M04 | Catálogo | `/negocio/{slug}/catalogo/` | verificado (lista; editor P1) |
| M05 | Pedidos + transiciones | `/negocio/{slug}/pedidos/` | verificado |
| M06–M09 | Clientes, marketing, finanzas, logística | — | P1 planificado |
| M10 | Configuración + integraciones | `/negocio/{slug}/configuracion/` | verificado |
| P01 | Directorio | `/tiendas/` | verificado |
| P02 | Plataforma | `/plataforma/` (superusuario) | verificado mínimo |

**Redirecciones documentadas:** ninguna. `/` conserva la home histórica (PR #2) con una
franja única y real hacia la nueva boutique; la experiencia Reino Commerce vive en
`/tiendas/`, `/s/{slug}/…`, `/cuenta/`, `/para-negocios/`, `/negocio/{slug}/…` y
`/plataforma/`. Todas las rutas legacy (`/productos/`, `/smart-fit/`, `/quote/`, `/cart/`,
`/order/`, `/panel/`) operan sin cambios y la suite histórica queda en verde (289 tests).
Decisión registrada: la adaptación mínima que no rompe ninguna prueba existente (§22:
«resolver semánticamente, conservar pruebas»).

## Sistema visual Royal Editorial (implementado)

- Tokens en `static/reino/css/reino.css`: marfil `#FAF8F6`, navy `#101E36`, carmín
  `#AF3635` (hover borgoña `#842F34`), acero `#366A91`, plata `#C5CBD5`, tinta `#1A2538`.
- Tipografía: **Fraunces** (titulares) + **Manrope** (texto/controles), vendoradas en
  `static/reino/fonts/` (subconjuntos latin woff2). Licencia: SIL OFL 1.1 para ambas
  (ver REFERENCIAS_Y_DECISIONES.md). Respaldo: Georgia/serif y system sans.
- Retícula: contenedor 1,248 px máx., radios 10/16/24, escala de espaciado 4–96,
  botones 48 px (área táctil ≥44), hero editorial 620 px desktop.
- Movimiento: 120–180 ms controles; `prefers-reduced-motion` respeta omisión.
- Diagrama Smart Fit: SVG original inline (no caricatura canina, política de marca).
- Imágenes Estudio Nube: generadas como contenido de demostración y marcadas así en
  `ProductMedia.source`. Fotos de Wiener Kingdom: fotografías reales del repositorio.
- Copy en español con voseo («Encontrá su look», «Revisar talla», «Agregar al carrito»).
  La interfaz histórica legacy se mantiene en su idioma original (documentado).

## Componentes (§4) y dónde viven

Header + barra de contexto (`templates/reino/base.html`), ProductCard y FitStatus
(`_product_card.html`), PriceBlock + VariantSelector + acordeones (`product_detail.html`),
elecciones LookLab + revelación (`looklab.html`), chat con tarjetas (`stylist.html` +
`_stylist_reply.html`), resumen de carrito/checkout (`cart.html`, `checkout*.html`),
estados vacíos y toasts (CSS `.empty-state`, `.flash-ok`, `.form-errors`),
panel sobrio navy 232 px (`merchant_base.html`).

## Cambios respecto del documento de diseño (adaptaciones registradas)

1. **Una app nueva `reino`** en lugar de doce módulos: el propio diseño lo permite
   («no se exige crear doce apps si servicios organizados logran lo mismo»). Límites por
   archivos de servicio: `services_fit`, `services_recommend`, `services_commerce`,
   `services_memory`, `ai/`.
2. **Catálogo nuevo en DB**; el dict histórico se preserva para el flujo Smart Quote (S11)
   que sigue operando como «pieza hecha a medida». Enlaces desde la ficha nueva.
3. **Carrito/pedido nuevo** (`reino`) para el flujo de boutique; el carrito/pedido legacy
   queda para cotizaciones a medida. Ambos aparecen en paneles separados por tienda.
4. **Reserva de stock de 10 min** implementada en checkout (propuesta inicial del diseño).
5. **Cuenta P0 por sesión** (sin registro de usuarios compradores): el diseño permite
   invitados; la identidad comprador→cuenta con login es P1.
6. **Fecha de entrega exigida**: no implementada en P0 — la entrega se declara siempre
   «por confirmar» (DELIVERY_UNKNOWN), que es el comportamiento honesto exigido.
7. Fotos de perfil: el modelo las admite (`photo_path`) pero la subida de archivos
   queda P1 (validación/escaneo pendiente); la foto nunca es obligatoria.
