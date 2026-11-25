"use client";

import * as React from "react";
import Link from "next/link";
import { Sidebar, SidebarMobile } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { AuthGuard } from "@/components/auth/auth-guard";
import { useAuth } from "@/hooks/use-auth";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [institutionName, setInstitutionName] = React.useState<string | null>(null);
  const { admin } = useAuth();

  React.useEffect(() => {
    const saved = localStorage.getItem("sidebar-collapsed");
    if (saved === "true") {
      setCollapsed(true);
    }
    setInstitutionName(sessionStorage.getItem("cri_selected_tenant_name"));
  }, []);

  function handleToggle() {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("sidebar-collapsed", String(next));
      return next;
    });
  }

  return (
    <AuthGuard>
      <TooltipProvider delayDuration={0}>
        <div className="flex h-screen overflow-hidden">
          {/* Desktop sidebar */}
          <Sidebar collapsed={collapsed} onToggle={handleToggle} />

          {/* Mobile sidebar (Sheet overlay) */}
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetContent side="left" className="p-0 w-72 border-0">
              <SidebarMobile onClose={() => setMobileOpen(false)} />
            </SheetContent>
          </Sheet>

          {/* Main content */}
          <div className="flex flex-1 flex-col overflow-hidden">
            <Topbar onMenuClick={() => setMobileOpen(true)} />
            <main className="flex-1 overflow-y-auto bg-background p-6">
              {admin?.role === "super_admin" && (
                <div className="mb-4 rounded border p-3 text-sm">
                  {institutionName ? `Institution : ${institutionName}` : "Aucune institution sélectionnée."}{" "}
                  <Link href="/sa/tenants" className="underline">Choisir une institution</Link>
                </div>
              )}
              {admin?.role !== "super_admin" || institutionName ? children : null}
            </main>
          </div>
        </div>
      </TooltipProvider>
    </AuthGuard>
  );
}
