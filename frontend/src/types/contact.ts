export type OptInStatus = "opted_in" | "opted_out" | "pending";
export type ContactSource = "whatsapp" | "import_csv" | "manual";
export type ContactLanguage = "fr" | "ar" | "en";

export interface Contact {
  id: string;
  phone: string;
  name: string | null;
  language: ContactLanguage;
  cin: string | null;
  opt_in_status: OptInStatus;
  tags: string[];
  source: ContactSource;
  created_at: string;
  updated_at: string;
}

export interface ContactDetail extends Contact {
  conversation_count: number;
  last_interaction: string | null;
}

export interface ContactCreatePayload {
  phone: string;
  name?: string;
  language?: ContactLanguage;
  cin?: string;
  tags?: string[];
  source?: ContactSource;
}

export interface ContactUpdatePayload {
  name?: string;
  language?: ContactLanguage;
  cin?: string;
  opt_in_status?: OptInStatus;
  tags?: string[];
}

export interface ImportResult {
  created: number;
  skipped: number;
  errors: Array<{ row: number; phone: string | null; error: string }>;
}
