"""Rutas de la plataforma Reino Commerce (mapa de pantallas §5).

- "" redirige a /tiendas/ (directorio P01); la home histórica de Weiner
  Kingdom queda preservada en /legacy/ (redirección documentada).
- /s/<slug>/... namespacing por tienda (S01–S12).
- /cuenta/ Royal Passport (S10), /para-negocios/ (M01), /negocio/<slug>/ (M03+),
  /plataforma/ (P02 mínimo).
"""

from django.urls import include, path

from . import (
    views_account, views_design, views_explore, views_health, views_looklab, views_merchant,
    views_payments, views_platform, views_storefront, views_stylist,
)

urlpatterns = [
    path("", include("reino.urls_shipping")),
    path("", include("reino.urls_auth")),
    path("salud/", views_health.health, name="reino_health"),
    path("pagos/webhook/<str:provider>/", views_payments.payment_webhook,
         name="reino_payment_webhook"),
    # NOTA: "/" la sirve la app histórica `tienda` (home preservada, tests en verde).
    # La plataforma nueva vive en /tiendas/ y /s/<slug>/ (redirección documentada en docs/01).
    # Plataforma: descubrimiento, búsqueda y comparación (P01/P04/P06, §11).
    path("explorar/", views_explore.explore, name="reino_explore"),
    path("buscar/", views_explore.search, name="reino_search"),
    path("comparar/", views_explore.compare, name="reino_compare"),
    path("comparar/agregar/", views_explore.compare_add, name="reino_compare_add"),
    path("comparar/quitar/", views_explore.compare_remove, name="reino_compare_remove"),
    path("tiendas/", views_platform.directory, name="reino_directory"),
    path("para-negocios/", views_platform.for_business, name="reino_for_business"),
    path("plataforma/", views_platform.platform_admin, name="reino_platform"),
    path("plataforma/componentes/", views_platform.components_showcase,
         name="reino_componentes"),
    path("plataforma/alta/", views_platform.merchant_onboard, name="reino_platform_onboard"),
    path("plataforma/tienda/<slug:slug>/activar/", views_platform.store_activate,
         name="reino_platform_activate"),

    # S01–S12 · tienda
    path("s/<slug:slug>/", views_storefront.store_home, name="reino_store_home"),
    path("s/<slug:slug>/coleccion/", views_storefront.collection, name="reino_collection"),
    path("s/<slug:slug>/producto/<slug:product_slug>/", views_storefront.product_detail, name="reino_product"),
    path("s/<slug:slug>/tallas/", views_storefront.smart_fit, name="reino_fit"),
    path("s/<slug:slug>/looklab/", views_looklab.looklab, name="reino_looklab"),
    path("s/<slug:slug>/looklab/agregar/", views_looklab.looklab_add, name="reino_looklab_add"),
    path("s/<slug:slug>/looklab/guardar/", views_looklab.looklab_save, name="reino_looklab_save"),
    path("s/<slug:slug>/asesor/", views_stylist.stylist, name="reino_stylist"),
    path("s/<slug:slug>/asesor/mensaje/", views_stylist.stylist_message, name="reino_stylist_message"),
    path("s/<slug:slug>/asesor/accion/", views_stylist.stylist_confirm_action,
         name="reino_stylist_action"),
    path("s/<slug:slug>/asesor/sin-guardar/", views_stylist.stylist_memory_mode,
         name="reino_stylist_memory"),
    path("s/<slug:slug>/carrito/", views_storefront.cart_view, name="reino_cart"),
    path("s/<slug:slug>/descargar/<uuid:token>/", views_storefront.digital_download,
         name="reino_digital_download"),
    path("s/<slug:slug>/carrito/agregar/", views_storefront.cart_add, name="reino_cart_add"),
    path("s/<slug:slug>/carrito/linea/<int:item_id>/", views_storefront.cart_update, name="reino_cart_update"),
    path("s/<slug:slug>/carrito/linea/<int:item_id>/quitar/", views_storefront.cart_remove, name="reino_cart_remove"),
    path("s/<slug:slug>/checkout/", views_storefront.checkout, name="reino_checkout"),
    path("s/<slug:slug>/pedido/<uuid:public_id>/", views_storefront.order_detail, name="reino_order"),
    path("s/<slug:slug>/pedido/<uuid:public_id>/<uuid:token>/", views_storefront.order_detail, name="reino_order_guest"),
    path("s/<slug:slug>/ayuda/", views_storefront.help_center, name="reino_help"),

    # S10 · cuenta / Royal Passport
    path("cuenta/", views_account.account_home, name="reino_account"),
    path("cuenta/perfiles/<uuid:public_id>/preferencias/", views_account.profile_preferences, name="reino_profile_preferences"),
    path("cuenta/perfiles/nuevo/", views_account.profile_create, name="reino_profile_create"),
    path("cuenta/perfiles/<uuid:public_id>/medidas/", views_account.profile_measurements, name="reino_profile_measure"),
    path("cuenta/perfiles/<uuid:public_id>/activar/", views_account.profile_activate, name="reino_profile_activate"),
    path("cuenta/perfiles/<uuid:public_id>/memoria/borrar/", views_account.profile_memory_delete, name="reino_profile_memory_delete"),
    path("cuenta/consentimiento/", views_account.consent_update, name="reino_consent"),
    path("cuenta/looks/", views_account.looks, name="reino_looks"),

    # M01–M10 · panel del comerciante
    path("negocio/<slug:slug>/", views_merchant.dashboard, name="reino_merchant"),
    path("negocio/<slug:slug>/catalogo/", views_merchant.catalog, name="reino_merchant_catalog"),
    path("negocio/<slug:slug>/catalogo/nuevo/", views_merchant.product_new,
         name="reino_merchant_product_new"),
    path("negocio/<slug:slug>/catalogo/<int:pk>/", views_merchant.product_edit,
         name="reino_merchant_product_edit"),
    path("negocio/<slug:slug>/catalogo/<int:pk>/variante/", views_merchant.variant_new,
         name="reino_merchant_variant_new"),
    path("negocio/<slug:slug>/catalogo/<int:pk>/tabla-tallas/", views_merchant.fit_rule_new,
         name="reino_merchant_fit_rule"),
    path("negocio/<slug:slug>/catalogo/<int:pk>/media/", views_merchant.product_media_add,
         name="reino_merchant_product_media"),
    path("negocio/<slug:slug>/variante/<int:pk>/stock/", views_merchant.variant_stock,
         name="reino_merchant_variant_stock"),
    path("negocio/<slug:slug>/variante/<int:pk>/activar/", views_merchant.variant_toggle,
         name="reino_merchant_variant_toggle"),
    path("negocio/<slug:slug>/pedidos/", views_merchant.orders, name="reino_merchant_orders"),
    path("negocio/<slug:slug>/pedidos/<uuid:public_id>/", views_merchant.order_detail, name="reino_merchant_order"),
    path("negocio/<slug:slug>/pedidos/<uuid:public_id>/transicion/", views_merchant.order_transition, name="reino_merchant_order_transition"),
    path("negocio/<slug:slug>/clientes/", views_merchant.customers, name="reino_merchant_customers"),
    path("negocio/<slug:slug>/finanzas/", views_merchant.finance, name="reino_merchant_finance"),
    path("negocio/<slug:slug>/logistica/", views_merchant.logistics, name="reino_merchant_logistics"),
    path("negocio/<slug:slug>/configuracion/", views_merchant.settings_view, name="reino_merchant_settings"),
    path("negocio/<slug:slug>/configuracion/tienda/", views_merchant.settings_store,
         name="reino_merchant_settings_store"),
    path("negocio/<slug:slug>/configuracion/zonas/", views_merchant.zone_save,
         name="reino_merchant_zone_save"),
    path("negocio/<slug:slug>/configuracion/politicas/", views_merchant.policy_save,
         name="reino_merchant_policy_save"),
    path("negocio/<slug:slug>/configuracion/equipo/", views_merchant.team_save,
         name="reino_merchant_team_save"),
    path("negocio/<slug:slug>/configuracion/equipo/<int:member_id>/quitar/",
         views_merchant.team_remove, name="reino_merchant_team_remove"),

    # Estudio de diseño + medios + pruebas de integración (§13/§14, AC11/12/25)
    path("negocio/<slug:slug>/diseno/", views_design.design_studio,
         name="reino_merchant_diseno"),
    path("negocio/<slug:slug>/diseno/guardar/", views_design.design_save,
         name="reino_merchant_diseno_save"),
    path("negocio/<slug:slug>/diseno/previsualizar/", views_design.design_preview,
         name="reino_merchant_diseno_preview"),
    path("negocio/<slug:slug>/diseno/publicar/", views_design.design_publish,
         name="reino_merchant_diseno_publish"),
    path("negocio/<slug:slug>/diseno/modulo/mover/", views_design.design_module_move,
         name="reino_merchant_diseno_move"),
    path("negocio/<slug:slug>/diseno/media/<int:asset_id>/asignar/", views_design.media_assign,
         name="reino_merchant_media_assign"),
    path("negocio/<slug:slug>/diseno/restaurar/<int:version>/",
         views_design.design_restore, name="reino_merchant_diseno_restore"),
    path("negocio/<slug:slug>/medios/subir/", views_design.media_upload,
         name="reino_merchant_media_upload"),
    path("negocio/<slug:slug>/integraciones/<slug:key>/probar/",
         views_design.integration_probe, name="reino_merchant_probe"),
]
