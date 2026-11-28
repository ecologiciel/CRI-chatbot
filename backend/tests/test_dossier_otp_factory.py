"""The staged tracking implementation must use the atomic OTP primitive."""
from app.services.dossier import otp
from app.services.dossier.otp_atomic import AtomicDossierOTPService


def test_tracking_factory_selects_atomic_otp(monkeypatch):
    monkeypatch.setattr(otp, "_dossier_otp_service", None)
    first = otp.get_dossier_otp_service()
    assert isinstance(first, AtomicDossierOTPService)
    assert otp.get_dossier_otp_service() is first
