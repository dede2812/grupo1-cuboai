from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from reino import views_platform

urlpatterns = [
    path("", include("reino.urls_payments")),
    path("", include("reino.urls_business")),
    path("robots.txt", views_platform.robots_txt),
    path("sitemap.xml", views_platform.sitemap_xml),
    # Plataforma Reino Commerce (P0). La ruta "/" la resuelve primero `reino`;
    # todas las demás rutas históricas de `tienda` quedan intactas debajo
    # (Smart Fit, Smart Quote, cotización, carrito legacy, pedido y panel).
    path("", include("reino.urls")),
    path("", include("tienda.urls")),
]

# En desarrollo Django sirve los medios subidos por comerciantes (§18); en
# producción los sirve el servidor/plataforma configurada.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
