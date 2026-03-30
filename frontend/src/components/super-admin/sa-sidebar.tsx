"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Building,
  Activity,
  Settings,
  ScrollText,
  ChevronLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Separator } from "@/components/ui/separator";
import type { NavItem } from "@/types";

// ---------------------------------------------------------------------------
// Super-admin navigation (4 items)
// ---------------------------------------------------------------------------

const navItems: NavItem[] = [
  { label: "Tenants", href: "/sa/tenants", icon: Building },
  { label: "Monitoring", href: "/sa/monitoring", icon: Activity },
  { label: "Configuration", href: "/sa/configuration", icon: Settings },
  { label: "Logs d'audit", href: "/sa/audit", icon: ScrollText },
];

// ---------------------------------------------------------------------------
// Desktop sidebar
// ---------------------------------------------------------------------------

interface SASidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function SASidebar({ collapsed, onToggle }: SASidebarProps) {
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "hidden md:flex flex-col h-screen sticky top-0 z-40 border-e border-white/10 transition-all duration-200 ease-out",
        collapsed ? "w-16" : "w-60"
      )}
      style={{ backgroundColor: "hsl(var(--sidebar-bg))" }}
    >
      {/* Header — Platform branding */}
      <div className="flex h-14 items-center gap-3 px-4">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary/20">
          <Building className="h-4 w-4 text-primary" strokeWidth={2} />
        </div>
        {!collapsed && (
          <div className="flex flex-col min-w-0">
            <span className="text-sm font-bold font-heading text-white truncate">
              CRI Platform
            </span>
            <span className="text-[11px] text-white/50">Administration</span>
          </div>
        )}
      </div>

      <div className="mx-3">
        <Separator className="bg-white/10" />
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-4 space-y-1">
        {navItems.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
          const Icon = item.icon;

          const linkContent = (
            <Link
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/20 text-white border-s-[3px] border-primary"
                  : "text-[hsl(var(--sidebar-fg))] hover:bg-white/[0.06]"
              )}
            >
              <Icon className="h-5 w-5 shrink-0" strokeWidth={1.75} />
              {!collapsed && (
                <span className="flex-1 truncate">{item.label}</span>
              )}
            </Link>
          );

          if (collapsed) {
            return (
              <Tooltip key={item.href} delayDuration={0}>
                <TooltipTrigger asChild>{linkContent}</TooltipTrigger>
                <TooltipContent side="right" className="font-sans">
                  <p>{item.label}</p>
                </TooltipContent>
              </Tooltip>
            );
          }

          return <React.Fragment key={item.href}>{linkContent}</React.Fragment>;
        })}
      </nav>

      {/* Collapse toggle */}
      <div className="px-2 py-3">
        <div className="mx-3 mb-3">
          <Separator className="bg-white/10" />
        </div>
        <button
          onClick={onToggle}
          className="flex w-full items-center justify-center rounded-lg px-3 py-2 text-sm text-[hsl(var(--sidebar-fg))] hover:bg-white/[0.06] transition-colors"
          aria-label={collapsed ? "Déplier le menu" : "Replier le menu"}
        >
          <ChevronLeft
            className={cn(
              "h-5 w-5 transition-transform duration-200",
              collapsed && "rotate-180 rtl:rotate-0",
              !collapsed && "rtl:rotate-180"
            )}
            strokeWidth={1.75}
          />
          {!collapsed && <span className="ms-3 text-sm">Replier</span>}
        </button>
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Mobile sidebar — used inside Sheet
// ---------------------------------------------------------------------------

export function SASidebarMobile({ onClose }: { onClose: () => void }) {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: "hsl(var(--sidebar-bg))" }}>
      {/* Header */}
      <div className="flex h-14 items-center gap-3 px-4">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary/20">
          <Building className="h-4 w-4 text-primary" strokeWidth={2} />
        </div>
        <div className="flex flex-col min-w-0">
          <span className="text-sm font-bold font-heading text-white">
            CRI Platform
          </span>
          <span className="text-[11px] text-white/50">Administration</span>
        </div>
      </div>

      <div className="mx-3">
        <Separator className="bg-white/10" />
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-4 space-y-1">
        {navItems.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => onClose()}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/20 text-white border-s-[3px] border-primary"
                  : "text-[hsl(var(--sidebar-fg))] hover:bg-white/[0.06]"
              )}
            >
              <Icon className="h-5 w-5 shrink-0" strokeWidth={1.75} />
              <span className="flex-1 truncate">{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
