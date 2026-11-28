"""Verify canonical phone indexes introduced by the earlier production migration.

Revision ID: 0023
Revises: 0022

This deliberately fails on existing duplicates or missing indexes; it never
selects a winner or merges contacts and their consent.
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    reference = bind.execute(sa.text(
        "SELECT pg_get_expr(i.indexprs,i.indrelid), pg_get_expr(i.indpred,i.indrelid) "
        "FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='tenant_template' AND c.relname='uq_contacts_canonical_phone' "
        "AND i.indisunique AND i.indisvalid"
    )).one_or_none()
    if reference is None:
        raise RuntimeError("Canonical phone index is missing or invalid on tenant template")
    names = bind.execute(sa.text(
        "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'tenant\\_%' ESCAPE '\\' ORDER BY nspname"
    )).scalars().all()
    if "tenant_template" not in names:
        raise RuntimeError("Missing tenant template")
    for name in names:
        if not re.fullmatch(r"tenant_[a-z][a-z0-9_]{0,49}", name):
            raise RuntimeError("Unsupported tenant schema name")
        schema = bind.dialect.identifier_preparer.quote(name)
        # Lock before preflight so a concurrent contact insert cannot slip in
        # between duplicate detection and unique index creation.
        op.execute(f"LOCK TABLE {schema}.contacts IN ACCESS EXCLUSIVE MODE")
        duplicates = bind.execute(sa.text(
            f"SELECT EXISTS (SELECT 1 FROM {schema}.contacts "
            "WHERE phone ~ '^[+]?[1-9][0-9]{6,14}$' "
            "GROUP BY ltrim(phone, '+') HAVING count(*) > 1)"
        )).scalar_one()
        if duplicates:
            raise RuntimeError("Duplicate international contacts require reconciliation before migration")
        equivalent = bind.execute(sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_index i "
            "JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
            "WHERE n.nspname=:name AND t.relname='contacts' AND i.indisunique AND i.indisvalid "
            "AND pg_get_expr(i.indexprs,i.indrelid)=:expr "
            "AND pg_get_expr(i.indpred,i.indrelid)=:predicate)"
        ), {"name": name, "expr": reference[0], "predicate": reference[1]}).scalar_one()
        if not equivalent:
            raise RuntimeError("Canonical phone index is missing or invalid on a tenant")


def downgrade() -> None:
    # New institutions inherit the index under PostgreSQL-generated names;
    # a generic downgrade cannot safely remove every copy or preserve the
    # consent invariant. Restore a verified backup instead.
    raise RuntimeError("Contact identity protection cannot be downgraded automatically")
