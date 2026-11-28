-- Rehearsal only. Before running in the same transaction, set the expected
-- tenant schema with set_config('rehearsal.expected_tenant_schema', ..., true).
-- This checks schema privileges, not shared public-table row isolation.
\set ON_ERROR_STOP on
DO $$
DECLARE expected_schema text := current_setting('rehearsal.expected_tenant_schema', true);
DECLARE me oid;
DECLARE member record;
DECLARE other_schema record;
BEGIN
  IF current_database() !~ '^ragtest_[a-z0-9_]+$' OR current_user <> session_user THEN
    RAISE EXCEPTION 'Tenant privilege audit requires a direct disposable database login';
  END IF;
  IF expected_schema IS NULL OR expected_schema !~ '^tenant_[a-z][a-z0-9_]{0,49}$'
     OR expected_schema = 'tenant_template' OR to_regnamespace(expected_schema) IS NULL THEN
    RAISE EXCEPTION 'Expected tenant schema is invalid or missing';
  END IF;
  SELECT oid INTO me FROM pg_roles WHERE rolname=session_user AND rolcanlogin;
  IF me IS NULL OR NOT has_schema_privilege(me, expected_schema, 'USAGE') THEN
    RAISE EXCEPTION 'Tenant login lacks access to its schema';
  END IF;
  FOR member IN SELECT r.oid, r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolreplication, r.rolbypassrls
                FROM pg_roles r WHERE pg_has_role(me, r.oid, 'MEMBER') LOOP
    IF member.rolsuper OR member.rolcreatedb OR member.rolcreaterole OR member.rolreplication OR member.rolbypassrls THEN
      RAISE EXCEPTION 'Tenant login can assume an elevated role';
    END IF;
    FOR other_schema IN SELECT n.oid FROM pg_namespace n
                        WHERE n.nspname LIKE 'tenant\_%' ESCAPE '\' AND n.nspname <> expected_schema LOOP
      IF has_schema_privilege(member.oid, other_schema.oid, 'USAGE,CREATE') THEN
        RAISE EXCEPTION 'Tenant login can access another tenant schema';
      END IF;
    END LOOP;
  END LOOP;
END $$;
