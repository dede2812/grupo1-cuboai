"""Adaptador FAKE: exclusivamente para tests locales (§11.3).

Simula el CONTRATO (crear → requires_action → capturar/fallar por referencia
determinista). No es un proveedor y NUNCA se ofrece al comprador: las vistas
sólo muestran métodos con `configured=True` de su cuenta.
"""

from .base import AdapterResponse, PaymentAdapter


class FakeAdapter(PaymentAdapter):
    key = "fake"
    label = "Simulador de pruebas (NO producción)"

    def capabilities(self, account=None):
        return {"create": True, "capture": True, "refund": True, "webhook": True,
                "hosted": True, "configured": True, "simulated": True}

    def validate_configuration(self, account):
        return AdapterResponse(ok=True, provider=self.key, state="ready")

    def create_payment(self, attempt):
        return AdapterResponse(
            ok=True, provider=self.key, state="requires_action",
            external_ref=f"fake-{attempt.public_id}",
            redirect_url=f"/pagos/fake/{attempt.public_id}/",
            currency=attempt.currency, amount=str(attempt.amount),
        )

    def get_payment(self, attempt):
        return AdapterResponse(ok=True, provider=self.key,
                               state=attempt.state,
                               external_ref=attempt.external_ref,
                               currency=attempt.currency, amount=str(attempt.amount))

    def verify_notification(self, headers, raw_body):
        return headers.get("X-Fake-Signature") == "firma-de-prueba"

    def capture(self, attempt):
        return AdapterResponse(ok=True, provider=self.key, state="captured",
                               external_ref=attempt.external_ref,
                               currency=attempt.currency, amount=str(attempt.amount))

    def refund(self, attempt, amount=None, note=""):
        return AdapterResponse(ok=True, provider=self.key, state="refunded",
                               external_ref=attempt.external_ref,
                               amount=str(amount or attempt.amount))
