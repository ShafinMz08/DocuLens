import type {
  ChatRequest,
  ChatResponse,
  Conversation,
  ConversationSummary,
  Document,
  DocumentListResponse,
  EmbeddingResult,
  HealthResponse,
  ProcessingResult,
  SearchRequest,
  SearchResponse,
} from "./types";

/**
 * Base URL for backend calls. Empty string means "same origin", which is the
 * default for the Vite dev proxy (and any same-origin deployment). Set
 * VITE_API_BASE_URL to point at a backend on another origin.
 */
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch (cause) {
    throw new ApiError(
      0,
      cause instanceof Error ? cause.message : "Network request failed",
    );
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        // FastAPI/Pydantic validation error list
        detail = body.detail
          .map((item: { msg?: string }) => item?.msg)
          .filter(Boolean)
          .join("; ") || detail;
      }
    } catch {
      // Non-JSON error body; keep the status-based message.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const api = {
  health: () => request<HealthResponse>("/health"),

  listDocuments: (skip = 0, limit = 20) =>
    request<DocumentListResponse>(
      `/api/v1/documents?skip=${skip}&limit=${limit}`,
    ),

  uploadDocument: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Document>("/api/v1/documents/upload", {
      method: "POST",
      body: form,
    });
  },

  processDocument: (documentId: string) =>
    request<ProcessingResult>(
      `/api/v1/documents/${documentId}/process`,
      jsonInit("POST", {}),
    ),

  embedDocument: (documentId: string) =>
    request<EmbeddingResult>(
      `/api/v1/documents/${documentId}/embed`,
      jsonInit("POST", {}),
    ),

  chat: (payload: ChatRequest) =>
    request<ChatResponse>("/api/v1/chat", jsonInit("POST", payload)),

  listConversations: (skip = 0, limit = 50) =>
    request<ConversationSummary[]>(
      `/api/v1/conversations?skip=${skip}&limit=${limit}`,
    ),

  getConversation: (conversationId: string) =>
    request<Conversation>(`/api/v1/conversations/${conversationId}`),

  search: (payload: SearchRequest) =>
    request<SearchResponse>("/api/v1/search", jsonInit("POST", payload)),
};

/** Human-readable message for an unknown thrown value. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.isNetworkError) {
      return "Cannot reach the DocuLens backend. Check that the server is running.";
    }
    return error.detail;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "An unexpected error occurred.";
}
