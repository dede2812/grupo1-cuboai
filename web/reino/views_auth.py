"""Customer authentication; Django auth remains the only source of roles."""
import hashlib
from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.db import DatabaseError, transaction
from django.db.models import F
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from . import services_identity, tenancy
from .models import AIUsageCounter, CustomerIdentity


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(label="Correo electrónico", max_length=254)
    keep_guest_data = forms.BooleanField(label="Guardar el carrito, los perfiles y los looks de esta visita en mi cuenta", required=False)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "email")


class CustomerLoginForm(AuthenticationForm):
    keep_guest_data = forms.BooleanField(label="Importar el carrito, los perfiles y los looks de esta visita", required=False)


def safe_next(request, default="reino_account"):
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return reverse(default)


def _allow_attempt(request, purpose, limit):
    # Fixed-window database quota shared across workers; never log credentials.
    now = timezone.now()
    digest = hashlib.sha256((request.META.get("REMOTE_ADDR", "") + ":" + purpose).encode()).hexdigest()
    key = f"auth:{digest}:{int(now.timestamp()) // 900}"
    try:
        with transaction.atomic():
            counter, _ = AIUsageCounter.objects.get_or_create(
                key=key, defaults={"expires_at": now + timedelta(minutes=16)})
            return bool(AIUsageCounter.objects.filter(pk=counter.pk, count__lt=limit).update(count=F("count") + 1))
    except DatabaseError:
        return False


def _finish_login(request, user, guest_key, keep_guest_data):
    if keep_guest_data:
        services_identity.import_guest_data(guest_key, user)
    login(request, user)
    CustomerIdentity.objects.get_or_create(user=user)
    # Browser-only drafts and confirmation IDs never cross an auth boundary.
    for key in list(request.session.keys()):
        if key.startswith("reino_") and (not keep_guest_data or key != tenancy.SESSION_PROFILE):
            request.session.pop(key, None)
    request.session["reino_flash"] = "Ya ingresaste a tu cuenta."


@sensitive_post_parameters("password1", "password2")
def register(request):
    if request.user.is_authenticated:
        return redirect("reino_account")
    tenancy.ensure_session(request)
    form = RegistrationForm(request.POST or None)
    if request.method == "POST":
        if not _allow_attempt(request, "register", 8):
            form.add_error(None, "Alcanzaste el límite de intentos. Volvé a probar en 15 minutos.")
        elif form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
                    _finish_login(request, user, request.session.session_key, form.cleaned_data["keep_guest_data"])
                return redirect(safe_next(request))
            except services_identity.IdentityImportError as exc:
                form.add_error(None, str(exc))
    return render(request, "reino/auth/register.html", {"form": form, "next": safe_next(request)})


@sensitive_post_parameters("password")
def sign_in(request):
    if request.user.is_authenticated:
        return redirect("reino_account")
    tenancy.ensure_session(request)
    form = CustomerLoginForm(request, data=request.POST or None)
    if request.method == "POST":
        if not _allow_attempt(request, "login", 20):
            form.add_error(None, "Alcanzaste el límite de intentos. Volvé a probar en 15 minutos.")
        elif form.is_valid():
            try:
                _finish_login(request, form.get_user(), request.session.session_key, form.cleaned_data["keep_guest_data"])
                return redirect(safe_next(request))
            except services_identity.IdentityImportError as exc:
                form.add_error(None, str(exc))
    return render(request, "reino/auth/login.html", {"form": form, "next": safe_next(request)})


@require_POST
def sign_out(request):
    logout(request)
    return redirect("reino_account")


@login_required(login_url="reino_login")
@sensitive_post_parameters("old_password", "new_password1", "new_password2")
def password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        request.session["reino_flash"] = "Contraseña actualizada."
        return redirect("reino_account")
    return render(request, "reino/auth/password_change.html", {"form": form})
