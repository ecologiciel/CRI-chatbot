/**
 * Re-export auth hooks from the provider module.
 * Components import from "@/hooks/use-auth" for consistency.
 */
export { useAuth, useApiClient } from "@/lib/auth-provider";
