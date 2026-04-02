// ---------------------------------------------------------------------------
// Dossier types — mirrors backend DossierRead / DossierStats / Sync* schemas
// ---------------------------------------------------------------------------

import type { LucideIcon } from "lucide-react";
import {
  Clock,
  CheckCircle,
  XCircle,
  Hourglass,
  Paperclip,
  AlertTriangle,
  FolderOpen,
  Loader2,
  CheckCircle2,
  XOctagon,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type DossierStatut =
  | "en_cours"
  | "valide"
  | "rejete"
  | "en_attente"
  | "complement"
  | "incomplet";

export type SyncStatus = "pending" | "running" | "completed" | "failed";

export type SyncSourceType = "excel" | "csv" | "api_rest" | "manual";

export type SyncProviderType = "excel_csv" | "api_rest" | "db_link";

// ---------------------------------------------------------------------------
// Data interfaces
// ---------------------------------------------------------------------------

export interface Dossier {
  id: string;
  numero: string;
  contact_id: string | null;
  statut: DossierStatut;
  type_projet: string | null;
  raison_sociale: string | null;
  montant_investissement: string | null; // Decimal serialized as string
  region: string | null;
  secteur: string | null;
  date_depot: string | null;
  date_derniere_maj: string | null;
  observations: string | null;
  created_at: string;
  updated_at: string;
}

export interface DossierHistory {
  id: string;
  field_changed: string;
  old_value: string | null;
  new_value: string | null;
  changed_at: string;
  sync_log_id: string | null;
}

export interface DossierDetail extends Dossier {
  history: DossierHistory[];
}

export interface DossierStats {
  total: number;
  en_cours: number;
  valide: number;
  rejete: number;
  en_attente: number;
  complement: number;
  incomplet: number;
}

export interface SyncLog {
  id: string;
  source_type: SyncSourceType;
  file_name: string | null;
  file_hash: string | null;
  rows_total: number;
  rows_imported: number;
  rows_updated: number;
  rows_errored: number;
  error_details: Record<string, unknown> | null;
  status: SyncStatus;
  started_at: string | null;
  completed_at: string | null;
  triggered_by: string | null;
  created_at: string;
}

export interface SyncConfig {
  id: string;
  provider_type: SyncProviderType;
  config_json: Record<string, unknown>;
  column_mapping: Record<string, string>;
  schedule_cron: string | null;
  watched_folder: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SyncConfigCreatePayload {
  provider_type?: SyncProviderType;
  config_json?: Record<string, unknown>;
  column_mapping: Record<string, string>;
  schedule_cron?: string;
  watched_folder?: string;
  is_active?: boolean;
}

// ---------------------------------------------------------------------------
// UI config — labels, styling, icons
// ---------------------------------------------------------------------------

export const STATUT_CONFIG: Record<
  DossierStatut,
  { label: string; className: string; icon: LucideIcon }
> = {
  en_cours: {
    label: "En cours",
    className: "bg-[#C4944B]/10 text-[#C4944B] border-[#C4944B]/20",
    icon: Clock,
  },
  valide: {
    label: "Validé",
    className: "bg-[#5F8B5F]/10 text-[#5F8B5F] border-[#5F8B5F]/20",
    icon: CheckCircle,
  },
  rejete: {
    label: "Rejeté",
    className: "bg-[#B5544B]/10 text-[#B5544B] border-[#B5544B]/20",
    icon: XCircle,
  },
  en_attente: {
    label: "En attente",
    className: "bg-[#5B7A8B]/10 text-[#5B7A8B] border-[#5B7A8B]/20",
    icon: Hourglass,
  },
  complement: {
    label: "Complément",
    className: "bg-[#C4704B]/10 text-[#C4704B] border-[#C4704B]/20",
    icon: Paperclip,
  },
  incomplet: {
    label: "Incomplet",
    className: "bg-muted text-muted-foreground border-muted-foreground/20",
    icon: AlertTriangle,
  },
};

/** KPI card config — total card + per-status cards */
export const STATS_CARD_CONFIG: Array<{
  key: keyof DossierStats;
  label: string;
  icon: LucideIcon;
  color: string; // Tailwind bg for icon circle
  textColor: string;
}> = [
  { key: "total", label: "Total dossiers", icon: FolderOpen, color: "bg-[#C4704B]/10", textColor: "text-[#C4704B]" },
  { key: "en_cours", label: "En cours", icon: Clock, color: "bg-[#C4944B]/10", textColor: "text-[#C4944B]" },
  { key: "valide", label: "Validés", icon: CheckCircle, color: "bg-[#5F8B5F]/10", textColor: "text-[#5F8B5F]" },
  { key: "rejete", label: "Rejetés", icon: XCircle, color: "bg-[#B5544B]/10", textColor: "text-[#B5544B]" },
  { key: "en_attente", label: "En attente", icon: Hourglass, color: "bg-[#5B7A8B]/10", textColor: "text-[#5B7A8B]" },
  { key: "complement", label: "Complément", icon: Paperclip, color: "bg-[#C4704B]/10", textColor: "text-[#C4704B]" },
  { key: "incomplet", label: "Incomplets", icon: AlertTriangle, color: "bg-muted", textColor: "text-muted-foreground" },
];

export const SYNC_STATUS_CONFIG: Record<
  SyncStatus,
  { label: string; className: string; icon: LucideIcon }
> = {
  pending: {
    label: "En attente",
    className: "bg-[#C4944B]/10 text-[#C4944B] border-0",
    icon: Clock,
  },
  running: {
    label: "En cours",
    className: "bg-[#5B7A8B]/10 text-[#5B7A8B] border-0",
    icon: Loader2,
  },
  completed: {
    label: "Terminé",
    className: "bg-[#5F8B5F]/10 text-[#5F8B5F] border-0",
    icon: CheckCircle2,
  },
  failed: {
    label: "Échoué",
    className: "bg-[#B5544B]/10 text-[#B5544B] border-0",
    icon: XOctagon,
  },
};

/** French labels for dossier fields (used in timeline) */
export const DOSSIER_FIELD_LABELS: Record<string, string> = {
  numero: "Numéro",
  statut: "Statut",
  type_projet: "Type de projet",
  raison_sociale: "Raison sociale",
  montant_investissement: "Montant investissement",
  region: "Région",
  secteur: "Secteur",
  date_depot: "Date de dépôt",
  date_derniere_maj: "Dernière mise à jour",
  observations: "Observations",
  contact_id: "Contact",
};

/** Target fields for column mapping in import wizard */
export const MAPPABLE_FIELDS: Array<{ value: string; label: string; required?: boolean }> = [
  { value: "numero", label: "Numéro de dossier", required: true },
  { value: "statut", label: "Statut" },
  { value: "type_projet", label: "Type de projet" },
  { value: "raison_sociale", label: "Raison sociale" },
  { value: "montant_investissement", label: "Montant investissement" },
  { value: "region", label: "Région" },
  { value: "secteur", label: "Secteur" },
  { value: "date_depot", label: "Date de dépôt" },
  { value: "date_derniere_maj", label: "Dernière mise à jour" },
  { value: "observations", label: "Observations" },
  { value: "phone", label: "Téléphone contact" },
];
