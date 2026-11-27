-- EXPERIMENTAL; install only in an isolated rehearsal database.
\set ON_ERROR_STOP on
BEGIN;
DO $$
BEGIN
  IF current_database() !~ '^ragtest_[a-z0-9_]+$' THEN
    RAISE EXCEPTION 'Schema drop rehearsal requires a disposable ragtest_ database';
  END IF;
END $$;

CREATE FUNCTION public.rehearsal_drop_tenant_schema(p_slug text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE tenant_uuid uuid;
DECLARE tenant_status text;
BEGIN
  IF p_slug IS NULL OR p_slug !~ '^[a-z][a-z0-9_]{0,49}$' OR p_slug = 'template' THEN
    RAISE EXCEPTION 'Invalid tenant schema identifier';
  END IF;
  SELECT id, status::text INTO tenant_uuid, tenant_status
  FROM public.tenants WHERE slug = p_slug FOR UPDATE;
  IF NOT FOUND OR tenant_status IS NULL OR tenant_status NOT IN ('inactive', 'provisioning') THEN
    RAISE EXCEPTION 'Tenant is missing or not eligible for schema removal';
  END IF;
  INSERT INTO public.audit_logs (tenant_slug, user_type, action, resource_type, resource_id, details)
  VALUES (p_slug, 'system', 'tenant_schema_drop', 'tenant_schema', tenant_uuid::text,
          pg_catalog.jsonb_build_object('source', 'restricted_function'));
  EXECUTE pg_catalog.format('DROP SCHEMA IF EXISTS %I CASCADE', 'tenant_' || p_slug);
END $$;

REVOKE ALL ON FUNCTION public.rehearsal_drop_tenant_schema(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rehearsal_drop_tenant_schema(text) TO cri_runtime_access;
COMMIT;
