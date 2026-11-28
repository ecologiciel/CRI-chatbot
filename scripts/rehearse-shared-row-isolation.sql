-- EXPERIMENTAL. Isolated ragtest_ databases only. This is not a production
-- migration and does not protect other shared tables or tenant schemas.
\set ON_ERROR_STOP on
BEGIN;
DO $$
DECLARE rel text;
BEGIN
  IF current_database() !~ '^ragtest_[a-z0-9_]+$' THEN
    RAISE EXCEPTION 'Row isolation rehearsal requires a disposable ragtest_ database';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='cri_rls_fixture')
     OR to_regnamespace('rls_rehearsal') IS NOT NULL THEN
    RAISE EXCEPTION 'Row isolation rehearsal namespace already exists';
  END IF;
  FOREACH rel IN ARRAY ARRAY[
    'agent_reply_outbox_events', 'whatsapp_inbox_events', 'whatsapp_status_events'
  ] LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      JOIN pg_attribute a ON a.attrelid=c.oid
      WHERE n.nspname='public' AND c.relname=rel AND c.relkind IN ('r','p')
        AND NOT c.relrowsecurity AND NOT c.relforcerowsecurity
        AND a.attname='tenant_id' AND a.atttypid='uuid'::regtype AND a.attnotnull
        AND NOT a.attisdropped
        AND NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid=c.oid)
    ) THEN
      RAISE EXCEPTION 'Shared table or existing row policy requires review: %', rel;
    END IF;
  END LOOP;
END $$;

CREATE ROLE cri_rls_fixture NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE SCHEMA rls_rehearsal;
REVOKE ALL ON SCHEMA rls_rehearsal FROM PUBLIC;
CREATE TABLE rls_rehearsal.login_tenants (
  login_name name PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE
);
REVOKE ALL ON rls_rehearsal.login_tenants FROM PUBLIC, cri_rls_fixture;
CREATE FUNCTION rls_rehearsal.current_tenant() RETURNS uuid
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp
  AS 'SELECT tenant_id FROM rls_rehearsal.login_tenants WHERE login_name = session_user::pg_catalog.name';
REVOKE ALL ON FUNCTION rls_rehearsal.current_tenant() FROM PUBLIC;
GRANT USAGE ON SCHEMA rls_rehearsal TO cri_rls_fixture;
GRANT EXECUTE ON FUNCTION rls_rehearsal.current_tenant() TO cri_rls_fixture;

DO $$
DECLARE rel text;
BEGIN
  FOREACH rel IN ARRAY ARRAY[
    'agent_reply_outbox_events', 'whatsapp_inbox_events', 'whatsapp_status_events'
  ] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', rel);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', rel);
    EXECUTE format(
      'CREATE POLICY tenant_scope ON public.%I TO cri_rls_fixture USING (tenant_id = rls_rehearsal.current_tenant()) WITH CHECK (tenant_id = rls_rehearsal.current_tenant())', rel
    );
  END LOOP;
END $$;
COMMIT;
