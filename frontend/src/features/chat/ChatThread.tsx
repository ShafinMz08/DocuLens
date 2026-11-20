import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { BookOpen, SendHorizontal, Sparkles } from "lucide-react";
import type { Citation, MessageRole } from "../../lib/types";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import { cn } from "../../lib/utils";
import { EmptyState } from "../../components/ui/states";

export interface ThreadMessage {
  id: string;
  role: MessageRole;
  content: string;
  citations?: Citation[] | null;
  provider?: string | null;
  model?: string | null;
}

/** Render answer text, turning inline [n] markers into citation links. */
function renderAnswer(text: string, messageId: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const regex = /\[(\d+)\]/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  const scrollToCitation = (n: number) => {
    const el = document.getElementById(`${messageId}-citation-${n}`);
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  };

  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) {
      nodes.push(text.slice(last, match.index));
    }
    const n = Number(match[1]);
    nodes.push(
      <button
        key={`${messageId}-ref-${key++}`}
        type="button"
        onClick={() => scrollToCitation(n)}
        className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-primary/15 px-1 align-super text-[10px] font-semibold text-primary hover:bg-primary/25 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        aria-label={`Jump to citation ${n}`}
      >
        {n}
      </button>,
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function CitationCard({
  citation,
  index,
  messageId,
}: {
  citation: Citation;
  index: number;
  messageId: string;
}) {
  return (
    <li
      id={`${messageId}-citation-${index + 1}`}
      className="rounded-md border bg-muted/40 p-3 text-sm"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-medium text-primary">[{index + 1}]</span>
        <span className="font-medium">{citation.document_name}</span>
        {citation.page_number != null && (
          <span className="text-muted-foreground">
            · page {citation.page_number}
          </span>
        )}
        <span className="text-xs text-muted-foreground">
          chunk {citation.chunk_index} · similarity{" "}
          {citation.score.toFixed(3)}
        </span>
      </div>
      {citation.excerpt && (
        <p className="mt-1.5 line-clamp-4 text-xs leading-relaxed text-muted-foreground">
          {citation.excerpt}
        </p>
      )}
    </li>
  );
}

function MessageBubble({ message }: { message: ThreadMessage }) {
  const isUser = message.role === "user";
  const citations = message.citations ?? [];

  return (
    <article
      className={cn(
        "flex flex-col gap-2",
        isUser ? "items-end" : "items-start",
      )}
      aria-label={`${isUser ? "You" : "Assistant"} message`}
    >
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm sm:max-w-[75%]",
          isUser
            ? "rounded-br-sm bg-primary text-primary-foreground"
            : "rounded-bl-sm border bg-card",
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="whitespace-pre-wrap">
            {renderAnswer(message.content, message.id)}
          </div>
        )}
      </div>

      {!isUser && (message.provider || message.model) && (
        <p className="px-1 text-[11px] text-muted-foreground">
          {message.provider}
          {message.model ? ` · ${message.model}` : ""}
        </p>
      )}

      {!isUser && citations.length > 0 && (
        <div className="w-full max-w-[85%] sm:max-w-[75%]">
          <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <BookOpen className="size-3.5" aria-hidden />
            Sources
          </p>
          <ul className="space-y-2" aria-label="Citations">
            {citations.map((c, i) => (
              <CitationCard
                key={c.chunk_id}
                citation={c}
                index={i}
                messageId={message.id}
              />
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

interface ChatThreadProps {
  messages: ThreadMessage[];
  isSending: boolean;
  error: string | null;
  onSend: (question: string) => void;
  documentContextName?: string | null;
}

export function ChatThread({
  messages,
  isSending,
  error,
  onSend,
  documentContextName,
}: ChatThreadProps) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottom.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  useEffect(() => {
    if (stickToBottom.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isSending]);

  const submit = useCallback(
    (e?: FormEvent) => {
      e?.preventDefault();
      const question = draft.trim();
      if (!question || isSending) return;
      setDraft("");
      onSend(question);
    },
    [draft, isSending, onSend],
  );

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 space-y-6 overflow-y-auto px-4 py-6 sm:px-6"
        aria-live="polite"
      >
        {messages.length === 0 && !isSending && (
          <EmptyState
            icon={<Sparkles className="size-8" aria-hidden />}
            title="Ask about your documents"
            description={
              documentContextName
                ? `Answers will be grounded in "${documentContextName}". Questions the documents can't answer will be declined honestly.`
                : "Answers are grounded in your uploaded, processed documents via semantic retrieval. Select a document above to restrict the context."
            }
            className="mx-auto mt-10 max-w-md border-0"
          />
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {isSending && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
            <span className="size-2 animate-pulse rounded-full bg-primary" />
            Thinking…
          </div>
        )}
        {error && (
          <div
            className="rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
            role="alert"
          >
            {error}
          </div>
        )}
      </div>

      <form
        onSubmit={submit}
        className="border-t bg-card/60 p-3 backdrop-blur sm:p-4"
      >
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={
              isSending
                ? "Waiting for response…"
                : "Ask a question about your documents…"
            }
            disabled={isSending}
            rows={1}
            className="max-h-40 min-h-10 flex-1 resize-none py-2.5"
            aria-label="Question"
          />
          <Button
            type="submit"
            disabled={isSending || !draft.trim()}
            aria-label="Send question"
          >
            <SendHorizontal className="size-4" aria-hidden />
            <span className="hidden sm:inline">Send</span>
          </Button>
        </div>
        <p className="mx-auto mt-1.5 max-w-3xl text-[11px] text-muted-foreground">
          Enter to send · Shift+Enter for a new line
          {documentContextName && (
            <>
              {" "}
              · Context:{" "}
              <Badge variant="secondary" className="align-middle">
                <span className="max-w-40 truncate">{documentContextName}</span>
              </Badge>
            </>
          )}
        </p>
      </form>
    </div>
  );
}
