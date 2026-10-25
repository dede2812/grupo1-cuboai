from django.urls import path
from django.contrib.auth import views as auth_views

from . import panel, views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("productos/", views.productos, name="productos"),
    path("producto/<str:producto>/", views.detalle, name="detalle"),
    path("smart-fit/", views.smart_fit, name="smart_fit"),
    path("guide/", views.assistant, name="assistant"),
    path("smart-fit/<uuid:public_id>/", views.smart_fit_resultado, name="smart_fit_resultado"),
    path("smart-fit/<uuid:public_id>/editar/", views.smart_fit_editar, name="smart_fit_editar"),
    path("smart-fit/<uuid:public_id>/cotizar/", views.smart_quote_crear, name="smart_quote_crear"),
    path("quote/<uuid:public_id>/", views.smart_quote, name="smart_quote"),
    path("quote/<uuid:public_id>/cantidad/", views.smart_quote_cantidad, name="smart_quote_cantidad"),
    path("quote/<uuid:public_id>/checkout/", views.checkout, name="checkout"),
    path("cart/", views.cart_view, name="cart"),
    path("cart/add/", views.cart_add, name="cart_add"),
    path("cart/checkout/", views.cart_checkout, name="cart_checkout"),
    path("cart/line/<uuid:public_id>/", views.cart_line_update, name="cart_line_update"),
    path("cart/line/<uuid:public_id>/remove/", views.cart_line_remove, name="cart_line_remove"),
    path("quote/<uuid:public_id>/to-cart/", views.quote_to_cart, name="quote_to_cart"),
    path("order/<uuid:public_id>/", views.order_detail, name="order_detail"),
    path(
        "panel/login/",
        panel.PanelLoginView.as_view(template_name="tienda/panel_login.html"),
        name="panel_login",
    ),
    path("panel/logout/", auth_views.LogoutView.as_view(), name="panel_logout"),
    path("panel/", panel.orders, name="panel_orders"),
    path("panel/orders/<uuid:public_id>/", panel.order, name="panel_order"),
    path("panel/orders/<uuid:public_id>/sheet/", panel.order_sheet, name="panel_order_sheet"),
    path("panel/payments/", panel.payments, name="panel_payments"),
    path("panel/measurements/", panel.measurements, name="panel_measurements"),
    path("panel/costs/", panel.costs, name="panel_costs"),
    path("panel/costs/<slug:slug>/", panel.product_cost, name="panel_product_cost"),
]
