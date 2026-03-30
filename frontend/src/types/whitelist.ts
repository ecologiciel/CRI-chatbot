export interface WhitelistEntry {
  id: string;
  phone: string;
  label: string | null;
  note: string | null;
  is_active: boolean;
  added_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface WhitelistCreatePayload {
  phone: string;
  label?: string;
  note?: string;
}

export interface WhitelistUpdatePayload {
  label?: string;
  note?: string;
  is_active?: boolean;
}
