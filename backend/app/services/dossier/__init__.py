"""Dossier tracking services — consultation, anti-BOLA, OTP authentication, import."""

from app.services.dossier.service import DossierService, get_dossier_service

__all__ = ["DossierService", "get_dossier_service"]

# Import service (Wave 23B)
try:
    from app.services.dossier.import_service import (
        DossierImportService,
        get_dossier_import_service,
    )

    __all__ += ["DossierImportService", "get_dossier_import_service"]
except ImportError:
    pass

# OTP service may be added by a parallel wave
try:
    from app.services.dossier.otp import DossierOTPService, get_dossier_otp_service

    __all__ += ["DossierOTPService", "get_dossier_otp_service"]
except ImportError:
    pass
