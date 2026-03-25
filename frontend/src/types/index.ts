import type { LucideIcon } from "lucide-react";

export type Locale = "fr" | "ar" | "en";

export type AdminRole = "super_admin" | "admin_tenant" | "supervisor" | "viewer";

export type TenantStatus = "active" | "inactive" | "suspended" | "provisioning";

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  region: string;
  logoUrl: string | null;
  accentColor: string | null;
  status: TenantStatus;
}

export interface Admin {
  id: string;
  email: string;
  fullName: string;
  role: AdminRole;
  tenantId: string | null;
}

export interface KPICard {
  title: string;
  value: string | number;
  icon: LucideIcon;
  color: "primary" | "success" | "warning" | "info";
}

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  badge?: string;
  disabled?: boolean;
}
