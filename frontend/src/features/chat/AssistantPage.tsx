import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../../lib/api";
import type { Citation, Message } from "../../lib/types";
import { Select } from "../../components/ui/select";
import { ConversationSidebar } from "./ConversationSidebar";
import { ChatThread, type ThreadMessage } from "./ChatThread";
import { LoadingState } from "../../components/ui/states";

function toThreadMessage(m: Message): ThreadMessage {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    citations: (m.sources ?? null) as Citation[] | null,
    provider: m.llm_provider,
    model: m.llm_model,
  };
}

export function AssistantPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [sendError, setSendError] = useState<string | null>(null);
  const [documentId, setDocumentId] = useState<string>("");

  const conversationQuery = useQuery({
    queryKey: ["conversation", selectedId],
    queryFn: () => api.getConversation(selectedId!),
    enabled: selectedId !== null,
  });

  useEffect(() => {
    if (selectedId === null) {
      setSendError(null);
      return;
    }
    if (conversationQuery.data) {
      setMessages(conversationQuery.data.messages.map(toThreadMessage));
      setSendError(null);
    }
  }, [selectedId, conversationQuery.data]);

  const documentsQuery = useQuery({
    queryKey: ["documents", "assistant-context"],
    queryFn: () => api.listDocuments(0, 100),
  });

  const usableDocuments = useMemo(
    () =>
      (documentsQuery.data?.items ?? []).filter(
        (d) => d.status === "completed" && d.embedding_status === "completed",
      ),
    [documentsQuery.data],
  );

  const selectedDoc = usableDocuments.find((d) => d.id === documentId) ?? null;

  const chatMutation = useMutation({
    mutationFn: (question: string) =>
      api.chat({
        question,
        conversation_id: selectedId,
        document_id: documentId || null,
      }),
    onSuccess: (response, question) => {
      setSendError(null);
      setSelectedId(response.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          id: `local-user-${Date.now()}`,
          role: "user",
          content: question,
        },
        {
          id: `local-assistant-${Date.now()}`,
          role: "assistant",
          content: response.answer,
          citations: response.citations,
          provider: response.provider,
          model: response.model,
        },
      ]);
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (err) => setSendError(errorMessage(err)),
  });

  const handleSend = (question: string) => {
    chatMutation.mutate(question);
  };

  const handleSelect = (id: string | null) => {
    // Defensive guard: never switch conversations while a response is pending.
    if (chatMutation.isPending) return;
    if (id !== selectedId) setMessages([]);
    setSelectedId(id);
  };

  return (
    <div className="flex h-full min-h-0">
      <ConversationSidebar
        selectedId={selectedId}
        onSelect={handleSelect}
        selectionDisabled={chatMutation.isPending}
      />

      <section className="flex min-w-0 flex-1 flex-col" aria-label="Chat">
        <div className="flex flex-wrap items-center gap-3 border-b bg-card/60 px-4 py-2.5 backdrop-blur">
          <label
            htmlFor="document-context"
            className="text-xs font-medium text-muted-foreground"
          >
            Document context
          </label>
          <div className="w-64 max-w-full">
            <Select
              id="document-context"
              value={documentId}
              onChange={(e) => setDocumentId(e.target.value)}
            >
              <option value="">All documents (global search)</option>
              {usableDocuments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.original_filename}
                </option>
              ))}
            </Select>
          </div>
          {usableDocuments.length === 0 && !documentsQuery.isPending && (
            <span className="text-xs text-muted-foreground">
              No embedded documents yet — process documents in the library first.
            </span>
          )}
        </div>

        {selectedId !== null &&
        messages.length === 0 &&
        conversationQuery.isPending ? (
          <LoadingState label="Loading conversation…" className="flex-1" />
        ) : selectedId !== null &&
          messages.length === 0 &&
          conversationQuery.isError ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
            <p className="text-sm text-destructive">
              {errorMessage(conversationQuery.error)}
            </p>
            <button
              className="text-sm text-primary underline"
              onClick={() => void conversationQuery.refetch()}
            >
              Retry
            </button>
          </div>
        ) : (
          <ChatThread
            messages={messages}
            isSending={chatMutation.isPending}
            error={sendError}
            onSend={handleSend}
            documentContextName={selectedDoc?.original_filename ?? null}
          />
        )}
      </section>
    </div>
  );
}
