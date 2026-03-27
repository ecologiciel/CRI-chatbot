export type KBDocumentStatus =
  | "pending"
  | "indexing"
  | "indexed"
  | "error";

export interface KBDocument {
  id: string;
  title: string;
  source_url: string | null;
  category: string | null;
  language: string;
  content_hash: string | null;
  file_path: string | null;
  file_size: number | null;
  chunk_count: number;
  status: KBDocumentStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export type UnansweredQuestionStatus =
  | "pending"
  | "approved"
  | "modified"
  | "rejected"
  | "injected";

export interface UnansweredQuestion {
  id: string;
  question: string;
  language: string;
  frequency: number;
  proposed_answer: string | null;
  status: UnansweredQuestionStatus;
  reviewed_by: string | null;
  review_note: string | null;
  source_conversation_id: string | null;
  created_at: string;
  updated_at: string;
}
