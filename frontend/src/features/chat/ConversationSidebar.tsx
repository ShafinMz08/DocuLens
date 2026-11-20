import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { api, errorMessage } from "../../lib/api";
import type { ConversationSummary } from "../../lib/types";
import { formatRelative } from "../../lib/format";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";

interface ConversationSidebarProps {
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /** Disables conversation selection (e.g. while a chat response is pending). */
  selectionDisabled?: boolean;
}

function conversationLabel(c: ConversationSummary): string {
  return c.title?.trim() || "Untitled conversation";
}

export function ConversationSidebar({
  selectedId,
  onSelect,
  selectionDisabled = false,
}: ConversationSidebarProps) {
  const queryClient = useQueryClient();
  const [mobileOpen, setMobileOpen] = useState(false);

  const { data, isPending, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["conversations"],
    queryFn: () => api.listConversations(0, 50),
  });

  const list = (
    <div className="flex h-full flex-col">
      <div className="border-b p-3">
        <Button
          className="w-full"
          size="sm"
          disabled={selectionDisabled}
          onClick={() => {
            onSelect(null);
            setMobileOpen(false);
          }}
        >
          <Plus className="size-4" aria-hidden />
          New conversation
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {isPending && (
          <p className="px-2 py-6 text-center text-sm text-muted-foreground">
            Loading conversations…
          </p>
        )}
        {isError && (
          <div className="px-2 py-6 text-center">
            <p className="text-sm text-destructive">{errorMessage(error)}</p>
            <Button variant="outline" size="sm" className="mt-2" onClick={() => void refetch()}>
              Retry
            </Button>
          </div>
        )}
        {data && data.length === 0 && (
          <p className="px-2 py-6 text-center text-sm text-muted-foreground">
            No conversations yet. Ask a question to start one.
          </p>
        )}
        {data && data.length > 0 && (
          <ul className="space-y-1" aria-label="Conversations">
            {data.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => {
                    onSelect(c.id);
                    setMobileOpen(false);
                  }}
                  disabled={selectionDisabled}
                  className={cn(
                    "w-full rounded-md px-3 py-2 text-left text-sm transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    "disabled:cursor-not-allowed disabled:opacity-50",
                    selectedId === c.id
                      ? "bg-accent text-accent-foreground"
                      : "hover:bg-accent/60",
                  )}
                >
                  <span className="block truncate font-medium">
                    {conversationLabel(c)}
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {c.message_count} message{c.message_count === 1 ? "" : "s"} ·{" "}
                    {formatRelative(c.updated_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t p-2">
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start text-muted-foreground"
          onClick={() => void queryClient.invalidateQueries({ queryKey: ["conversations"] })}
          disabled={isFetching}
        >
          Refresh list
        </Button>
      </div>
    </div>
  );

  return (
    <>
      {/* Mobile toggle */}
      <div className="border-b p-2 lg:hidden">
        <Button variant="outline" size="sm" className="w-full" onClick={() => setMobileOpen((v) => !v)}>
          {mobileOpen ? "Hide" : "Show"} conversations
        </Button>
      </div>
      {mobileOpen && <div className="border-b bg-card lg:hidden">{list}</div>}
      {/* Desktop */}
      <aside className="hidden w-72 shrink-0 border-r bg-card lg:block">
        {list}
      </aside>
    </>
  );
}
