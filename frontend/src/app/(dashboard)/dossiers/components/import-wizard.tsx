"use client";

import { useState, useCallback, useRef } from "react";
import {
  Upload,
  FileSpreadsheet,
  ArrowLeft,
  Loader2,
  CheckCircle2,
  XOctagon,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import {
  useImportDossiers,
  useCreateSyncConfig,
  useSyncConfigs,
  useSyncLogs,
} from "@/hooks/use-dossiers";
import type { SyncLog } from "@/types/dossier";
import { SYNC_STATUS_CONFIG } from "@/types/dossier";
import { ImportMappingStep } from "./import-mapping-step";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
const ALLOWED_EXTENSIONS = [".xlsx", ".xls", ".csv"];

type WizardStep = "upload" | "mapping" | "progress";

const STEP_TITLES: Record<WizardStep, string> = {
  upload: "Importer des dossiers",
  mapping: "Correspondance des colonnes",
  progress: "Import en cours",
};

const STEP_DESCRIPTIONS: Record<WizardStep, string> = {
  upload: "Glissez-déposez un fichier Excel ou CSV",
  mapping: "Associez les colonnes du fichier aux champs du système",
  progress: "Traitement du fichier en arrière-plan",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ImportWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ImportWizard({ open, onOpenChange }: ImportWizardProps) {
  // Step state
  const [step, setStep] = useState<WizardStep>("upload");

  // Upload state
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Mapping state
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [selectedConfigId, setSelectedConfigId] = useState<string | null>(null);

  // Progress state
  const [importFilePath, setImportFilePath] = useState<string | null>(null);
  const [matchedLog, setMatchedLog] = useState<SyncLog | null>(null);
  const isPolling = step === "progress" && !matchedLog?.status?.match(/completed|failed/);

  // Hooks
  const { data: syncConfigs } = useSyncConfigs();
  const importMutation = useImportDossiers();
  const createConfigMutation = useCreateSyncConfig();
  const { data: syncLogsData } = useSyncLogs(
    isPolling ? { page: 1, page_size: 5 } : undefined,
  );

  // Poll sync-logs to find matching entry
  // We check on every render when polling is active
  if (isPolling && syncLogsData?.items && importFilePath) {
    const baseName = importFilePath.split("/").pop() ?? "";
    const match = syncLogsData.items.find(
      (log) => log.file_name?.includes(baseName) && log.status !== "pending",
    ) ?? syncLogsData.items.find(
      (log) => log.file_name?.includes(baseName),
    );
    if (match && match.id !== matchedLog?.id) {
      // Update matched log — check if status changed
      if (!matchedLog || match.status !== matchedLog.status) {
        setMatchedLog(match);
      }
    }
  }

  // Reset wizard state
  function resetWizard() {
    setStep("upload");
    setFile(null);
    setDragActive(false);
    setMapping({});
    setSelectedConfigId(null);
    setImportFilePath(null);
    setMatchedLog(null);
  }

  // --- Drag & Drop ---
  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  }, []);

  const validateFile = useCallback((f: File): string | null => {
    const ext = "." + f.name.split(".").pop()?.toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      return `Format non supporté (${ext}). Utilisez .xlsx, .xls ou .csv`;
    }
    if (f.size > MAX_FILE_SIZE) {
      return `Fichier trop volumineux (${(f.size / 1024 / 1024).toFixed(1)} MB). Maximum 10 MB`;
    }
    return null;
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragActive(false);
      const droppedFile = e.dataTransfer.files[0];
      if (droppedFile) {
        const error = validateFile(droppedFile);
        if (error) {
          toast.error(error);
          return;
        }
        setFile(droppedFile);
        setStep("mapping");
      }
    },
    [validateFile],
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selectedFile = e.target.files?.[0];
      if (selectedFile) {
        const error = validateFile(selectedFile);
        if (error) {
          toast.error(error);
          return;
        }
        setFile(selectedFile);
        setStep("mapping");
      }
    },
    [validateFile],
  );

  // --- Import ---
  async function handleImport() {
    if (!file) return;

    try {
      // Save mapping config if new
      let configId = selectedConfigId;
      if (!configId && Object.keys(mapping).length > 0) {
        const config = await createConfigMutation.mutateAsync({
          column_mapping: mapping,
        });
        configId = config.id;
        setSelectedConfigId(configId);
      }

      // Upload file
      const result = await importMutation.mutateAsync({
        file,
        syncConfigId: configId ?? undefined,
      });

      setImportFilePath(result.file_path);
      setStep("progress");
      toast.success("Import lancé");
    } catch {
      toast.error("Erreur lors du lancement de l'import");
    }
  }

  const hasRequiredMapping = !!mapping.numero;
  const isImporting = importMutation.isPending || createConfigMutation.isPending;

  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!value) resetWizard();
        onOpenChange(value);
      }}
    >
      <DialogContent className="sm:max-w-[640px]">
        <DialogHeader>
          <DialogTitle className="font-heading">
            {STEP_TITLES[step]}
          </DialogTitle>
          <DialogDescription>{STEP_DESCRIPTIONS[step]}</DialogDescription>
        </DialogHeader>

        {/* Stepper */}
        <div className="flex items-center gap-2 py-2">
          {(["upload", "mapping", "progress"] as const).map((s, i) => (
            <div key={s} className="flex items-center gap-2 flex-1">
              <div
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold shrink-0",
                  step === s
                    ? "bg-primary text-primary-foreground"
                    : (["upload", "mapping", "progress"].indexOf(step) > i)
                      ? "bg-[#5F8B5F] text-white"
                      : "bg-muted text-muted-foreground",
                )}
              >
                {i + 1}
              </div>
              {i < 2 && (
                <div
                  className={cn(
                    "h-[2px] flex-1",
                    (["upload", "mapping", "progress"].indexOf(step) > i)
                      ? "bg-[#5F8B5F]"
                      : "bg-border",
                  )}
                />
              )}
            </div>
          ))}
        </div>

        {/* Step 1 — Upload */}
        {step === "upload" && (
          <div className="py-2">
            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={cn(
                "flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-10 cursor-pointer transition-colors",
                dragActive
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50",
              )}
            >
              <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10">
                <Upload className="h-6 w-6 text-primary" strokeWidth={1.75} />
              </div>
              <div className="text-center">
                <p className="text-sm font-medium">
                  Glissez-déposez un fichier ici
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  ou cliquez pour parcourir — .xlsx, .xls, .csv (max 10 MB)
                </p>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                className="sr-only"
                accept=".xlsx,.xls,.csv"
                onChange={handleFileInput}
              />
            </div>
          </div>
        )}

        {/* Step 2 — Mapping */}
        {step === "mapping" && file && (
          <div className="space-y-4 py-2">
            {/* File info */}
            <div className="flex items-center gap-3 rounded-lg border bg-muted/30 p-3">
              <FileSpreadsheet className="h-5 w-5 text-primary shrink-0" strokeWidth={1.75} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium truncate">{file.name}</p>
                <p className="text-xs text-muted-foreground">
                  {(file.size / 1024).toFixed(0)} Ko
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={() => {
                  setFile(null);
                  setMapping({});
                  setStep("upload");
                }}
              >
                <X className="h-4 w-4" />
                <span className="sr-only">Supprimer</span>
              </Button>
            </div>

            <ImportMappingStep
              file={file}
              mapping={mapping}
              onMappingChange={setMapping}
              syncConfigs={syncConfigs ?? []}
              selectedConfigId={selectedConfigId}
              onConfigSelect={setSelectedConfigId}
            />
          </div>
        )}

        {/* Step 3 — Progress */}
        {step === "progress" && (
          <div className="space-y-4 py-4">
            {!matchedLog || matchedLog.status === "pending" || matchedLog.status === "running" ? (
              <div className="flex flex-col items-center gap-4 py-4">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
                <div className="text-center">
                  <p className="text-sm font-medium">Traitement en cours...</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Le fichier est en cours d&apos;import
                  </p>
                </div>
                {matchedLog && matchedLog.rows_total > 0 && (
                  <div className="w-full max-w-xs space-y-1.5">
                    <Progress
                      value={
                        ((matchedLog.rows_imported + matchedLog.rows_updated + matchedLog.rows_errored) /
                          matchedLog.rows_total) *
                        100
                      }
                    />
                    <p className="text-xs text-center text-muted-foreground">
                      {matchedLog.rows_imported + matchedLog.rows_updated} / {matchedLog.rows_total} lignes
                    </p>
                  </div>
                )}
              </div>
            ) : matchedLog.status === "completed" ? (
              <div className="flex flex-col items-center gap-4 py-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-[#5F8B5F]/10">
                  <CheckCircle2 className="h-7 w-7 text-[#5F8B5F]" strokeWidth={1.75} />
                </div>
                <div className="text-center">
                  <p className="text-sm font-semibold">Import terminé</p>
                </div>
                <div className="grid grid-cols-3 gap-4 w-full max-w-sm">
                  <div className="text-center rounded-lg border p-3">
                    <p className="text-xl font-bold font-heading text-[#5F8B5F]">
                      {matchedLog.rows_imported}
                    </p>
                    <p className="text-xs text-muted-foreground">Créés</p>
                  </div>
                  <div className="text-center rounded-lg border p-3">
                    <p className="text-xl font-bold font-heading text-[#5B7A8B]">
                      {matchedLog.rows_updated}
                    </p>
                    <p className="text-xs text-muted-foreground">Mis à jour</p>
                  </div>
                  <div className="text-center rounded-lg border p-3">
                    <p className="text-xl font-bold font-heading text-[#B5544B]">
                      {matchedLog.rows_errored}
                    </p>
                    <p className="text-xs text-muted-foreground">Erreurs</p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-4 py-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-[#B5544B]/10">
                  <XOctagon className="h-7 w-7 text-[#B5544B]" strokeWidth={1.75} />
                </div>
                <div className="text-center">
                  <p className="text-sm font-semibold">L&apos;import a échoué</p>
                  {matchedLog.error_details && (
                    <p className="text-xs text-muted-foreground mt-1 max-w-sm">
                      {JSON.stringify(matchedLog.error_details).slice(0, 200)}
                    </p>
                  )}
                </div>
                {matchedLog.rows_total > 0 && (
                  <Badge className={SYNC_STATUS_CONFIG.failed.className}>
                    {matchedLog.rows_errored} erreur{matchedLog.rows_errored !== 1 ? "s" : ""} sur{" "}
                    {matchedLog.rows_total} lignes
                  </Badge>
                )}
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <DialogFooter className="gap-2 sm:gap-0">
          {step === "mapping" && (
            <>
              <Button
                variant="outline"
                onClick={() => {
                  setFile(null);
                  setMapping({});
                  setStep("upload");
                }}
              >
                <ArrowLeft className="h-4 w-4 me-2" strokeWidth={1.75} />
                Retour
              </Button>
              <Button
                onClick={handleImport}
                disabled={!hasRequiredMapping || isImporting}
              >
                {isImporting && <Loader2 className="h-4 w-4 me-2 animate-spin" />}
                Lancer l&apos;import
              </Button>
            </>
          )}
          {step === "progress" && (
            matchedLog?.status === "completed" || matchedLog?.status === "failed"
          ) && (
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
