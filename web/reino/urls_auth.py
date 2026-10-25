from django.urls import path
from . import views_auth

urlpatterns = [
    path("cuenta/registro/", views_auth.register, name="reino_register"),
    path("cuenta/ingresar/", views_auth.sign_in, name="reino_login"),
    path("cuenta/salir/", views_auth.sign_out, name="reino_logout"),
    path("cuenta/contrasena/", views_auth.password_change, name="reino_password_change"),
]
