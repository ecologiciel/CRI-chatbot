export type KBDocumentStatus =
  | "pending"
  | "pending_validation"
  | "indexing"
  | "indexed"
  | "rejected"
  | "expired"
  | "error";

export interface KBDocument {
  id: string;
  title: string;
  source_url: string | null;
  source_authority: string | null;
  source_reference: string | null;
  source_version: string | null;
  published_at: string | null;
  verified_at: string | null;
  expires_at: string | null;
  validated_by: string | null;
  validated_at: string | null;
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

export interface RAGEvaluationRun {
  id: string;
  case_count: number;
  metrics: Record<string, number | string>;
  triggered_by: string | null;
  created_at: string;
}
