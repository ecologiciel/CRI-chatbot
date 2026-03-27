"use client";

import { useState, useCallback } from "react";
import {
  Upload,
  FileSpreadsheet,
  Loader2,
  CheckCircle,
  AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useImportContacts } from "@/hooks/use-contacts";
import type { ImportResult } from "@/types/contact";

interface ImportWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Step = "upload" | "confirm" | "results";

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1_048_576) return `${(bytes / 1024).toFixed(0)} Ko`;
  return `${(bytes / 1_048_576).toFixed(1)} Mo`;
}

export function ImportWizard({ open, onOpenChange }: ImportWizardProps) {
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const importMutation = useImportContacts();

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      setFile(droppedFile);
      setStep("confirm");
    }
  }, []);

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selectedFile = e.target.files?.[0];
      if (selectedFile) {
        setFile(selectedFile);
        setStep("confirm");
      }
    },
    [],
  );

  function resetWizard() {
    setStep("upload");
    setFile(null);
    setResult(null);
  }

  function handleImport() {
    if (!file) return;
    importMutation.mutate(file, {
      onSuccess: (data) => {
        setResult(data);
        setStep("results");
        toast.success(`${data.created} contacts importés`);
      },
      onError: () => {
        toast.error("Erreur lors de l'import", {
          description: "Vérifiez le format du fichier.",
        });
      },
    });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!value) resetWizard();
        onOpenChange(value);
      }}
    >
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="font-heading">
            {step === "upload" && "Importer des contacts"}
            {step === "confirm" && "Confirmer l'import"}
            {step === "results" && "Résultats de l'import"}
          </DialogTitle>
          <DialogDescription>
            {step === "upload" &&
              "Importez une liste de contacts depuis un fichier Excel ou CSV."}
            {step === "confirm" &&
              "Vérifiez le fichier avant de lancer l'import."}
            {step === "results" && "Voici le résumé de l'importation."}
          </DialogDescription>
        </DialogHeader>

        {/* Step 1: Upload */}
        {step === "upload" && (
          <div className="py-2">
            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              className={cn(
                "relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-10 transition-colors",
                dragActive
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50",
              )}
            >
              <Upload className="h-10 w-10 text-muted-foreground mb-3" />
              <p className="text-sm font-medium">
                Glissez un fichier ou{" "}
                <label className="text-primary cursor-pointer hover:underline">
                  cliquez pour parcourir
                  <input
                    type="file"
                    className="sr-only"
                    accept=".csv,.xlsx,.xls"
                    onChange={handleFileSelect}
                  />
                </label>
              </p>
              <p className="text-xs text-muted-foreground mt-2">
                CSV ou Excel — colonnes attendues : phone (obligatoire), name,
                language, cin, tags
              </p>
            </div>
          </div>
        )}

        {/* Step 2: Confirm */}
        {step === "confirm" && file && (
          <div className="space-y-4 py-2">
            <div className="flex items-center gap-4 rounded-lg border p-4 bg-muted/30">
              <FileSpreadsheet className="h-8 w-8 text-primary shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="font-medium text-sm truncate">{file.name}</p>
                <p className="text-xs text-muted-foreground">
                  {formatFileSize(file.size)}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="text-xs"
                onClick={() => {
                  setFile(null);
                  setStep("upload");
                }}
              >
                Changer
              </Button>
            </div>

            <div className="rounded-lg border p-4 space-y-2">
              <p className="text-sm font-medium">Comportement :</p>
              <ul className="text-xs text-muted-foreground space-y-1">
                <li>• Les numéros existants seront ignorés (déduplication par téléphone)</li>
                <li>• Les nouveaux contacts seront créés avec le statut &quot;En attente&quot;</li>
                <li>• Maximum 50 000 lignes par fichier</li>
              </ul>
            </div>
          </div>
        )}

        {/* Step 3: Results */}
        {step === "results" && result && (
          <div className="space-y-4 py-2">
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-lg border p-3 text-center">
                <CheckCircle className="h-5 w-5 text-[hsl(var(--success))] mx-auto mb-1" />
                <p className="text-xl font-bold font-heading">{result.created}</p>
                <p className="text-xs text-muted-foreground">Créés</p>
              </div>
              <div className="rounded-lg border p-3 text-center">
                <AlertTriangle className="h-5 w-5 text-[hsl(var(--warning))] mx-auto mb-1" />
                <p className="text-xl font-bold font-heading">{result.skipped}</p>
                <p className="text-xs text-muted-foreground">Ignorés</p>
              </div>
              <div className="rounded-lg border p-3 text-center">
                <AlertTriangle className="h-5 w-5 text-destructive mx-auto mb-1" />
                <p className="text-xl font-bold font-heading">
                  {result.errors.length}
                </p>
                <p className="text-xs text-muted-foreground">Erreurs</p>
              </div>
            </div>

            {result.errors.length > 0 && (
              <div>
                <p className="text-sm font-medium mb-2">Détails des erreurs</p>
                <ScrollArea className="h-[200px] rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-[60px]">Ligne</TableHead>
                        <TableHead className="w-[120px]">Téléphone</TableHead>
                        <TableHead>Erreur</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {result.errors.slice(0, 50).map((err, idx) => (
                        <TableRow key={idx}>
                          <TableCell className="font-mono text-xs">
                            {err.row}
                          </TableCell>
                          <TableCell className="font-mono text-xs">
                            {err.phone || "—"}
                          </TableCell>
                          <TableCell className="text-xs text-destructive">
                            {err.error}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </ScrollArea>
                {result.errors.length > 50 && (
                  <p className="text-xs text-muted-foreground mt-1">
                    et {result.errors.length - 50} erreurs supplémentaires...
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          {step === "upload" && (
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Annuler
            </Button>
          )}
          {step === "confirm" && (
            <>
              <Button
                variant="outline"
                onClick={() => {
                  setFile(null);
                  setStep("upload");
                }}
              >
                Retour
              </Button>
              <Button onClick={handleImport} disabled={importMutation.isPending}>
                {importMutation.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 me-2 animate-spin" />
                    Import en cours...
                  </>
                ) : (
                  "Lancer l'import"
                )}
              </Button>
            </>
          )}
          {step === "results" && (
            <Button
              onClick={() => {
                resetWizard();
                onOpenChange(false);
              }}
            >
              Fermer
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
