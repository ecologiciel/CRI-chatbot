"""Schema invariants for the staged durable inbox."""

from app.models.whatsapp_inbox import WhatsAppInboxEvent


def test_inbox_is_tenant_scoped_and_requires_encrypted_payload():
    table = WhatsAppInboxEvent.__table__
    assert table.schema == "public"
    assert not table.c.tenant_id.nullable
    assert not table.c.provider_message_id.nullable
    assert not table.c.ciphertext.nullable
    assert not table.c.key_version.nullable
    assert not {"phone", "message", "payload", "contacts"} & set(table.c.keys())
    index = next(index for index in table.indexes if index.name == "uq_wa_inbox_tenant_message")
    assert index.unique
    assert [column.name for column in index.columns] == ["tenant_id", "provider_message_id"]
    fk = next(iter(table.c.tenant_id.foreign_keys))
    assert fk.ondelete == "CASCADE"
