-- =============================================================================
-- Audit Trail Security Policy (SECURITE.1)
-- =============================================================================
--
-- Run this ONCE in production after migration 007.
-- Enforces INSERT-ONLY on public.audit_logs for the application DB user.
--
-- The application user (cri_admin) can:
--   - INSERT new audit log entries
--   - SELECT for the back-office audit trail UI
--
-- The application user CANNOT:
--   - UPDATE existing entries (immutability)
--   - DELETE entries (tamper-resistance)
--
-- Only PostgreSQL superusers can modify or drop the table.
--
-- Usage:
--   psql -U postgres -d cri_platform -f scripts/apply_audit_policy.sql
--
-- Replace 'cri_admin' below if your POSTGRES_USER differs.
-- =============================================================================

-- Revoke all existing privileges on the audit table
REVOKE ALL ON public.audit_logs FROM cri_admin;

-- Grant only INSERT and SELECT
GRANT INSERT ON public.audit_logs TO cri_admin;
GRANT SELECT ON public.audit_logs TO cri_admin;

-- Verify the policy (run manually):
--   \dp public.audit_logs
-- Expected output should show only INSERT and SELECT for cri_admin.

-- Optional: create a read-only auditor role for external audit access
-- CREATE ROLE cri_auditor NOLOGIN;
-- GRANT SELECT ON public.audit_logs TO cri_auditor;
-- GRANT cri_auditor TO <auditor_login_role>;
