// Typed mirrors of the backend Pydantic schemas (backend/app/schemas).

export type DocumentStatus = "uploaded" | "processing" | "completed" | "failed";
export type EmbeddingStatus = "pending" | "processing" | "completed" | "failed";
export type ProcessingStatus = "processing" | "completed" | "failed";
export type MessageRole = "user" | "assistant";

export interface Document {
  id: string;
  original_filename: string;
  content_type: string;
  file_size_bytes: number;
  status: DocumentStatus;
  embedding_status: EmbeddingStatus;
  embedding_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentListResponse {
  items: Document[];
  total: number;
  skip: number;
  limit: number;
}

export interface ProcessingResult {
  document_id: string;
  document_status: DocumentStatus;
  attempt_number: number;
  processing_status: ProcessingStatus;
  chunks_created: number;
  error_message: string | null;
  embedding_status: EmbeddingStatus | null;
  embedded_chunks: number;
  total_chunks: number | null;
  skipped_chunks: number | null;
  embedding_error: string | null;
}

export interface EmbeddingResult {
  document_id: string;
  embedding_status: EmbeddingStatus;
  embedding_model: string;
  total_chunks: number;
  embedded_chunks: number;
  skipped_chunks: number;
  error_message: string | null;
}

export interface Citation {
  chunk_id: string;
  document_id: string;
  document_name: string;
  chunk_index: number;
  page_number: number | null;
  excerpt: string | null;
  score: number;
}

export interface ChatRequest {
  question: string;
  conversation_id?: string | null;
  document_id?: string | null;
}

export interface ChatResponse {
  answer: string;
  conversation_id: string;
  citations: Citation[];
  provider: string | null;
  model: string | null;
  retrieved_chunks: number;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  sources: Citation[] | null;
  llm_provider: string | null;
  llm_model: string | null;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface Conversation extends Omit<ConversationSummary, "message_count"> {
  messages: Message[];
}

export interface SearchRequest {
  query: string;
  top_k: number;
  document_id?: string | null;
}

export interface SearchResultItem {
  chunk_id: string;
  document_id: string;
  document_name: string;
  chunk_index: number;
  page_number: number | null;
  content: string;
  score: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResultItem[];
}

export interface HealthResponse {
  status: string;
  [key: string]: unknown;
}
