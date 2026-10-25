"""Royal Passport: perfiles, medidas, consentimiento y borrado de memoria.

Reglas (S10/§12):
- El consentimiento no viene premarcado; navegar o pagar no equivale a autorizar.
- Retirar consentimiento impide reutilizar los datos y elimina derivados.
- Dos perros no comparten datos por coincidencia de nombre: selección por ID.
"""

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import Consent, Measurement, MemorySummary, Preference, RecipientProfile


def get_profile(store, session_key, public_id):
    """Perfil por ID validado contra tienda y propietario (fail-closed)."""
    try:
        return RecipientProfile.objects.filter(
            store=store, session_key=session_key, public_id=public_id
        ).first()
    except (ValidationError, ValueError, TypeError):
        return None


def list_profiles(store, session_key):
    return list(RecipientProfile.objects.filter(store=store, session_key=session_key))


def create_profile(store, session_key, alias, kind="dog", breed="", photo_path=""):
    return RecipientProfile.objects.create(
        store=store, session_key=session_key, alias=alias.strip()[:80] or "Sin nombre",
        kind=kind, breed=breed.strip()[:80], photo_path=photo_path,
    )


def latest_measurement(profile):
    """Crudo: NO usar directamente en IA/recomendador (R07). Ver
    authorized_measurement() para lecturas con finalidad verificada."""
    return profile.measurements.first()


def authorized_measurement(store, session_key, profile):
    """Única lectura autorizada de medidas persistentes (R07).

    Verifica tienda, titular, perfil, finalidad (MEASUREMENTS) y estado
    vigente del consentimiento. Tras revocar, devuelve None: ninguna
    herramienta, recomendador ni contexto del modelo puede reutilizarlas.
    """
    if profile is None:
        return None
    if not has_consent(store, session_key, Consent.Purpose.MEASUREMENTS, profile):
        return None
    return profile.measurements.first()


def save_measurement(profile, chest_cm=None, neck_cm=None, back_cm=None, original=None,
                     source="owner"):
    """Medidas nuevas versionan las anteriores (historial conservado)."""
    return Measurement.objects.create(
        profile=profile, chest_cm=chest_cm, neck_cm=neck_cm, back_cm=back_cm,
        original=original or {}, source=source,
    )


def has_consent(store, session_key, purpose, profile=None):
    if profile is not None and (profile.store_id != store.pk or profile.session_key != session_key):
        return False
    qs = Consent.objects.filter(store=store, session_key=session_key, purpose=purpose)
    if profile is not None:
        specific = qs.filter(profile=profile).order_by("-granted_at", "-pk").first()
        if specific:
            return specific.status == Consent.Status.GRANTED
    permission = qs.filter(profile__isnull=True).order_by("-granted_at", "-pk").first()
    return permission is not None and permission.status == Consent.Status.GRANTED


def grant_consent(store, session_key, purpose, profile=None, version="v1"):
    """Registra permiso explícito (clic del usuario, nunca del modelo)."""
    consent, _ = Consent.objects.update_or_create(
        store=store, session_key=session_key, purpose=purpose, profile=profile,
        defaults={"status": Consent.Status.GRANTED, "version": version, "revoked_at": None},
    )
    return consent


def revoke_consent(store, session_key, purpose, profile=None):
    """Revoca un consentimiento y ejecuta su efecto completo (§8.3, N08).

    Además de cerrar el permiso y borrar sus derivados, SELLA el historial de
    la conversación: los mensajes anteriores dejan de ser elegibles para el
    proveedor (el historial visible del cliente se conserva). No se intenta
    un borrado selectivo por expresión regular: se excluye el historial
    afectado completo.
    """
    if profile is not None and (profile.store_id != store.pk or profile.session_key != session_key):
        return 0
    previously_authorized = has_consent(store, session_key, purpose, profile)
    qs = Consent.objects.filter(
        store=store, session_key=session_key, purpose=purpose, status=Consent.Status.GRANTED
    )
    if profile is not None:
        qs = qs.filter(profile=profile)
    n = 0
    for consent in qs:
        consent.status = Consent.Status.REVOKED
        consent.revoked_at = timezone.now()
        consent.save(update_fields=["status", "revoked_at"])
        # Los derivados de ese permiso dejan de existir.
        Preference.objects.filter(consent=consent).delete()
        n += 1
    if profile is not None and previously_authorized and not n:
        Consent.objects.update_or_create(store=store, session_key=session_key, purpose=purpose, profile=profile,
                                         defaults={"status": Consent.Status.REVOKED, "revoked_at": timezone.now()})
        profile.preferences.filter(consent__purpose=purpose).delete()
        n = 1
    if n:
        # Sellar el historial de ESTA conversación (tienda+sesión): los datos
        # revocados no se reenvían al modelo en ningún turno futuro.
        from .models import AIConversation
        now = timezone.now()
        AIConversation.objects.filter(store=store, session_key=session_key).update(
            history_sealed_before=now)
    return n


def save_preference(profile, consent, key, value, source="explicit"):
    if (consent.store_id != profile.store_id or consent.session_key != profile.session_key
            or consent.profile_id not in (None, profile.pk) or consent.status != Consent.Status.GRANTED
            or consent.purpose != Consent.Purpose.PREFERENCES):
        raise ValueError("La preferencia requiere consentimiento vigente del titular.")
    pref, _ = Preference.objects.update_or_create(
        profile=profile, key=key[:40],
        defaults={"value": str(value)[:120], "source": source, "consent": consent},
    )
    return pref


def authorized_preferences(profile, store, session_key):
    """Solo preferencias con consentimiento vigente (A14)."""
    if profile is None or not has_consent(store, session_key, Consent.Purpose.PREFERENCES, profile):
        return {}
    return {p.key: p.value for p in profile.preferences.filter(
        consent__store=store, consent__session_key=session_key,
        consent__purpose=Consent.Purpose.PREFERENCES, consent__status=Consent.Status.GRANTED,
    ).filter(Q(consent__profile=profile) | Q(consent__profile__isnull=True))}


def delete_profile_memory(store, session_key, profile):
    """Borra TODA la memoria del perfil (R07): medidas, preferencias,
    resúmenes, foto, consentimientos y recuerdos de conversación de la sesión.

    No toca pedidos (otra base de conservación: conservan solo lo necesario
    para su propia finalidad) ni documentos públicos de la tienda.
    """
    from .models import AIConversation
    if profile.store_id != store.pk or profile.session_key != session_key:
        return False
    profile.measurements.all().delete()
    profile.preferences.all().delete()
    profile.memory_summaries.all().delete()
    profile.consents.update(status=Consent.Status.REVOKED, revoked_at=timezone.now())
    AIConversation.objects.filter(store=store, session_key=session_key).delete()
    profile.photo_path = ""
    profile.save(update_fields=["photo_path"])
    return True


def consent_state(store, session_key, profile=None):
    """Estado visible de permisos para la pantalla de privacidad."""
    qs = Consent.objects.filter(store=store, session_key=session_key)
    if profile is not None:
        qs = qs.filter(Q(profile=profile) | Q(profile__isnull=True))
    state = {}
    for purpose, label in Consent.Purpose.choices:
        c = qs.filter(purpose=purpose).order_by("-granted_at").first()
        state[purpose] = {
            "label": label,
            "status": c.status if c else "none",
            "granted_at": c.granted_at if c else None,
            "version": c.version if c else None,
        }
    return state
