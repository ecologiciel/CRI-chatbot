"""New demo identifiers must work in database schemas and object buckets."""

import pytest
from pydantic import ValidationError

from app.schemas.tenant import TenantCreate


@pytest.mark.parametrize("slug", ["prospect1", "onssa", "institution2026"])
def test_safe_demo_slug(slug):
    data = TenantCreate(name="Institution", region="National", slug=slug)
    assert data.slug == slug


@pytest.mark.parametrize("slug", ["prospect-test", "prospect_test", "template", "a;drop"])
def test_unsafe_or_reserved_demo_slug_rejected(slug):
    with pytest.raises(ValidationError):
        TenantCreate(name="Institution", region="National", slug=slug)
