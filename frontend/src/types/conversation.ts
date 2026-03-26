export type ConversationStatus =
  | "active"
  | "waiting"
  | "escalated"
  | "closed"
  | "archived";

export type MessageDirection = "inbound" | "outbound";

export type MessageType =
  | "text"
  | "image"
  | "audio"
  | "interactive"
  | "template"
  | "system";

export interface Conversation {
  id: string;
  contact_name: string | null;
  contact_phone: string;
  agent_type: "public" | "internal";
  status: ConversationStatus;
  last_message: string;
  last_message_at: string;
  unread_count: number;
}

export interface Message {
  id: string;
  direction: MessageDirection;
  type: MessageType;
  content: string;
  timestamp: string;
  is_read: boolean;
}
