> Estado histórico de rondas anteriores, conservado como evidencia del trabajo de Fluso. El estado autoritativo de esta fase es [15_ESTADO_FINAL_Y_TRAZABILIDAD.md](15_ESTADO_FINAL_Y_TRAZABILIDAD.md), con resultados en [12_PRUEBAS_Y_RESULTADOS.md](12_PRUEBAS_Y_RESULTADOS.md). Las cifras de 432/493 pruebas que siguen no son resultados nuevos.

# STATUS · Wiener Kingdom / Reino Commerce

Actualizado: 23-oct-2026 (segunda ronda: revisión independiente 2 cerrada).
Rama: `feature/fluso-kingdom-mvp` · PR #3 (draft) en CUBO-IA/grupo1-cuboai.

## Estado por área

| Área | Estado |
|---|---|
| Suite completa | **432 pruebas OK** · 5 saltadas solo en SQLite (concurrencia PostgreSQL, que CI ejecuta SIN skip) |
| Auditoría 1 (R01–R13) | Cerrada en ronda 1 (matriz docs/07) |
| Auditoría 2 (N01–N11) | **11/11 corregidos y probados** (matriz docs/08) |
| Regresiones | 14 de auditoría 1 + 11 de auditoría 2 + dataset 81 casos, en CI |
| CI | Job SQLite (suite + check --deploy) + job PostgreSQL (servicio real) |
| Comercio | Checkout intento/revisión/digest, reservas 10 min, stock agregado, restitución exactamente-una-vez, reembolsos con evidencia |
| IA (Royal Stylist) | Propuestas con permiso de un solo uso vinculado (destinatario + cotización); validación de texto por hechos tipados; memoria sellada al revocar. **Proveedor real: implementado, pendiente de clave** |
| Memoria | Lectura autorizada por finalidad; revocar sella historial del proveedor; borrado total con alcance por perfil |
| Plataforma | /explorar/, /buscar/ (reglas, sin IA), /comparar/ (2–4, diferencias, compartir, recálculo), /tiendas/ con filtros |
| Temas | StoreThemeVersion (borrador/publicar/restaurar, contraste AA); estudio de diseño con preview y carga real de imágenes |
| Integraciones | Estados comprobados con fecha (IntegrationState); correo transaccional real probado con backend local (locmem) |
| Operación | Outbox con claim+backoff; PostgreSQL en CI; WhiteNoise en prod; medios por MEDIA_ROOT; .env real |

## Bloqueos externos (honestos, sin maquillar)

1. `REINO_AI_API_KEY` — pasa el asesor a modo real y habilita la evaluación con proveedor.
2. Pasarela de pagos electrónica (elegibilidad SV); manual + Bitcoin manual operan.
3. RLS en PostgreSQL: no existe; CI cubre concurrencia/migraciones, políticas aparte.
4. Tarifa $3.50 San Salvador: hipótesis pendiente del negocio.
5. Activo de marca «WEINER» vs «Wiener»: hero ya sin el activo erróneo; validación de marca pendiente.
6. Métricas de campo (LCP/INP/CLS): metas, pendientes de tráfico real.

## Cómo correr

```bash
cd web
python -m venv ../venv && ../venv/bin/pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo        # no destructivo; --reset protegido fuera de dev
python manage.py test             # 432 OK (5 skipped en SQLite)
python manage.py process_outbox   # cola de correo/métricas
python manage.py runserver
```

Plataforma: `/explorar/` · Tiendas: `/tiendas/` · Panel: `/negocio/wiener-kingdom/`
(demo_staff/demo1234, solo demo) · Diseño: `/negocio/wiener-kingdom/diseno/`.

## Ronda 4 — Revisión 3 (prompt maestro final): G0–G7

- **G0/F13**: upstream/main (`98fc9f6`) fusionado en la rama del PR (merge `d26f4360`);
  CI postgres inspeccionado y corregido (F01–F04).
- **F05–F12** corregidos con pruebas (ver `docs/09_CIERRE_FINAL.md`): comparador alineado,
  visibilidad coherente, contraste con par validado, vista previa de borrador, versiones
  inmutables con hash, claims de entrega/devolución endurecidos, editor de filas fit,
  evidencias móvil/movimiento/componentes.
- **G2 dominio**: `offer_type` físico/digital/servicio + `DigitalAsset/Grant`,
  `ServiceSlot/Booking`; `mercado-demo` con 6 categorías físicas + digital + servicio;
  envío «ninguno» para carritos no físicos.
- **G3 IA**: contrato de intención `intent-v1` gobierna cada turno; ranking
  `ranking-v1` auditable; dataset de evaluación **202 casos** con 5 runners;
  modo «sin guardar» (efímero, sella historial) en el asesor.
- **G4 pagos/envíos**: `PaymentAttempt/PaymentEvent` con efectos exactamente-una-vez,
  webhook autenticado, conciliación, reembolsos con límites, «2 tiendas 2 pagos»;
  `Shipment/ShipmentEvent` idempotente, parciales, tracking deduplicado; adaptadores
  por contrato (fake sólo-tests, manual operativo); proveedores reales = bloqueo
  externo declarado (credenciales).
- **G5/G6**: `/plataforma/componentes/`, `docs/DIRECCION_VISUAL.md`, `/salud/`,
  `backup_reino` + `restore_check` (restauración verificada en base temporal).
- **Suite final: 493 tests OK** (5 omitidos sólo-Postgres, en CI). Migraciones limpias.
- Evidencia nueva: `docs/capturas/r4_*.jpg` (8 capturas) + `shots4/` en el workspace.
