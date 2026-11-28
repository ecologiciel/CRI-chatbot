-- EXPERIMENTAL: refresh grants only in a disposable rehearsal database.
-- A production migration must not reuse this script without review.
\set ON_ERROR_STOP on
DO $$
DECLARE item record;
DECLARE schema_item record;
DECLARE relation_item record;
DECLARE sequence_item record;
DECLARE public_tables text[] := ARRAY[
  'admins', 'tenants', 'tenant_keys', 'whatsapp_inbox_events',
  'whatsapp_status_events', 'agent_reply_outbox_events'
];
DECLARE tenant_tables text[] := ARRAY[
  'contacts', 'kb_documents', 'incentive_categories', 'conversations', 'messages',
  'kb_chunks', 'incentive_items', 'feedback', 'unanswered_questions', 'campaigns',
  'campaign_recipients', 'escalations', 'internal_whitelist', 'dossiers',
  'sync_configs', 'sync_logs', 'dossier_history', 'rag_evaluation_cases',
  'rag_evaluation_runs'
];
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
  IF EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE c.relkind IN ('r','p','v','m','f')
      AND ((n.nspname='public' AND c.relname NOT IN ('audit_logs','alembic_version')
            AND NOT (c.relname = ANY(public_tables)))
        OR (n.nspname ~ '^tenant_[a-z0-9_]+$' AND NOT (c.relname = ANY(tenant_tables))))
  ) THEN
    RAISE EXCEPTION 'Unknown table requires explicit privilege review';
  END IF;
  -- Only reviewed tables receive DML. Unknown tables block the transaction.
  FOR item IN
    SELECT c.oid::regclass AS relation
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')
      AND c.relname = ANY(public_tables)
  LOOP
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES ON TABLE %s TO cri_runtime_access', item.relation);
  END LOOP;
  GRANT SELECT, INSERT ON public.audit_logs TO cri_runtime_access;
  REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.audit_logs FROM cri_runtime_access;
  GRANT SELECT ON public.alembic_version TO cri_runtime_access;
  REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.alembic_version FROM cri_runtime_access;
  FOR schema_item IN SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_[a-z0-9_]+$' LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO cri_runtime_access', schema_item.nspname);
    FOR relation_item IN SELECT c.oid::regclass AS relation FROM pg_class c
      JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname=schema_item.nspname AND c.relkind IN ('r','p','v','m','f')
        AND c.relname = ANY(tenant_tables)
    LOOP
      EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES ON TABLE %s TO cri_runtime_access', relation_item.relation);
    END LOOP;
  END LOOP;
  -- Only sequences owned by reviewed tables are granted. Standalone or new
  -- sequences require review instead of acquiring privileges automatically.
  IF EXISTS (
    SELECT 1 FROM pg_class s JOIN pg_namespace n ON n.oid=s.relnamespace
    WHERE s.relkind='S' AND (n.nspname='public' OR n.nspname ~ '^tenant_[a-z0-9_]+$')
      AND NOT EXISTS (
        SELECT 1 FROM pg_depend d JOIN pg_class t ON t.oid=d.refobjid
        JOIN pg_namespace tn ON tn.oid=t.relnamespace
        WHERE d.classid='pg_class'::regclass AND d.refclassid='pg_class'::regclass
          AND d.objid=s.oid AND d.deptype IN ('a','i') AND tn.oid=n.oid
          AND ((n.nspname='public' AND t.relname = ANY(public_tables || ARRAY['audit_logs']))
            OR (n.nspname ~ '^tenant_[a-z0-9_]+$' AND t.relname = ANY(tenant_tables)))
      )
  ) THEN
    RAISE EXCEPTION 'Unknown sequence requires explicit privilege review';
  END IF;
  FOR sequence_item IN
    SELECT s.oid::regclass AS relation FROM pg_class s
      JOIN pg_namespace n ON n.oid=s.relnamespace
    WHERE s.relkind='S' AND (n.nspname='public' OR n.nspname ~ '^tenant_[a-z0-9_]+$')
  LOOP
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO cri_runtime_access', sequence_item.relation);
  END LOOP;
END $$;
