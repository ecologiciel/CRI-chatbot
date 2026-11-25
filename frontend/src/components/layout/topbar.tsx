"use client";

import * as React from "react";
import { Menu, Globe, KeyRound, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Breadcrumb } from "@/components/layout/breadcrumb";
import { useAuth } from "@/hooks/use-auth";
import { ChangePasswordDialog } from "@/components/layout/change-password-dialog";
import type { Locale } from "@/types";

const localeLabels: Record<Locale, string> = {
  fr: "Français",
  ar: "العربية",
  en: "English",
};

interface TopbarProps {
  onMenuClick: () => void;
}

function getInitials(name: string): string {
  return name
    .split(" ")
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function Topbar({ onMenuClick }: TopbarProps) {
  const { admin, logout } = useAuth();
  const [locale, setLocale] = React.useState<Locale>("fr");
  const [passwordOpen, setPasswordOpen] = React.useState(false);

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
        <Breadcrumb />
      </div>

      {/* Right section */}
      <div className="flex items-center gap-2">
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
            <DropdownMenuItem onSelect={() => setPasswordOpen(true)}>
              <KeyRound className="h-4 w-4" />
              <span>Modifier le mot de passe</span>
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
        <ChangePasswordDialog open={passwordOpen} onOpenChange={setPasswordOpen} />
      </div>
    </header>
  );
}
