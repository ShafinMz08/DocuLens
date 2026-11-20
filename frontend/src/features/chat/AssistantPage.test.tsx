import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AssistantPage } from "./AssistantPage";
import { api, ApiError } from "../../lib/api";
import type { ChatResponse } from "../../lib/types";
import { deferred, renderWithProviders } from "../../test/utils";

vi.mock("../../lib/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      listConversations: vi.fn(),
      getConversation: vi.fn(),
      chat: vi.fn(),
      listDocuments: vi.fn(),
    },
  };
});

const conversation = {
  id: "conv-1",
  title: "Revenue questions",
  created_at: "2026-11-20T10:00:00Z",
  updated_at: "2026-11-20T10:05:00Z",
  message_count: 2,
  messages: [
    {
      id: "m1",
      role: "user" as const,
      content: "What was revenue?",
      sources: null,
      llm_provider: null,
      llm_model: null,
      created_at: "2026-11-20T10:00:00Z",
    },
    {
      id: "m2",
      role: "assistant" as const,
      content: "Revenue grew 12% [1].",
      sources: [
        {
          chunk_id: "c1",
          document_id: "d1",
          document_name: "report.pdf",
          chunk_index: 0,
          page_number: 2,
          excerpt: "excerpt",
          score: 0.9,
        },
      ],
      llm_provider: "gemini",
      llm_model: "gemini-3.8-flash",
      created_at: "2026-11-20T10:00:01Z",
    },
  ],
};

describe("AssistantPage", () => {
  beforeEach(() => {
    vi.mocked(api.listConversations).mockReset().mockResolvedValue([
      {
        id: "conv-1",
        title: "Revenue questions",
        created_at: conversation.created_at,
        updated_at: conversation.updated_at,
        message_count: 2,
      },
    ]);
    vi.mocked(api.getConversation).mockReset().mockImplementation((id) =>
      Promise.resolve(
        id === "conv-new"
          ? {
              ...conversation,
              id: "conv-new",
              messages: [
                {
                  id: "mn1",
                  role: "user" as const,
                  content: "hi there",
                  sources: null,
                  llm_provider: null,
                  llm_model: null,
                  created_at: "2026-11-20T10:10:00Z",
                },
                {
                  id: "mn2",
                  role: "assistant" as const,
                  content: "It grew 12%.",
                  sources: [],
                  llm_provider: "gemini",
                  llm_model: "gemini-3.8-flash",
                  created_at: "2026-11-20T10:10:01Z",
                },
              ],
            }
          : conversation,
      ),
    );
    vi.mocked(api.chat).mockReset();
    vi.mocked(api.listDocuments).mockReset().mockResolvedValue({
      items: [],
      total: 0,
      skip: 0,
      limit: 100,
    });
  });

  it("lists conversations in the sidebar", async () => {
    renderWithProviders(<AssistantPage />);
    expect(await screen.findByText("Revenue questions")).toBeInTheDocument();
  });

  it("loads a conversation and its messages on selection", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AssistantPage />);
    await user.click(await screen.findByText("Revenue questions"));
    await waitFor(() =>
      expect(api.getConversation).toHaveBeenCalledWith("conv-1"),
    );
    expect(await screen.findByText("What was revenue?")).toBeInTheDocument();
    expect(screen.getByText(/Revenue grew 12%/)).toBeInTheDocument();
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
  });

  it("submits a new question and appends the answer", async () => {
    const user = userEvent.setup();
    vi.mocked(api.chat).mockResolvedValue({
      answer: "It grew 12%.",
      conversation_id: "conv-new",
      citations: [],
      provider: "gemini",
      model: "gemini-3.8-flash",
      retrieved_chunks: 3,
    });
    renderWithProviders(<AssistantPage />);
    await user.type(screen.getByLabelText("Question"), "hi there{Enter}");
    await waitFor(() =>
      expect(api.chat).toHaveBeenCalledWith({
        question: "hi there",
        conversation_id: null,
        document_id: null,
      }),
    );
    expect(await screen.findByText("It grew 12%.")).toBeInTheDocument();
    expect(screen.getByText("hi there")).toBeInTheDocument();
  });

  it("blocks conversation switching while a chat response is pending", async () => {
    const user = userEvent.setup();
    const d = deferred<ChatResponse>();

    const conv2 = {
      ...conversation,
      id: "conv-2",
      title: "Second chat",
      messages: [],
    };
    vi.mocked(api.listConversations).mockResolvedValue([
      {
        id: "conv-1",
        title: "Revenue questions",
        created_at: conversation.created_at,
        updated_at: conversation.updated_at,
        message_count: 2,
      },
      {
        id: "conv-2",
        title: "Second chat",
        created_at: conversation.created_at,
        updated_at: conversation.updated_at,
        message_count: 0,
      },
    ]);
    vi.mocked(api.getConversation).mockImplementation((id) =>
      Promise.resolve(id === "conv-2" ? conv2 : conversation),
    );
    vi.mocked(api.chat).mockReturnValue(d.promise);

    renderWithProviders(<AssistantPage />);

    // Open the first conversation and ask a follow-up.
    await user.click(await screen.findByText("Revenue questions"));
    expect(await screen.findByText("What was revenue?")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Question"), "follow up{Enter}");
    await waitFor(() =>
      expect(api.chat).toHaveBeenCalledWith({
        question: "follow up",
        conversation_id: "conv-1",
        document_id: null,
      }),
    );

    // While pending: selection controls are disabled.
    expect(
      screen.getByRole("button", { name: /new conversation/i }),
    ).toBeDisabled();
    const secondChat = screen.getByText("Second chat");
    expect(secondChat.closest("button")).toBeDisabled();

    // Clicking it must not switch conversations.
    await user.click(secondChat);
    expect(api.getConversation).not.toHaveBeenCalledWith("conv-2");
    expect(screen.getByText("What was revenue?")).toBeInTheDocument();

    // Resolve: the answer lands on the original conversation.
    await act(async () => {
      d.resolve({
        answer: "Follow up answer.",
        conversation_id: "conv-1",
        citations: [],
        provider: "gemini",
        model: "gemini-3.8-flash",
        retrieved_chunks: 1,
      });
    });
    expect(await screen.findByText("Follow up answer.")).toBeInTheDocument();

    // Controls are usable again.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /new conversation/i }),
      ).toBeEnabled(),
    );
    await user.click(screen.getByText("Second chat"));
    await waitFor(() =>
      expect(api.getConversation).toHaveBeenCalledWith("conv-2"),
    );
  });

  it("shows an error when the chat request fails", async () => {
    const user = userEvent.setup();
    vi.mocked(api.chat).mockRejectedValue(
      new ApiError(502, "The AI service is currently unavailable. Please try again later."),
    );
    renderWithProviders(<AssistantPage />);
    await user.type(screen.getByLabelText("Question"), "hello{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("unavailable");
  });
});
