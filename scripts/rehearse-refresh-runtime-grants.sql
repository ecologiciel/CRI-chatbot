-- EXPERIMENTAL: refresh grants only in a disposable rehearsal database.
-- A production migration must not reuse this script without review.
\set ON_ERROR_STOP on
BEGIN;
DO $$
DECLARE item record;
BEGIN
  IF current_database() !~ '^ragtest_[a-z0-9_]+$' THEN
    RAISE EXCEPTION 'Grant refresh requires a disposable ragtest_ database';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname='cri_runtime_access' AND NOT rolcanlogin
      AND NOT rolsuper AND NOT rolcreaterole AND NOT rolcreatedb
      AND NOT rolreplication AND NOT rolbypassrls
  ) THEN
    RAISE EXCEPTION 'Restricted runtime group is missing or unsafe';
  END IF;
  -- Grant the same DML as the initial rehearsal, excluding protected tables
  -- from the outset; no transaction window grants them write privileges.
  FOR item IN
    SELECT c.oid::regclass AS relation
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')
      AND c.relname NOT IN ('audit_logs','alembic_version')
  LOOP
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES ON TABLE %s TO cri_runtime_access', item.relation);
  END LOOP;
  GRANT SELECT, INSERT ON public.audit_logs TO cri_runtime_access;
  REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.audit_logs FROM cri_runtime_access;
  GRANT SELECT ON public.alembic_version TO cri_runtime_access;
  REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.alembic_version FROM cri_runtime_access;
  GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cri_runtime_access;
  FOR item IN SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_[a-z0-9_]+$' LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO cri_runtime_access', item.nspname);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES ON ALL TABLES IN SCHEMA %I TO cri_runtime_access', item.nspname);
    EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO cri_runtime_access', item.nspname);
  END LOOP;
END $$;
COMMIT;
