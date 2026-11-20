import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SearchPage } from "./SearchPage";
import { api, ApiError } from "../../lib/api";
import { renderWithProviders } from "../../test/utils";

vi.mock("../../lib/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...mod,
    api: { ...mod.api, search: vi.fn(), listDocuments: vi.fn() },
  };
});

const searchResponse = {
  query: "revenue growth",
  results: [
    {
      chunk_id: "chunk-1",
      document_id: "doc-1",
      document_name: "annual.pdf",
      chunk_index: 2,
      page_number: 5,
      content: "Revenue grew 12% in fiscal 2025.",
      score: 0.9123,
    },
  ],
};

describe("SearchPage", () => {
  beforeEach(() => {
    vi.mocked(api.search).mockReset();
    vi.mocked(api.listDocuments).mockReset().mockResolvedValue({
      items: [],
      total: 0,
      skip: 0,
      limit: 100,
    });
  });

  it("renders the search form and empty state", () => {
    renderWithProviders(<SearchPage />);
    expect(screen.getByLabelText("Search query")).toBeInTheDocument();
    expect(screen.getByText("Search your documents")).toBeInTheDocument();
  });

  it("runs a search and renders result cards", async () => {
    const user = userEvent.setup();
    vi.mocked(api.search).mockResolvedValue(searchResponse);
    renderWithProviders(<SearchPage />);
    await user.type(screen.getByLabelText("Search query"), "revenue growth");
    await user.click(screen.getByRole("button", { name: /^search$/i }));
    await waitFor(() =>
      expect(api.search).toHaveBeenCalledWith({
        query: "revenue growth",
        top_k: 10,
        document_id: null,
      }),
    );
    expect(await screen.findByText("annual.pdf")).toBeInTheDocument();
    expect(screen.getByText(/Revenue grew 12%/)).toBeInTheDocument();
    expect(screen.getByText(/similarity 0\.912/)).toBeInTheDocument();
    expect(screen.getByText(/page 5/)).toBeInTheDocument();
  });

  it("shows a no-results state", async () => {
    const user = userEvent.setup();
    vi.mocked(api.search).mockResolvedValue({ query: "xyz", results: [] });
    renderWithProviders(<SearchPage />);
    await user.type(screen.getByLabelText("Search query"), "xyz");
    await user.click(screen.getByRole("button", { name: /^search$/i }));
    expect(await screen.findByText("No matching chunks")).toBeInTheDocument();
  });

  it("shows an error state on failure", async () => {
    const user = userEvent.setup();
    vi.mocked(api.search).mockRejectedValue(new ApiError(500, "Search failed"));
    renderWithProviders(<SearchPage />);
    await user.type(screen.getByLabelText("Search query"), "q");
    await user.click(screen.getByRole("button", { name: /^search$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Search failed");
  });

  it("sends the selected top_k value", async () => {
    const user = userEvent.setup();
    vi.mocked(api.search).mockResolvedValue(searchResponse);
    renderWithProviders(<SearchPage />);
    await user.type(screen.getByLabelText("Search query"), "revenue");
    await user.selectOptions(screen.getByLabelText("Number of results"), "20");
    await user.click(screen.getByRole("button", { name: /^search$/i }));
    await waitFor(() =>
      expect(api.search).toHaveBeenCalledWith({
        query: "revenue",
        top_k: 20,
        document_id: null,
      }),
    );
  });

  it("sends the selected document filter", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listDocuments).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          original_filename: "annual.pdf",
          content_type: "application/pdf",
          file_size_bytes: 100,
          status: "completed",
          embedding_status: "completed",
          embedding_error: null,
          created_at: "2026-11-20T10:00:00Z",
          updated_at: "2026-11-20T10:00:00Z",
        },
      ],
      total: 1,
      skip: 0,
      limit: 100,
    });
    vi.mocked(api.search).mockResolvedValue(searchResponse);
    renderWithProviders(<SearchPage />);
    await user.type(screen.getByLabelText("Search query"), "revenue");
    await user.selectOptions(
      screen.getByLabelText("Filter by document"),
      "annual.pdf",
    );
    await user.click(screen.getByRole("button", { name: /^search$/i }));
    await waitFor(() =>
      expect(api.search).toHaveBeenCalledWith({
        query: "revenue",
        top_k: 10,
        document_id: "doc-1",
      }),
    );
  });

  it("does not submit an empty query", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SearchPage />);
    expect(screen.getByRole("button", { name: /^search$/i })).toBeDisabled();
    await user.type(screen.getByLabelText("Search query"), "   ");
    expect(screen.getByRole("button", { name: /^search$/i })).toBeDisabled();
  });
});
