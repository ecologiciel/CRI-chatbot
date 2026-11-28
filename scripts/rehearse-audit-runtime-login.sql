-- EXPERIMENTAL: inspect effective privileges only in a disposable rehearsal DB.
-- Run as the actual login, not through SET ROLE. This is not an isolation proof.
\set ON_ERROR_STOP on
DO $$
DECLARE member record;
DECLARE col record;
DECLARE me oid;
BEGIN
  IF current_database() !~ '^ragtest_[a-z0-9_]+$' OR current_user <> session_user THEN
    RAISE EXCEPTION 'Login audit requires a direct connection to a disposable ragtest_ database';
  END IF;
  SELECT oid INTO me FROM pg_roles WHERE rolname=session_user AND rolcanlogin;
  IF me IS NULL OR to_regclass('public.agent_reply_outbox_events') IS NULL
     OR to_regclass('public.audit_logs') IS NULL OR to_regclass('public.alembic_version') IS NULL
     OR NOT pg_has_role(me, 'cri_runtime_access'::regrole, 'USAGE') THEN
    RAISE EXCEPTION 'Runtime login or required objects are unavailable';
  END IF;
  IF NOT has_table_privilege(me, 'public.agent_reply_outbox_events', 'SELECT')
     OR NOT has_table_privilege(me, 'public.agent_reply_outbox_events', 'INSERT')
     OR NOT has_column_privilege(me, 'public.agent_reply_outbox_events', 'state', 'UPDATE')
     OR NOT has_table_privilege(me, 'public.audit_logs', 'SELECT')
     OR NOT has_table_privilege(me, 'public.audit_logs', 'INSERT')
     OR NOT has_table_privilege(me, 'public.alembic_version', 'SELECT') THEN
    RAISE EXCEPTION 'Runtime login lacks required privileges';
  END IF;
  -- Check the login and every role it can SET ROLE to, including NOINHERIT
  -- memberships. A benign-looking current role must not hide an unsafe one.
  FOR member IN SELECT r.oid, r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolreplication, r.rolbypassrls
                FROM pg_roles r WHERE pg_has_role(me, r.oid, 'MEMBER') LOOP
    IF member.rolsuper OR member.rolcreatedb OR member.rolcreaterole OR member.rolreplication OR member.rolbypassrls
       OR has_table_privilege(member.oid, 'public.agent_reply_outbox_events', 'DELETE,TRUNCATE,TRIGGER,REFERENCES')
       OR has_table_privilege(member.oid, 'public.audit_logs', 'DELETE,TRUNCATE,TRIGGER,REFERENCES')
       OR has_table_privilege(member.oid, 'public.alembic_version', 'INSERT,DELETE,TRUNCATE,TRIGGER,REFERENCES') THEN
      RAISE EXCEPTION 'Runtime login can assume a role with forbidden privileges';
    END IF;
    FOR col IN SELECT unnest(ARRAY['id','tenant_id','request_key','actor_id','escalation_id','conversation_id','sequence','key_version','created_at']) AS name LOOP
      IF has_column_privilege(member.oid, 'public.agent_reply_outbox_events', col.name, 'UPDATE') THEN
        RAISE EXCEPTION 'Runtime login can change an immutable reply identity';
      END IF;
    END LOOP;
    FOR col IN SELECT attname AS name FROM pg_attribute WHERE attrelid='public.audit_logs'::regclass AND attnum>0 AND NOT attisdropped LOOP
      IF has_column_privilege(member.oid, 'public.audit_logs', col.name, 'UPDATE') THEN
        RAISE EXCEPTION 'Runtime login can modify audit records';
      END IF;
    END LOOP;
    FOR col IN SELECT attname AS name FROM pg_attribute WHERE attrelid='public.alembic_version'::regclass AND attnum>0 AND NOT attisdropped LOOP
      IF has_column_privilege(member.oid, 'public.alembic_version', col.name, 'UPDATE') THEN
        RAISE EXCEPTION 'Runtime login can modify schema versions';
      END IF;
    END LOOP;
  END LOOP;
END $$;
