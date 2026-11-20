import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatThread, type ThreadMessage } from "./ChatThread";
import type { Citation } from "../../lib/types";

const citation: Citation = {
  chunk_id: "chunk-1",
  document_id: "doc-1",
  document_name: "annual-report.pdf",
  chunk_index: 3,
  page_number: 7,
  excerpt: "Revenue grew 12% year over year.",
  score: 0.83,
};

const assistantMessage: ThreadMessage = {
  id: "m1",
  role: "assistant",
  content: "Revenue grew 12% [1] according to the report.",
  citations: [citation],
  provider: "gemini",
  model: "gemini-3.8-flash",
};

function renderThread(overrides: Partial<Parameters<typeof ChatThread>[0]> = {}) {
  const onSend = vi.fn();
  render(
    <ChatThread
      messages={[assistantMessage]}
      isSending={false}
      error={null}
      onSend={onSend}
      {...overrides}
    />,
  );
  return { onSend };
}

describe("ChatThread", () => {
  it("renders user and assistant messages distinctly", () => {
    renderThread({
      messages: [
        { id: "u1", role: "user", content: "What was revenue?" },
        assistantMessage,
      ],
    });
    expect(screen.getByText("What was revenue?")).toBeInTheDocument();
    expect(screen.getByText(/according to the report/)).toBeInTheDocument();
  });

  it("sends on Enter and keeps Shift+Enter for newlines", async () => {
    const user = userEvent.setup();
    const { onSend } = renderThread();
    const box = screen.getByLabelText("Question");

    await user.type(box, "line one{Shift>}{Enter}{/Shift}line two");
    expect(onSend).not.toHaveBeenCalled();
    expect(box).toHaveValue("line one\nline two");

    await user.type(box, "{Enter}");
    expect(onSend).toHaveBeenCalledWith("line one\nline two");
  });

  it("does not send empty or whitespace questions", async () => {
    const user = userEvent.setup();
    const { onSend } = renderThread();
    const box = screen.getByLabelText("Question");
    await user.type(box, "   ");
    await user.keyboard("{Enter}");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("disables the composer while a request is in flight", () => {
    renderThread({ isSending: true });
    expect(screen.getByLabelText("Question")).toBeDisabled();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });

  it("renders citations with document, page, excerpt and score", () => {
    renderThread();
    expect(screen.getByText("Sources")).toBeInTheDocument();
    expect(screen.getByText("annual-report.pdf")).toBeInTheDocument();
    expect(screen.getByText(/page 7/)).toBeInTheDocument();
    expect(screen.getByText(/Revenue grew 12% year over year/)).toBeInTheDocument();
    expect(screen.getByText(/similarity 0\.830/)).toBeInTheDocument();
  });

  it("links inline [n] markers to citation cards", () => {
    renderThread();
    const ref = screen.getByRole("button", { name: "Jump to citation 1" });
    expect(ref).toBeInTheDocument();
    expect(document.getElementById("m1-citation-1")).not.toBeNull();
  });

  it("shows provider and model metadata unobtrusively", () => {
    renderThread();
    expect(screen.getByText(/gemini · gemini-3\.8-flash/)).toBeInTheDocument();
  });

  it("shows error messages", () => {
    renderThread({ error: "The AI service is currently unavailable." });
    expect(screen.getByRole("alert")).toHaveTextContent("unavailable");
  });

  it("shows an empty state with no messages", () => {
    renderThread({ messages: [] });
    expect(screen.getByText("Ask about your documents")).toBeInTheDocument();
  });
});
