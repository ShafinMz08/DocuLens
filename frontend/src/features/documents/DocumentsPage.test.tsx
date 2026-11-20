import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DocumentsPage } from "./DocumentsPage";
import { api, ApiError } from "../../lib/api";
import type { Document, ProcessingResult } from "../../lib/types";
import { deferred, renderWithProviders } from "../../test/utils";

vi.mock("../../lib/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      listDocuments: vi.fn(),
      uploadDocument: vi.fn(),
      processDocument: vi.fn(),
      embedDocument: vi.fn(),
    },
  };
});

function makeDoc(overrides: Partial<Document> = {}): Document {
  return {
    id: "doc-1",
    original_filename: "report.pdf",
    content_type: "application/pdf",
    file_size_bytes: 2048,
    status: "uploaded",
    embedding_status: "pending",
    embedding_error: null,
    created_at: "2026-11-20T10:00:00Z",
    updated_at: "2026-11-20T10:00:00Z",
    ...overrides,
  };
}

function listResponse(items: Document[]) {
  return { items, total: items.length, skip: 0, limit: 20 };
}

describe("DocumentsPage", () => {
  beforeEach(() => {
    vi.mocked(api.listDocuments).mockReset();
    vi.mocked(api.processDocument).mockReset();
    vi.mocked(api.embedDocument).mockReset();
  });

  it("shows an empty state when there are no documents", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue(listResponse([]));
    renderWithProviders(<DocumentsPage />);
    expect(await screen.findByText("No documents yet")).toBeInTheDocument();
  });

  it("shows a loading skeleton while fetching", () => {
    vi.mocked(api.listDocuments).mockReturnValue(new Promise(() => {}));
    renderWithProviders(<DocumentsPage />);
    expect(screen.getByLabelText("Loading documents")).toBeInTheDocument();
  });

  it("renders documents with status badges", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue(
      listResponse([
        makeDoc({ id: "a", original_filename: "a.pdf", status: "completed", embedding_status: "completed" }),
        makeDoc({ id: "b", original_filename: "b.txt", content_type: "text/plain", status: "failed" }),
      ]),
    );
    renderWithProviders(<DocumentsPage />);
    expect(await screen.findByText("a.pdf")).toBeInTheDocument();
    expect(screen.getByText("b.txt")).toBeInTheDocument();
    expect(screen.getByText("Processed")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("Embedded")).toBeInTheDocument();
  });

  it("shows an error state with retry when listing fails", async () => {
    vi.mocked(api.listDocuments).mockRejectedValue(
      new ApiError(500, "boom"),
    );
    renderWithProviders(<DocumentsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    vi.mocked(api.listDocuments).mockResolvedValue(listResponse([]));
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() =>
      expect(screen.getByText("No documents yet")).toBeInTheDocument(),
    );
  });

  it("processes an uploaded document", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listDocuments).mockResolvedValue(listResponse([makeDoc()]));
    vi.mocked(api.processDocument).mockResolvedValue({
      document_id: "doc-1",
      document_status: "completed",
      attempt_number: 1,
      processing_status: "completed",
      chunks_created: 12,
      error_message: null,
      embedding_status: "completed",
      embedded_chunks: 12,
      total_chunks: 12,
      skipped_chunks: 0,
      embedding_error: null,
    });
    renderWithProviders(<DocumentsPage />);
    await user.click(await screen.findByRole("button", { name: /^process$/i }));
    await waitFor(() =>
      expect(api.processDocument).toHaveBeenCalledWith("doc-1"),
    );
  });

  it("offers embedding retry when embedding failed", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listDocuments).mockResolvedValue(
      listResponse([
        makeDoc({
          status: "completed",
          embedding_status: "failed",
          embedding_error: "Embedding generation failed",
        }),
      ]),
    );
    vi.mocked(api.embedDocument).mockResolvedValue({
      document_id: "doc-1",
      embedding_status: "completed",
      embedding_model: "m@1",
      total_chunks: 5,
      embedded_chunks: 5,
      skipped_chunks: 0,
      error_message: null,
    });
    renderWithProviders(<DocumentsPage />);
    await user.click(
      await screen.findByRole("button", { name: /retry embedding/i }),
    );
    await waitFor(() =>
      expect(api.embedDocument).toHaveBeenCalledWith("doc-1"),
    );
  });

  it("disables all document actions while a process request is pending", async () => {
    const user = userEvent.setup();
    const d = deferred<ProcessingResult>();
    vi.mocked(api.listDocuments).mockResolvedValue(
      listResponse([
        makeDoc({ id: "a", original_filename: "a.pdf" }),
        makeDoc({ id: "b", original_filename: "b.pdf" }),
      ]),
    );
    vi.mocked(api.processDocument).mockReturnValue(d.promise);
    renderWithProviders(<DocumentsPage />);

    const processButtons = await screen.findAllByRole("button", {
      name: /^process$/i,
    });
    expect(processButtons).toHaveLength(2);
    await user.click(processButtons[0]);

    await waitFor(() => {
      for (const b of screen.getAllByRole("button", { name: /^process$/i })) {
        expect(b).toBeDisabled();
      }
    });
    // Only the active row shows a spinner.
    const [active, other] = screen.getAllByRole("button", {
      name: /^process$/i,
    });
    expect(active.querySelector(".animate-spin")).not.toBeNull();
    expect(other.querySelector(".animate-spin")).toBeNull();

    await act(async () => {
      d.resolve({
        document_id: "a",
        document_status: "completed",
        attempt_number: 1,
        processing_status: "completed",
        chunks_created: 3,
        error_message: null,
        embedding_status: "completed",
        embedded_chunks: 3,
        total_chunks: 3,
        skipped_chunks: 0,
        embedding_error: null,
      });
    });
    await waitFor(() => {
      // After invalidation the mocked list still returns uploaded docs,
      // so buttons must be re-enabled.
      for (const b of screen.getAllByRole("button", { name: /^process$/i })) {
        expect(b).toBeEnabled();
      }
    });
  });

  it("disables other rows' actions during an embedding retry", async () => {
    const user = userEvent.setup();
    const d = deferred<{
      document_id: string;
      embedding_status: "completed";
      embedding_model: string;
      total_chunks: number;
      embedded_chunks: number;
      skipped_chunks: number;
      error_message: null;
    }>();
    vi.mocked(api.listDocuments).mockResolvedValue(
      listResponse([
        makeDoc({
          id: "a",
          original_filename: "a.pdf",
          status: "completed",
          embedding_status: "failed",
        }),
        makeDoc({ id: "b", original_filename: "b.pdf" }),
      ]),
    );
    vi.mocked(api.embedDocument).mockReturnValue(d.promise);
    renderWithProviders(<DocumentsPage />);

    const retryButtons = await screen.findAllByRole("button", {
      name: /retry embedding/i,
    });
    expect(retryButtons).toHaveLength(1);
    await user.click(retryButtons[0]);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /retry embedding/i }),
      ).toBeDisabled();
      expect(screen.getByRole("button", { name: /^process$/i })).toBeDisabled();
    });

    await act(async () => {
      d.resolve({
        document_id: "a",
        embedding_status: "completed",
        embedding_model: "m@1",
        total_chunks: 2,
        embedded_chunks: 2,
        skipped_chunks: 0,
        error_message: null,
      });
    });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /^process$/i }),
      ).toBeEnabled();
    });
  });

  it("re-enables actions after a failed process request", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listDocuments).mockResolvedValue(listResponse([makeDoc()]));
    vi.mocked(api.processDocument).mockRejectedValue(
      new ApiError(409, "already processing"),
    );
    renderWithProviders(<DocumentsPage />);
    const btn = await screen.findByRole("button", { name: /^process$/i });
    await user.click(btn);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "already processing",
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /^process$/i }),
      ).toBeEnabled(),
    );
  });

  it("shows conflict errors from the process endpoint", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listDocuments).mockResolvedValue(listResponse([makeDoc()]));
    vi.mocked(api.processDocument).mockRejectedValue(
      new ApiError(409, "Document is already being processed"),
    );
    renderWithProviders(<DocumentsPage />);
    await user.click(await screen.findByRole("button", { name: /^process$/i }));
    expect(
      await screen.findByText(/already being processed/),
    ).toBeInTheDocument();
  });
});
