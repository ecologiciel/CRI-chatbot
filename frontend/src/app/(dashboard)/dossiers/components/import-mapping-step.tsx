"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { SyncConfig } from "@/types/dossier";
import { MAPPABLE_FIELDS } from "@/types/dossier";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ImportMappingStepProps {
  file: File;
  mapping: Record<string, string>;
  onMappingChange: (mapping: Record<string, string>) => void;
  syncConfigs: SyncConfig[];
  selectedConfigId: string | null;
  onConfigSelect: (id: string | null) => void;
}

// ---------------------------------------------------------------------------
// File parsing helpers
// ---------------------------------------------------------------------------

/** Auto-detect CSV delimiter by counting occurrences in the first line. */
function detectDelimiter(firstLine: string): string {
  const commas = (firstLine.match(/,/g) || []).length;
  const semicolons = (firstLine.match(/;/g) || []).length;
  const tabs = (firstLine.match(/\t/g) || []).length;
  if (tabs >= commas && tabs >= semicolons) return "\t";
  return semicolons > commas ? ";" : ",";
}

function parseCsvText(
  text: string,
): { headers: string[]; rows: string[][] } {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length === 0) return { headers: [], rows: [] };
  const delimiter = detectDelimiter(lines[0]);
  const headers = lines[0].split(delimiter).map((h) => h.trim().replace(/^"|"$/g, ""));
  const rows = lines.slice(1, 6).map((line) =>
    line.split(delimiter).map((cell) => cell.trim().replace(/^"|"$/g, "")),
  );
  return { headers, rows };
}

async function parseXlsxFile(
  file: File,
): Promise<{ headers: string[]; rows: string[][] }> {
  const XLSX = await import("xlsx");
  const buffer = await file.arrayBuffer();
  const wb = XLSX.read(buffer, { type: "array" });
  const sheet = wb.Sheets[wb.SheetNames[0]];
  const data = XLSX.utils.sheet_to_json<string[]>(sheet, { header: 1 });
  if (data.length === 0) return { headers: [], rows: [] };
  const headers = (data[0] || []).map((h) => String(h ?? "").trim());
  const rows = data.slice(1, 6).map((row) =>
    row.map((cell) => String(cell ?? "").trim()),
  );
  return { headers, rows };
}

/** Simple fuzzy match for auto-mapping column headers to target fields. */
function autoMap(
  headers: string[],
  existingMapping?: Record<string, string>,
): Record<string, string> {
  if (existingMapping && Object.keys(existingMapping).length > 0) {
    return { ...existingMapping };
  }

  const result: Record<string, string> = {};
  const normalize = (s: string) =>
    s
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]/g, "");

  for (const header of headers) {
    const norm = normalize(header);
    for (const field of MAPPABLE_FIELDS) {
      const fieldNorm = normalize(field.label);
      const fieldValueNorm = normalize(field.value);
      if (
        norm === fieldNorm ||
        norm === fieldValueNorm ||
        norm.includes(fieldValueNorm) ||
        fieldNorm.includes(norm)
      ) {
        if (!Object.values(result).includes(header)) {
          result[field.value] = header;
        }
        break;
      }
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ImportMappingStep({
  file,
  mapping,
  onMappingChange,
  syncConfigs,
  selectedConfigId,
  onConfigSelect,
}: ImportMappingStepProps) {
  const [headers, setHeaders] = useState<string[]>([]);
  const [previewRows, setPreviewRows] = useState<string[][]>([]);
  const [parsing, setParsing] = useState(true);
  const [parseError, setParseError] = useState<string | null>(null);

  // Parse file on mount or file change
  useEffect(() => {
    let cancelled = false;
    setParsing(true);
    setParseError(null);

    async function parse() {
      try {
        const ext = file.name.split(".").pop()?.toLowerCase();
        let result: { headers: string[]; rows: string[][] };

        if (ext === "csv") {
          const text = await file.text();
          result = parseCsvText(text);
        } else {
          result = await parseXlsxFile(file);
        }

        if (cancelled) return;
        setHeaders(result.headers);
        setPreviewRows(result.rows);

        // Auto-map based on existing config or fuzzy match
        const existingConfig = selectedConfigId
          ? syncConfigs.find((c) => c.id === selectedConfigId)
          : null;
        const autoMapping = autoMap(
          result.headers,
          existingConfig?.column_mapping,
        );
        onMappingChange(autoMapping);
      } catch {
        if (!cancelled) setParseError("Impossible de lire le fichier");
      } finally {
        if (!cancelled) setParsing(false);
      }
    }

    parse();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, selectedConfigId]);

  function handleFieldMapping(targetField: string, sourceColumn: string) {
    const updated = { ...mapping };
    if (sourceColumn === "__none__") {
      delete updated[targetField];
    } else {
      updated[targetField] = sourceColumn;
    }
    onMappingChange(updated);
  }

  if (parsing) {
    return (
      <div className="flex items-center justify-center py-12 gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span className="text-sm">Analyse du fichier...</span>
      </div>
    );
  }

  if (parseError) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <AlertCircle className="h-8 w-8 text-destructive mb-3" />
        <p className="text-sm text-muted-foreground">{parseError}</p>
      </div>
    );
  }

  const mappedCount = Object.keys(mapping).length;
  const hasNumero = !!mapping.numero;

  return (
    <div className="space-y-5">
      {/* Existing config selector */}
      {syncConfigs.length > 0 && (
        <div>
          <label className="text-sm font-medium mb-1.5 block">
            Mapping existant
          </label>
          <Select
            value={selectedConfigId ?? "__new__"}
            onValueChange={(v) => onConfigSelect(v === "__new__" ? null : v)}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Nouveau mapping" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__new__">Nouveau mapping</SelectItem>
              {syncConfigs.map((cfg) => (
                <SelectItem key={cfg.id} value={cfg.id}>
                  Config #{cfg.id.slice(0, 8)} ({Object.keys(cfg.column_mapping).length} champs)
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* File preview */}
      {headers.length > 0 && previewRows.length > 0 && (
        <div>
          <p className="text-sm font-medium mb-1.5">
            Aperçu ({previewRows.length} premières lignes)
          </p>
          <ScrollArea className="rounded-lg border">
            <div className="max-h-[200px] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    {headers.map((h, i) => (
                      <TableHead key={i} className="text-xs whitespace-nowrap">
                        {h}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {previewRows.map((row, ri) => (
                    <TableRow key={ri}>
                      {row.map((cell, ci) => (
                        <TableCell key={ci} className="text-xs whitespace-nowrap py-1.5">
                          {cell || "—"}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </ScrollArea>
        </div>
      )}

      {/* Column mapping */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <p className="text-sm font-medium">
            Correspondance des colonnes
          </p>
          <Badge variant="secondary" className="text-xs">
            {mappedCount} champ{mappedCount !== 1 ? "s" : ""} mappé{mappedCount !== 1 ? "s" : ""}
          </Badge>
        </div>
        {!hasNumero && (
          <p className="text-xs text-destructive mb-2">
            Le champ &ldquo;Numéro de dossier&rdquo; est obligatoire
          </p>
        )}
        <div className="space-y-2">
          {MAPPABLE_FIELDS.map((field) => (
            <div
              key={field.value}
              className="flex items-center gap-3"
            >
              <span className="text-sm w-[180px] shrink-0">
                {field.label}
                {field.required && (
                  <span className="text-destructive ms-0.5">*</span>
                )}
              </span>
              <Select
                value={mapping[field.value] ?? "__none__"}
                onValueChange={(v) => handleFieldMapping(field.value, v)}
              >
                <SelectTrigger className="flex-1">
                  <SelectValue placeholder="— Non mappé —" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">— Non mappé —</SelectItem>
                  {headers.map((h) => (
                    <SelectItem key={h} value={h}>
                      {h}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
