from django.urls import path
from . import views_shipping

urlpatterns = [
    path('negocio/<slug:slug>/pedidos/<uuid:public_id>/envios/', views_shipping.shipments, name='reino_merchant_shipments'),
    path('negocio/<slug:slug>/pedidos/<uuid:public_id>/envios/crear/', views_shipping.shipment_create, name='reino_merchant_shipment_create'),
    path('negocio/<slug:slug>/pedidos/<uuid:public_id>/envios/<uuid:shipment_id>/', views_shipping.shipment_update, name='reino_merchant_shipment_update'),
]
