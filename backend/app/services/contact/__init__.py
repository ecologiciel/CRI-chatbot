"""Contact service — auto-create, CRM CRUD, segmentation, and import/export."""

from app.services.contact.segmentation import SegmentationService, get_segmentation_service
from app.services.contact.service import ContactService, get_contact_service

__all__ = [
    "ContactService",
    "SegmentationService",
    "get_contact_service",
    "get_segmentation_service",
]
