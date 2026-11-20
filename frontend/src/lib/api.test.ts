import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { api, ApiError, errorMessage } from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls the correct endpoint for listing documents", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [], total: 0, skip: 0, limit: 20 }),
    );
    await api.listDocuments(40, 20);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/documents?skip=40&limit=20",
      undefined,
    );
  });

  it("uploads a file as multipart form data", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "d1" }, 201));
    const file = new File(["hello"], "a.txt", { type: "text/plain" });
    await api.uploadDocument(file);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/documents/upload");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("posts chat requests with JSON body", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        answer: "ok",
        conversation_id: "c1",
        citations: [],
        provider: "gemini",
        model: "m",
        retrieved_chunks: 0,
      }),
    );
    await api.chat({ question: "hi", document_id: "d1" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/chat");
    expect(JSON.parse(init.body as string)).toEqual({
      question: "hi",
      document_id: "d1",
    });
  });

  it("throws ApiError with backend detail on 409 conflict", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "Document is already being processed" }, 409),
    );
    await expect(api.processDocument("d1")).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      detail: "Document is already being processed",
    });
  });

  it("handles FastAPI validation error arrays", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { detail: [{ msg: "field required" }, { msg: "bad value" }] },
        422,
      ),
    );
    try {
      await api.search({ query: "x", top_k: 10 });
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).detail).toBe("field required; bad value");
    }
  });

  it("maps network failures to status 0", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    try {
      await api.health();
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).isNetworkError).toBe(true);
    }
  });

  it("errorMessage returns friendly text for network errors", () => {
    expect(errorMessage(new ApiError(0, "boom"))).toContain("backend");
    expect(errorMessage(new ApiError(502, "AI unavailable"))).toBe(
      "AI unavailable",
    );
    expect(errorMessage(new Error("x"))).toBe("x");
  });
});
