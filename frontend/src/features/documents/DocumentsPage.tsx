import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { api, errorMessage } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "../../components/ui/states";
import { DocumentRow, DocumentListSkeleton } from "./DocumentRow";
import { UploadQueueList, UploadZone, useUploadQueue } from "./UploadZone";

const PAGE_SIZE = 20;

export function DocumentsPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(0);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const documentsQuery = useQuery({
    queryKey: ["documents", page],
    queryFn: () => api.listDocuments(page * PAGE_SIZE, PAGE_SIZE),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["documents"] });

  const upload = useUploadQueue(() => {
    void invalidate();
    setPage(0);
  });

  const processMutation = useMutation({
    mutationFn: (id: string) => api.processDocument(id),
    onMutate: (id) => {
      setPendingId(id);
      setActionError(null);
    },
    onSettled: () => {
      setPendingId(null);
      void invalidate();
    },
    onError: (err) => setActionError(errorMessage(err)),
  });

  const embedMutation = useMutation({
    mutationFn: (id: string) => api.embedDocument(id),
    onMutate: (id) => {
      setPendingId(id);
      setActionError(null);
    },
    onSettled: () => {
      setPendingId(null);
      void invalidate();
    },
    onError: (err) => setActionError(errorMessage(err)),
  });

  const anyActionPending =
    processMutation.isPending || embedMutation.isPending;

  const data = documentsQuery.data;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">
            Document Library
          </h2>
          <p className="text-sm text-muted-foreground">
            Upload documents, then process them to extract text, chunk, and
            generate embeddings for semantic search and Q&amp;A.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void documentsQuery.refetch()}
          disabled={documentsQuery.isFetching}
        >
          <RefreshCw
            className={documentsQuery.isFetching ? "animate-spin" : ""}
            aria-hidden
          />
          Refresh
        </Button>
      </div>

      <UploadZone
  onFiles={(files) => void upload.enqueue(files, api.uploadDocument)}
  disabled={upload.busy}
  uploading={upload.busy}
/>
      <UploadQueueList
  items={upload.items}
  onDismiss={upload.dismiss}
  disabled={upload.busy}
/>
      {upload.items.some((i) => i.state === "error") && (
        <Button
          variant="ghost"
          size="sm"
          onClick={upload.clear}
          disabled={upload.busy}
        >
          Dismiss upload report
        </Button>
      )}

      {actionError && <ErrorState message={actionError} />}

      {documentsQuery.isPending && <DocumentListSkeleton />}

      {documentsQuery.isError && (
        <ErrorState
          message={errorMessage(documentsQuery.error)}
          onRetry={() => void documentsQuery.refetch()}
        />
      )}

      {data && data.items.length === 0 && (
        <EmptyState
          title="No documents yet"
          description="Upload a PDF, DOCX, or TXT file to get started. Processed documents can be searched and used to ground AI answers."
        />
      )}

      {data && data.items.length > 0 && (
        <>
          <ul className="space-y-3" aria-label="Documents">
            {data.items.map((doc) => (
              <DocumentRow
                key={doc.id}
                document={doc}
                actionPending={pendingId === doc.id}
                actionsDisabled={anyActionPending}
                onProcess={(id) => {
                  if (!anyActionPending) processMutation.mutate(id);
                }}
                onEmbed={(id) => {
                  if (!anyActionPending) embedMutation.mutate(id);
                }}
              />
            ))}
          </ul>

          {totalPages > 1 && (
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span>
                {data.total} document{data.total === 1 ? "" : "s"} · page{" "}
                {page + 1} of {totalPages}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page + 1 >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {documentsQuery.isFetching && !documentsQuery.isPending && (
        <LoadingState label="Refreshing…" className="py-4" />
      )}
    </div>
  );
}
