"use client";

import * as React from "react";
import { Sidebar, SidebarMobile } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { AuthGuard } from "@/components/auth/auth-guard";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);

  React.useEffect(() => {
    const saved = localStorage.getItem("sidebar-collapsed");
    if (saved === "true") {
      setCollapsed(true);
    }
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
              {children}
            </main>
          </div>
        </div>
      </TooltipProvider>
    </AuthGuard>
  );
}
