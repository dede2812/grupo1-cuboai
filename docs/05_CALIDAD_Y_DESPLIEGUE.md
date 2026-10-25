> Evidencia histórica: los resultados y pendientes de este informe corresponden a su fase y entorno originales. Para la ejecución actual consultar [Pruebas y resultados](12_PRUEBAS_Y_RESULTADOS.md) y [Instalación](11_INSTALACION_Y_DESPLIEGUE.md). No sumar sus conteos a los nuevos.

# 05 · Calidad y despliegue (F9)

## Pruebas ejecutadas (evidencia real, 23-oct-2026, sandbox linux/arm64)

| Suite | Resultado |
|---|---|
| `python manage.py test` (completa) | **372 tests OK** (289 históricos + 83 reino: 14 regresiones de auditoría + 81 casos del dataset + panel) en ~25 s |
| `manage.py check` | 0 issues |
| Migraciones en base vacía + `seed_demo` | OK, reproducible (A30) |
| Recorrido E2E por cliente de pruebas | Home → colección → ficha → LookLab (4 pasos) → revelación → carrito → checkout (revisión) → pedido → seguimiento con token: **OK** |

## Matriz de aceptación §23: cobertura implementada

| ID | Prueba automática | Estado |
|---|---|---|
| A03 | `test_a03_variante_agotada_no_se_recomienda_como_disponible` | ✅ verificado |
| A04 | `test_a04_cm_y_pulgadas_equivalentes` + unidad inválida | ✅ |
| A05 | `test_a05_falta_medida_es_incertidumbre` / `producto_sin_regla` | ✅ |
| A06 | `test_a06_dos_perros_nombres_parecidos` | ✅ |
| A07 | `test_a07_looklab_conserva_borrador_al_volver` | ✅ |
| A08 | `test_a08_presupuesto_estricto_no_se_relaja` | ✅ |
| A09 | Entrega exigida: P0 declara `DELIVERY_UNKNOWN` (diseño) | ✅ comportamiento; test unitario de razón |
| A10 | `test_a10_consulta_natural_usa_herramientas_y_catalogo` (proveedor falso) | ✅ orquestador; **modelo real bloqueado sin clave** |
| A11 | `test_a11_id_inventado_no_se_hidrata` + herramientas prohibidas | ✅ |
| A12 | Documentos como datos sin autoridad (prompt + política de herramientas) | ✅ por diseño + test de política |
| A13 | `test_a13_*` (catálogo, perfiles) | ✅ |
| A14 | `test_a14_revocar_impide_reutilizar` | ✅ |
| A15 | `test_a15_ia_caida_modo_reglas_etiquetado` | ✅ |
| A16 | `test_a16_agregar_ambiguo_no_adivina` / `explicito_ejecuta_una_accion` | ✅ |
| A17 | `test_a17_dos_checkouts_ultima_unidad` + `ConcurrencyTests` (2 hilos) | ✅ SQLite; **re-ejecutar en PostgreSQL** |
| A18 | `test_a18_doble_clic_un_pedido` | ✅ |
| A19–A21 | Webhooks de pasarela | ⛔ bloqueado: sin pasarela (F8) |
| A22 | `test_bitcoin_descuento_15_porciento_pendiente` | ✅ núcleo; cambio de método recalcula (carrito) |
| A23 | Reembolso parcial | P1 (estados listos, acción no construida) |
| A24 | `test_checkout_vencido_no_confirma` (+ legacy quote vencida en suite histórica) | ✅ |
| A25 | `test_a25_pedido_ajeno_no_visible` | ✅ |
| A26 | `test_a26_staff_ajeno_no_entra_al_panel` | ✅ |
| A27 | `test_envio_local_requiere_zona` | ✅ |
| A28 | `test_a28_panel_sin_ventas_no_inventa_porcentajes` | ✅ |
| A29 | `test_a29_coherencia_de_importes` + `test_compra_completa_http` | ✅ |
| A30 | Seed reproducible + suite verde en arranque limpio | ✅ |
| A31 | Borrado + restauración de backup | ⚠️ borrado implementado y probado; **ensayo de restauración pendiente** (operativa) |
| A32 | Editar perfil mientras IA responde | ⚠️ mitigado: cada turno re-lee medidas desde DB; versionado de respuesta pendiente |
| A01–A02 | Responsive 360–1440 px y teclado | ⚠️ revisión manual con capturas (ver STATUS); menú con Escape, foco visible, labels asociadas |

## Accesibilidad (objetivo WCAG 2.2 AA)

Implementado: skip-link, landmarks, labels asociadas, foco visible, Escape cierra menú,
`prefers-reduced-motion`, contraste de la paleta validado por pares (texto navy/tinta sobre
marfil ≥ 7:1; carmín solo con texto claro en botones ≥48 px), formularios con errores
junto al campo y resumen, estados de talla con texto+icono (no solo color).
**Pendiente:** auditoría manual completa de teclado/lector de pantalla (herramienta
automática no certifica por sí sola).

## Rendimiento

CSS propio ~24 KB + JS ~4 KB + 2 familias de fuentes vendoradas (woff2 latin). Imágenes
hero con `fetchpriority=high`; resto `loading="lazy"`. Sin medición Lighthouse en sandbox:
objetivo LCP ≤ 2.5 s / INP ≤ 200 ms / CLS ≤ 0.1 queda para staging (honesto: no medido aquí).

## Seguridad aplicada

CSRF en todos los POST · salida escapada por templates · ORM parametrizado · permisos por
objeto (tienda+sesión/membresía) · secretos por entorno (`.env.example`) · UUID no
secuenciales + token de invitado · sin claves en repo · subida de archivos deshabilitada
en P0 (foto de perfil P1 con validación) · paneles de staff aislados por tenant.

## Operación propuesta del piloto

Staging aislado con PostgreSQL + re-ejecución de A17 · CI con esta suite · backups
automáticos con **ensayo de restauración que reaplique revocaciones** (A31) ·
RPO 24 h / RTO 4 h objetivos a validar (no SLA contratado) · workers para OutboxEvent
(correo transaccional cuando se configure; la UI no promete correo sin sistema).

## Arranque reproducible

```bash
cd web
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # Django 5.2, gunicorn, whitenoise
python manage.py migrate
python manage.py seed_demo               # datos demo controlados (2 tiendas)
python manage.py test                    # 372 tests
python manage.py runserver               # http://127.0.0.1:8000/tiendas/
# Panel: /negocio/wiener-kingdom/ · usuario demo_staff / demo1234 (SOLO demo)
# IA real: export REINO_AI_API_KEY=... (ver .env.example) → asesor en modo "ai"
```
