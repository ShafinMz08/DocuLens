import {
  CheckCircle2,
  CircleDashed,
  FileText,
  Loader2,
  Play,
  RefreshCw,
  XCircle,
} from "lucide-react";
import type { Document, EmbeddingStatus } from "../../lib/types";
import { formatBytes, formatDateTime } from "../../lib/format";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { IndeterminateBar } from "../../components/ui/spinner";
import { Tooltip } from "../../components/ui/tooltip";

const STATUS_META: Record<
  Document["status"],
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" | "outline" }
> = {
  uploaded: { label: "Uploaded", variant: "secondary" },
  processing: { label: "Processing", variant: "default" },
  completed: { label: "Processed", variant: "success" },
  failed: { label: "Failed", variant: "destructive" },
};

const EMBED_META: Record<
  EmbeddingStatus,
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" | "outline" }
> = {
  pending: { label: "Embed pending", variant: "outline" },
  processing: { label: "Embedding…", variant: "default" },
  completed: { label: "Embedded", variant: "success" },
  failed: { label: "Embed failed", variant: "destructive" },
};

function StatusIcon({ status }: { status: Document["status"] }) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="size-4 text-emerald-500" aria-hidden />;
    case "failed":
      return <XCircle className="size-4 text-destructive" aria-hidden />;
    case "processing":
      return <Loader2 className="size-4 animate-spin text-primary" aria-hidden />;
    default:
      return <CircleDashed className="size-4 text-muted-foreground" aria-hidden />;
  }
}

export interface DocumentRowProps {
  document: Document;
  /** True only for the row whose process/embed request is in flight. */
  actionPending: boolean;
  /** True while ANY document action is pending — disables all action buttons. */
  actionsDisabled: boolean;
  onProcess: (id: string) => void;
  onEmbed: (id: string) => void;
}

export function DocumentRow({
  document: doc,
  actionPending,
  actionsDisabled,
  onProcess,
  onEmbed,
}: DocumentRowProps) {
  const docStatus = STATUS_META[doc.status];
  const embedStatus = EMBED_META[doc.embedding_status];
  const isProcessing = doc.status === "processing";

  return (
    <li className="rounded-lg border bg-card p-4 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 rounded-md bg-accent p-2 text-accent-foreground">
            <FileText className="size-4" aria-hidden />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium" title={doc.original_filename}>
              {doc.original_filename}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {formatBytes(doc.file_size_bytes)} · Uploaded{" "}
              {formatDateTime(doc.created_at)}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Badge variant={docStatus.variant}>
                <StatusIcon status={doc.status} />
                {isProcessing && actionPending ? "Processing…" : docStatus.label}
              </Badge>
              {doc.status === "completed" && (
                <Tooltip content={doc.embedding_error ?? embedStatus.label}>
                  <Badge variant={embedStatus.variant}>{embedStatus.label}</Badge>
                </Tooltip>
              )}
              {doc.embedding_error && doc.status === "completed" && (
                <span className="text-xs text-destructive">{doc.embedding_error}</span>
              )}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {doc.status === "uploaded" && (
            <Button
              size="sm"
              onClick={() => onProcess(doc.id)}
              disabled={actionsDisabled}
            >
              {actionPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Play className="size-4" aria-hidden />
              )}
              Process
            </Button>
          )}
          {doc.status === "failed" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => onProcess(doc.id)}
              disabled={actionsDisabled}
            >
              {actionPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <RefreshCw className="size-4" aria-hidden />
              )}
              Retry processing
            </Button>
          )}
          {doc.status === "completed" && doc.embedding_status === "failed" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => onEmbed(doc.id)}
              disabled={actionsDisabled}
            >
              {actionPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <RefreshCw className="size-4" aria-hidden />
              )}
              Retry embedding
            </Button>
          )}
        </div>
      </div>

      {isProcessing && <IndeterminateBar className="mt-3" />}
      {doc.status === "processing" && (
        <p className="mt-2 text-xs text-muted-foreground">
          Extracting text and generating embeddings…
        </p>
      )}
    </li>
  );
}

export function DocumentListSkeleton() {
  return (
    <ul className="space-y-3" aria-label="Loading documents">
      {[0, 1, 2].map((i) => (
        <li key={i} className="h-24 animate-pulse rounded-lg border bg-card" />
      ))}
    </ul>
  );
}

export function documentMatchesSearch(doc: Document, query: string): boolean {
  return doc.original_filename.toLowerCase().includes(query.toLowerCase());
}
