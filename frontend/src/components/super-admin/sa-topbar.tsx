"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Menu,
  Search,
  Globe,
  Bell,
  User,
  Settings,
  LogOut,
  ChevronRight,
  Home,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/hooks/use-auth";
import type { Locale } from "@/types";

// ---------------------------------------------------------------------------
// Breadcrumb label map for super-admin routes
// ---------------------------------------------------------------------------

const labelMap: Record<string, string> = {
  sa: "Super-Admin",
  tenants: "Tenants",
  monitoring: "Monitoring",
  configuration: "Configuration",
  audit: "Logs d'audit",
  new: "Créer",
};

const localeLabels: Record<Locale, string> = {
  fr: "Français",
  ar: "العربية",
  en: "English",
};

function getInitials(name: string): string {
  return name
    .split(" ")
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

// ---------------------------------------------------------------------------
// SA Breadcrumb (inline — uses SA label map)
// ---------------------------------------------------------------------------

function SABreadcrumb() {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);

  return (
    <nav aria-label="Fil d'Ariane" className="flex items-center gap-1.5 text-sm">
      <Link
        href="/sa/tenants"
        className="text-muted-foreground hover:text-foreground transition-colors"
      >
        <Home className="h-4 w-4" strokeWidth={1.75} />
      </Link>

      {segments.map((segment, index) => {
        const href = "/" + segments.slice(0, index + 1).join("/");
        const label = labelMap[segment] || segment;
        const isLast = index === segments.length - 1;

        return (
          <span key={href} className="flex items-center gap-1.5">
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/50 rtl:rotate-180" />
            {isLast ? (
              <span className="font-medium text-foreground">{label}</span>
            ) : (
              <Link
                href={href}
                className="text-muted-foreground hover:text-foreground transition-colors"
              >
                {label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// SA Topbar
// ---------------------------------------------------------------------------

interface SATopbarProps {
  onMenuClick: () => void;
}

export function SATopbar({ onMenuClick }: SATopbarProps) {
  const { admin, logout } = useAuth();
  const [locale, setLocale] = React.useState<Locale>("fr");

  React.useEffect(() => {
    const saved = localStorage.getItem("locale") as Locale | null;
    if (saved && (saved === "fr" || saved === "ar" || saved === "en")) {
      setLocale(saved);
      applyLocale(saved);
    }
  }, []);

  function applyLocale(loc: Locale) {
    localStorage.setItem("locale", loc);
    document.documentElement.lang = loc;
    document.documentElement.dir = loc === "ar" ? "rtl" : "ltr";
  }

  function handleLocaleChange(loc: Locale) {
    setLocale(loc);
    applyLocale(loc);
  }

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b bg-card px-4 sm:px-6">
      {/* Mobile menu button */}
      <Button
        variant="ghost"
        size="icon"
        className="md:hidden"
        onClick={onMenuClick}
        aria-label="Ouvrir le menu"
      >
        <Menu className="h-5 w-5" strokeWidth={1.75} />
      </Button>

      {/* Breadcrumb */}
      <div className="flex-1">
        <SABreadcrumb />
      </div>

      {/* Right section */}
      <div className="flex items-center gap-2">
        {/* Super-Admin badge */}
        <Badge
          variant="outline"
          className="hidden sm:inline-flex items-center gap-1.5 bg-primary/10 text-primary border-primary/20 text-xs font-medium px-2.5 py-0.5"
        >
          <ShieldCheck className="h-3.5 w-3.5" strokeWidth={2} />
          Super-Admin
        </Badge>

        {/* Search button (visual only) */}
        <Button
          variant="outline"
          size="sm"
          className={cn(
            "hidden sm:flex items-center gap-2 text-muted-foreground font-normal",
            "h-9 px-3 bg-muted/50 border-border"
          )}
        >
          <Search className="h-4 w-4" strokeWidth={1.75} />
          <span className="text-sm">Rechercher...</span>
          <kbd className="pointer-events-none ms-4 hidden select-none items-center gap-1 rounded border bg-muted px-1.5 text-[10px] font-medium text-muted-foreground sm:flex">
            <span className="text-xs">⌘</span>K
          </kbd>
        </Button>

        {/* Language selector */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="relative">
              <Globe className="h-5 w-5" strokeWidth={1.75} />
              <span className="absolute -bottom-0.5 -end-0.5 text-[9px] font-bold uppercase text-muted-foreground">
                {locale}
              </span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Langue</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {(Object.keys(localeLabels) as Locale[]).map((loc) => (
              <DropdownMenuItem
                key={loc}
                onClick={() => handleLocaleChange(loc)}
                className={cn(locale === loc && "bg-accent")}
              >
                {localeLabels[loc]}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Notifications */}
        <Button variant="ghost" size="icon" className="relative">
          <Bell className="h-5 w-5" strokeWidth={1.75} />
          <Badge className="absolute -top-1 -end-1 h-5 w-5 p-0 flex items-center justify-center text-[10px] bg-destructive border-2 border-card">
            3
          </Badge>
        </Button>

        {/* User avatar dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="rounded-full">
              <Avatar className="h-8 w-8">
                <AvatarFallback className="bg-primary text-primary-foreground text-xs">
                  {admin ? getInitials(admin.full_name) : "?"}
                </AvatarFallback>
              </Avatar>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuLabel>
              <div className="flex flex-col">
                <span className="text-sm font-medium">
                  {admin?.full_name ?? "Utilisateur"}
                </span>
                <span className="text-xs text-muted-foreground">
                  {admin?.email ?? ""}
                </span>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem>
              <User className="h-4 w-4" />
              <span>Profil</span>
            </DropdownMenuItem>
            <DropdownMenuItem>
              <Settings className="h-4 w-4" />
              <span>Paramètres</span>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => logout()}
              className="text-destructive focus:text-destructive"
            >
              <LogOut className="h-4 w-4" />
              <span>Déconnexion</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
