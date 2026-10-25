"""Keep legacy English contracts while the marketplace speaks Spanish."""
from django.utils import translation


class StoreLocaleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        spanish = request.path.startswith(("/s/", "/negocio/", "/cuenta/", "/plataforma/",
            "/tiendas/", "/buscar/", "/explorar/", "/comparar/", "/para-negocios/", "/pagos/"))
        with translation.override("es-sv" if spanish else "en-us"):
            return self.get_response(request)
