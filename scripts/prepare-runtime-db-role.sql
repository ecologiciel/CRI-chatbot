-- EXPERIMENTAL: run only against an isolated rehearsal database.
-- The login and password are provisioned separately. Do not grant this role
-- to a production login until tenant lifecycle, migrations, rollback, all
-- workers and effective privileges have been verified.
\set ON_ERROR_STOP on
BEGIN;

DO $$
BEGIN
  IF current_database() !~ '^ragtest_[a-z0-9_]+$' THEN
    RAISE EXCEPTION 'Runtime role rehearsal requires a disposable ragtest_ database';
  END IF;
END $$;

CREATE ROLE cri_runtime_access NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

-- A PUBLIC grant would bypass the audit table's role-specific restrictions.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_class c
    CROSS JOIN LATERAL aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
    WHERE c.oid = 'public.audit_logs'::regclass AND a.grantee = 0
      AND a.privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE', 'TRIGGER', 'REFERENCES')
  ) THEN
    RAISE EXCEPTION 'Audit table grants unsafe privileges to PUBLIC';
  END IF;
  EXECUTE format('GRANT CONNECT, CREATE, TEMPORARY ON DATABASE %I TO cri_runtime_access', current_database());
END $$;

GRANT USAGE ON SCHEMA public TO cri_runtime_access;
-- Apply the same explicit table and sequence policy atomically at creation.
\ir rehearse-refresh-runtime-grants.sql

-- Future migration objects require reviewed explicit grants. Default table
-- privileges are intentionally not widened: a replacement audit table must
-- never silently inherit UPDATE or DELETE access.
COMMIT;
