"use client";

import {
  Phone,
  Globe,
  Calendar,
  MessageSquare,
  IdCard,
  Loader2,
  AlertCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useContact } from "@/hooks/use-contacts";

interface ContactDetailSheetProps {
  contactId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const languageLabels: Record<string, string> = {
  fr: "Français",
  ar: "Arabe",
  en: "Anglais",
};

const sourceLabels: Record<string, string> = {
  whatsapp: "WhatsApp",
  import_csv: "Import CSV",
  manual: "Création manuelle",
};

const optInLabels: Record<string, { label: string; className: string }> = {
  opted_in: {
    label: "Opt-in actif",
    className: "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-0",
  },
  opted_out: {
    label: "Opt-out",
    className: "bg-destructive/10 text-destructive border-0",
  },
  pending: {
    label: "En attente",
    className: "bg-[hsl(var(--info))]/10 text-[hsl(var(--info))] border-0",
  },
};

function getInitials(name: string | null): string {
  if (!name) return "?";
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function ContactDetailSheet({
  contactId,
  open,
  onOpenChange,
}: ContactDetailSheetProps) {
  const { data: contact, isLoading, isError } = useContact(contactId);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-[420px] overflow-y-auto">
        <SheetHeader className="pb-4">
          <SheetTitle className="font-heading">Détail du contact</SheetTitle>
        </SheetHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : isError || !contact ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <AlertCircle className="h-8 w-8 text-destructive mb-3" />
            <p className="text-sm text-muted-foreground">
              Impossible de charger le contact
            </p>
          </div>
        ) : (
          <div className="space-y-6">
            {/* Avatar + Name + Phone */}
            <div className="flex items-center gap-4">
              <Avatar className="h-14 w-14">
                <AvatarFallback className="bg-primary/10 text-primary font-heading text-lg">
                  {getInitials(contact.name)}
                </AvatarFallback>
              </Avatar>
              <div className="flex-1 min-w-0">
                <h3 className="font-heading font-semibold text-lg truncate">
                  {contact.name || "Sans nom"}
                </h3>
                <p className="text-sm text-muted-foreground font-mono">
                  {contact.phone}
                </p>
              </div>
            </div>

            <Separator />

            {/* Info grid */}
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <Globe className="h-4 w-4 text-muted-foreground shrink-0" strokeWidth={1.75} />
                <span className="text-sm text-muted-foreground">Langue</span>
                <span className="text-sm font-medium ms-auto">
                  {languageLabels[contact.language] ?? contact.language}
                </span>
              </div>

              {contact.cin && (
                <div className="flex items-center gap-3">
                  <IdCard className="h-4 w-4 text-muted-foreground shrink-0" strokeWidth={1.75} />
                  <span className="text-sm text-muted-foreground">CIN</span>
                  <span className="text-sm font-medium font-mono ms-auto">
                    {contact.cin}
                  </span>
                </div>
              )}

              <div className="flex items-center gap-3">
                <Phone className="h-4 w-4 text-muted-foreground shrink-0" strokeWidth={1.75} />
                <span className="text-sm text-muted-foreground">Source</span>
                <span className="text-sm font-medium ms-auto">
                  {sourceLabels[contact.source] ?? contact.source}
                </span>
              </div>

              <div className="flex items-center gap-3">
                <Calendar className="h-4 w-4 text-muted-foreground shrink-0" strokeWidth={1.75} />
                <span className="text-sm text-muted-foreground">Créé le</span>
                <span className="text-sm font-medium ms-auto">
                  {formatDate(contact.created_at)}
                </span>
              </div>
            </div>

            <Separator />

            {/* Opt-in status */}
            <div>
              <p className="text-xs text-muted-foreground mb-2">Consentement</p>
              <Badge className={optInLabels[contact.opt_in_status]?.className}>
                {optInLabels[contact.opt_in_status]?.label ?? contact.opt_in_status}
              </Badge>
            </div>

            {/* Tags */}
            <div>
              <p className="text-xs text-muted-foreground mb-2">Tags</p>
              {contact.tags.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {contact.tags.map((tag) => (
                    <Badge key={tag} variant="outline" className="text-xs">
                      {tag}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Aucun tag</p>
              )}
            </div>

            <Separator />

            {/* Conversation stats */}
            <div className="flex items-center gap-3">
              <MessageSquare className="h-4 w-4 text-muted-foreground shrink-0" strokeWidth={1.75} />
              <span className="text-sm text-muted-foreground">Conversations</span>
              <span className="text-sm font-medium ms-auto">
                {contact.conversation_count}
              </span>
            </div>
            {contact.last_interaction && (
              <div className="flex items-center gap-3">
                <Calendar className="h-4 w-4 text-muted-foreground shrink-0" strokeWidth={1.75} />
                <span className="text-sm text-muted-foreground">Dernière interaction</span>
                <span className="text-sm font-medium ms-auto">
                  {formatDate(contact.last_interaction)}
                </span>
              </div>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
