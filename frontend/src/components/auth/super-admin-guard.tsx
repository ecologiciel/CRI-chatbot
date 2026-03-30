"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Building2, Loader2 } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";

/**
 * Route guard that restricts access to super_admin role only.
 * Redirects to /login if the user is not authenticated or not a super_admin.
 */
export function SuperAdminGuard({ children }: { children: React.ReactNode }) {
  const { admin, isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  React.useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    } else if (!isLoading && isAuthenticated && admin?.role !== "super_admin") {
      // Authenticated but not a super_admin — redirect to tenant dashboard
      router.replace("/dashboard");
    }
  }, [isLoading, isAuthenticated, admin, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <Building2 className="h-12 w-12 text-primary" strokeWidth={1.5} />
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Chargement...</span>
          </div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated || admin?.role !== "super_admin") {
    return null;
  }

  return <>{children}</>;
}
