"use client";

import * as React from "react";
import { SASidebar, SASidebarMobile } from "@/components/super-admin/sa-sidebar";
import { SATopbar } from "@/components/super-admin/sa-topbar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { SuperAdminGuard } from "@/components/auth/super-admin-guard";

export default function SuperAdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);

  React.useEffect(() => {
    const saved = localStorage.getItem("sa-sidebar-collapsed");
    if (saved === "true") {
      setCollapsed(true);
    }
  }, []);

  function handleToggle() {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("sa-sidebar-collapsed", String(next));
      return next;
    });
  }

  return (
    <SuperAdminGuard>
      <TooltipProvider delayDuration={0}>
        <div className="flex h-screen overflow-hidden">
          {/* Desktop sidebar */}
          <SASidebar collapsed={collapsed} onToggle={handleToggle} />

          {/* Mobile sidebar (Sheet overlay) */}
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetContent side="left" className="p-0 w-72 border-0">
              <SASidebarMobile onClose={() => setMobileOpen(false)} />
            </SheetContent>
          </Sheet>

          {/* Main content */}
          <div className="flex flex-1 flex-col overflow-hidden">
            <SATopbar onMenuClick={() => setMobileOpen(true)} />
            <main className="flex-1 overflow-y-auto bg-background p-6">
              {children}
            </main>
          </div>
        </div>
      </TooltipProvider>
    </SuperAdminGuard>
  );
}
