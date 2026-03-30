"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  MessageSquare,
  BookOpen,
  Users,
  Shield,
  Send,
  BarChart3,
  Settings,
  Building2,
  ChevronLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Separator } from "@/components/ui/separator";
import type { NavItem } from "@/types";

const navItems: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Conversations", href: "/conversations", icon: MessageSquare },
  { label: "Base de connaissances", href: "/kb", icon: BookOpen },
  { label: "Contacts", href: "/contacts", icon: Users },
  { label: "Utilisateurs", href: "/users", icon: Shield },
  { label: "Campagnes", href: "/campaigns", icon: Send },
  { label: "Analytics", href: "/analytics", icon: BarChart3 },
  { label: "Paramètres", href: "/settings", icon: Settings },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "hidden md:flex flex-col h-screen sticky top-0 z-40 border-e border-white/10 transition-all duration-200 ease-out",
        collapsed ? "w-16" : "w-60"
      )}
      style={{ backgroundColor: "hsl(var(--sidebar-bg))" }}
    >
      {/* Logo */}
      <div className="flex h-14 items-center gap-3 px-4">
        <Building2 className="h-7 w-7 shrink-0 text-primary" />
        {!collapsed && (
          <span className="text-lg font-bold font-heading text-white truncate">
            CRI Platform
          </span>
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
              href={item.disabled ? "#" : item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/20 text-white border-s-[3px] border-primary"
                  : "text-[hsl(var(--sidebar-fg))] hover:bg-white/[0.06]",
                item.disabled && "opacity-50 cursor-not-allowed"
              )}
              onClick={item.disabled ? (e) => e.preventDefault() : undefined}
            >
              <Icon className="h-5 w-5 shrink-0" strokeWidth={1.75} />
              {!collapsed && (
                <span className="flex-1 truncate">{item.label}</span>
              )}
              {!collapsed && item.badge && (
                <Badge
                  variant="secondary"
                  className="text-[10px] px-1.5 py-0 h-5 bg-white/10 text-white/60 border-0"
                >
                  {item.badge}
                </Badge>
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

      {/* Collapse Toggle */}
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

/** Mobile sidebar content — used inside Sheet */
export function SidebarMobile({ onClose }: { onClose: () => void }) {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: "hsl(var(--sidebar-bg))" }}>
      {/* Logo */}
      <div className="flex h-14 items-center gap-3 px-4">
        <Building2 className="h-7 w-7 shrink-0 text-primary" />
        <span className="text-lg font-bold font-heading text-white">CRI Platform</span>
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
              href={item.disabled ? "#" : item.href}
              onClick={(e) => {
                if (item.disabled) {
                  e.preventDefault();
                  return;
                }
                onClose();
              }}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/20 text-white border-s-[3px] border-primary"
                  : "text-[hsl(var(--sidebar-fg))] hover:bg-white/[0.06]",
                item.disabled && "opacity-50 cursor-not-allowed"
              )}
            >
              <Icon className="h-5 w-5 shrink-0" strokeWidth={1.75} />
              <span className="flex-1 truncate">{item.label}</span>
              {item.badge && (
                <Badge
                  variant="secondary"
                  className="text-[10px] px-1.5 py-0 h-5 bg-white/10 text-white/60 border-0"
                >
                  {item.badge}
                </Badge>
              )}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
