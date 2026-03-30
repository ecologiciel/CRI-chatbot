"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { AdminRole } from "@/types";

const roleConfig: Record<AdminRole, { label: string; className: string }> = {
  super_admin: {
    label: "Super Admin",
    className: "bg-destructive/10 text-destructive border-0",
  },
  admin_tenant: {
    label: "Admin Tenant",
    className: "bg-primary/10 text-primary border-0",
  },
  supervisor: {
    label: "Superviseur",
    className: "bg-[hsl(var(--info))]/10 text-[hsl(var(--info))] border-0",
  },
  viewer: {
    label: "Analyste",
    className: "bg-[hsl(var(--olive))]/10 text-[hsl(var(--olive))] border-0",
  },
};

export function RoleBadge({ role }: { role: AdminRole }) {
  const config = roleConfig[role] ?? roleConfig.viewer;
  return (
    <Badge variant="outline" className={cn("text-xs font-medium", config.className)}>
      {config.label}
    </Badge>
  );
}
