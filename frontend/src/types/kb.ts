export type KBDocumentStatus =
  | "pending"
  | "processing"
  | "indexed"
  | "failed"
  | "archived";

export interface KBDocument {
  id: string;
  title: string;
  category: string | null;
  language: string;
  status: KBDocumentStatus;
  chunk_count: number;
  file_size: number | null;
  created_at: string;
  updated_at: string;
}

export type UnansweredQuestionStatus =
  | "pending"
  | "ai_proposed"
  | "approved"
  | "rejected"
  | "edited";

export interface UnansweredQuestion {
  id: string;
  question: string;
  language: string;
  frequency: number;
  proposed_answer: string | null;
  status: UnansweredQuestionStatus;
  created_at: string;
}
