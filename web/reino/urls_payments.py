from django.urls import path
from . import views_payments as views

urlpatterns = [
    path('s/<slug:slug>/pedido/<uuid:public_id>/pagar/<str:provider>/', views.payment_start, name='reino_payment_start'),
    path('s/<slug:slug>/pedido/<uuid:public_id>/pago/<uuid:attempt_id>/consultar/', views.payment_refresh, name='reino_payment_refresh'),
    path('pagos/retorno/<str:provider>/', views.payment_return, name='reino_payment_return'),
]
