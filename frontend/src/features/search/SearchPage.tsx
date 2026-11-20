import { useMutation, useQuery } from "@tanstack/react-query";
import { FileText, Search, SearchX } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { api, errorMessage } from "../../lib/api";
import type { SearchResponse } from "../../lib/types";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Badge } from "../../components/ui/badge";
import { EmptyState, ErrorState } from "../../components/ui/states";
import { cn } from "../../lib/utils";

const TOP_K_OPTIONS = [5, 10, 20, 50];

export function SearchPage() {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(10);
  const [documentId, setDocumentId] = useState("");

  const documentsQuery = useQuery({
    queryKey: ["documents", "search-filter"],
    queryFn: () => api.listDocuments(0, 100),
  });

  const filterableDocuments = useMemo(
    () =>
      (documentsQuery.data?.items ?? []).filter(
        (d) => d.status === "completed" && d.embedding_status === "completed",
      ),
    [documentsQuery.data],
  );

  const searchMutation = useMutation<SearchResponse, Error, void>({
    mutationFn: () =>
      api.search({
        query: query.trim(),
        top_k: topK,
        document_id: documentId || null,
      }),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!query.trim() || searchMutation.isPending) return;
    searchMutation.mutate();
  };

  const results = searchMutation.data?.results ?? null;

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Semantic Search</h2>
        <p className="text-sm text-muted-foreground">
          Search across the text and meaning of your processed documents using
          vector similarity.
        </p>
      </div>

      <form
        onSubmit={submit}
        className="rounded-lg border bg-card p-4 shadow-sm"
      >
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. technical skills and experience…"
              className="pl-9"
              aria-label="Search query"
            />
          </div>
          <div className="flex gap-2">
            <Select
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
              className="w-28"
              aria-label="Number of results"
            >
              {TOP_K_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  Top {n}
                </option>
              ))}
            </Select>
            <Select
              value={documentId}
              onChange={(e) => setDocumentId(e.target.value)}
              className="w-44 sm:w-56"
              aria-label="Filter by document"
            >
              <option value="">All documents</option>
              {filterableDocuments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.original_filename}
                </option>
              ))}
            </Select>
            <Button type="submit" disabled={!query.trim() || searchMutation.isPending}>
              {searchMutation.isPending ? "Searching…" : "Search"}
            </Button>
          </div>
        </div>
      </form>

      {searchMutation.isError && (
        <ErrorState
          message={errorMessage(searchMutation.error)}
          onRetry={() => searchMutation.mutate()}
        />
      )}

      {searchMutation.isPending && (
        <ul className="space-y-3" aria-label="Loading results">
          {[0, 1, 2].map((i) => (
            <li key={i} className="h-28 animate-pulse rounded-lg border bg-card" />
          ))}
        </ul>
      )}

      {results && results.length === 0 && (
        <EmptyState
          icon={<SearchX className="size-8" aria-hidden />}
          title="No matching chunks"
          description={`Nothing in the embedded documents matched "${searchMutation.data?.query}". Try different wording or process more documents.`}
        />
      )}

      {results && results.length > 0 && (
        <>
          <p className="text-sm text-muted-foreground" role="status">
            {results.length} result{results.length === 1 ? "" : "s"} for “
            {searchMutation.data?.query}”
          </p>
          <ul className="space-y-3" aria-label="Search results">
            {results.map((r, i) => (
              <li
                key={r.chunk_id}
                className={cn(
                  "rounded-lg border bg-card p-4 shadow-sm",
                  i === 0 && "border-primary/40",
                )}
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1 font-medium text-foreground">
                    <FileText className="size-3.5" aria-hidden />
                    {r.document_name}
                  </span>
                  <span>chunk {r.chunk_index}</span>
                  {r.page_number != null && <span>page {r.page_number}</span>}
                  <Badge variant="secondary" className="ml-auto">
                    similarity {r.score.toFixed(3)}
                  </Badge>
                </div>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">
                  {r.content}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}

      {!searchMutation.data && !searchMutation.isPending && (
        <EmptyState
          icon={<Search className="size-8" aria-hidden />}
          title="Search your documents"
          description="Enter a query above to find semantically similar passages across all embedded documents."
        />
      )}
    </div>
  );
}
