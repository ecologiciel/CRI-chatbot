"use client";

import { useState } from "react";
import { Loader2, AlertCircle, RefreshCw, Pencil, Check, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  useNotificationTemplates,
  useUpdateTemplate,
} from "@/hooks/use-notifications";

// ---------------------------------------------------------------------------
// Config maps
// ---------------------------------------------------------------------------

const EVENT_TYPE_LABELS: Record<string, string> = {
  decision_finale: "Décision finale",
  complement_request: "Demande de complément",
  status_update: "Mise à jour du statut",
  dossier_incomplet: "Dossier incomplet",
};

const PRIORITY_CONFIG: Record<string, { label: string; className: string }> = {
  high: {
    label: "Haute",
    className: "bg-destructive/10 text-destructive border-0",
  },
  medium: {
    label: "Moyenne",
    className: "bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-0",
  },
  low: {
    label: "Basse",
    className: "bg-muted text-muted-foreground border-0",
  },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TemplateConfig() {
  const { data: templates, isLoading, isError, refetch } =
    useNotificationTemplates();
  const updateMutation = useUpdateTemplate();

  const [editingEvent, setEditingEvent] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  function startEdit(eventType: string, currentName: string) {
    setEditingEvent(eventType);
    setEditValue(currentName);
  }

  function cancelEdit() {
    setEditingEvent(null);
    setEditValue("");
  }

  async function saveEdit(eventType: string) {
    if (!editValue.trim()) {
      toast.error("Le nom du template ne peut pas être vide");
      return;
    }

    try {
      await updateMutation.mutateAsync({
        eventType,
        data: { template_name: editValue.trim() },
      });
      toast.success("Template mis à jour");
      setEditingEvent(null);
      setEditValue("");
    } catch {
      toast.error("Erreur lors de la mise à jour du template");
    }
  }

  if (isLoading) {
    return (
      <Card className="shadow-card">
        <CardContent className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card className="shadow-card">
        <CardContent className="flex flex-col items-center justify-center py-16 gap-2">
          <AlertCircle className="h-5 w-5 text-destructive" />
          <p className="text-sm text-muted-foreground">
            Impossible de charger les templates
          </p>
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="h-3 w-3 me-1" />
            Réessayer
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="shadow-card">
      <CardHeader>
        <CardTitle className="text-lg font-heading">
          Mapping Templates WhatsApp
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Associez un template WhatsApp Meta à chaque type d&apos;événement de
          notification.
        </p>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-start">Type d&apos;événement</TableHead>
              <TableHead className="text-start">Template WhatsApp</TableHead>
              <TableHead className="text-start hidden sm:table-cell">
                Description
              </TableHead>
              <TableHead className="text-start hidden sm:table-cell">
                Priorité
              </TableHead>
              <TableHead className="text-end w-[100px]">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {templates?.map((tpl) => {
              const isEditing = editingEvent === tpl.event_type;
              const priorityCfg = PRIORITY_CONFIG[tpl.priority] ?? {
                label: tpl.priority,
                className: "bg-muted text-muted-foreground border-0",
              };

              return (
                <TableRow key={tpl.event_type}>
                  <TableCell>
                    <span className="text-sm font-medium">
                      {EVENT_TYPE_LABELS[tpl.event_type] ?? tpl.event_type}
                    </span>
                  </TableCell>
                  <TableCell>
                    {isEditing ? (
                      <Input
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        className="h-8 text-sm font-mono"
                        autoFocus
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            saveEdit(tpl.event_type);
                          }
                          if (e.key === "Escape") cancelEdit();
                        }}
                      />
                    ) : (
                      <span className="text-sm font-mono">
                        {tpl.template_name}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <span className="text-sm text-muted-foreground">
                      {tpl.description}
                    </span>
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <Badge
                      className={cn(
                        "text-xs font-medium",
                        priorityCfg.className,
                      )}
                    >
                      {priorityCfg.label}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-end">
                    {isEditing ? (
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          disabled={updateMutation.isPending}
                          onClick={() => saveEdit(tpl.event_type)}
                        >
                          {updateMutation.isPending ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Check className="h-3.5 w-3.5 text-[hsl(var(--success))]" />
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          onClick={cancelEdit}
                        >
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ) : (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() =>
                          startEdit(tpl.event_type, tpl.template_name)
                        }
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
