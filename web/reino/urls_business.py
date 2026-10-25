from django.urls import path
from . import views_business

urlpatterns = [
    path("negocio/<slug:slug>/estadisticas/", views_business.dashboard, name="reino_business_dashboard"),
    path("negocio/<slug:slug>/estadisticas/exportar/", views_business.export_csv, name="reino_business_export"),
]
