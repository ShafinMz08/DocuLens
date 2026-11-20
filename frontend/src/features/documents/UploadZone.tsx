import { useRef, useState } from "react";
import {
  FileText,
  FileUp,
  Loader2,
  UploadCloud,
  X,
} from "lucide-react";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";
import { formatBytes } from "../../lib/format";
import { errorMessage } from "../../lib/api";

export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024; // mirrors backend MAX_UPLOAD_SIZE_BYTES
export const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".txt"] as const;

export function validateFile(file: File): string | null {
  const name = file.name.toLowerCase();
  const extOk = ALLOWED_EXTENSIONS.some((ext) => name.endsWith(ext));
  if (!extOk) {
    return `"${file.name}" is not a supported file type. Allowed: PDF, DOCX, TXT.`;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `"${file.name}" exceeds the 20 MB upload limit.`;
  }
  if (file.size === 0) {
    return `"${file.name}" is empty.`;
  }
  return null;
}

interface UploadZoneProps {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  uploading?: boolean;
}

export function UploadZone({ onFiles, disabled, uploading }: UploadZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const isDisabled = disabled || uploading;

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault();
    setDragOver(false);
    if (isDisabled) return;
    const files = Array.from(event.dataTransfer.files);
    if (files.length) onFiles(files);
  };

  return (
    <div
      className={cn(
        "rounded-lg border-2 border-dashed p-6 text-center transition-colors",
        dragOver
          ? "border-primary bg-accent/50"
          : "border-input hover:border-primary/50",
        isDisabled && "pointer-events-none opacity-60",
      )}
      onDragOver={(e) => {
        e.preventDefault();
        if (!isDisabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      data-testid="upload-zone"
    >
      <input
        ref={inputRef}
        type="file"
        disabled={isDisabled}
        multiple
        accept=".pdf,.docx,.txt"
        className="sr-only"
        aria-label="Choose files to upload"
        onChange={(e) => {
          if (isDisabled) return;
          const files = Array.from(e.target.files ?? []);
          if (files.length) onFiles(files);
          e.target.value = "";
        }}
      />
      <div className="flex flex-col items-center gap-2">
        {uploading ? (
          <Loader2 className="size-8 animate-spin text-primary" aria-hidden />
        ) : (
          <UploadCloud className="size-8 text-muted-foreground" aria-hidden />
        )}
        <p className="text-sm font-medium">
          {uploading
            ? "Uploading…"
            : "Drag & drop documents here, or browse"}
        </p>
        <p className="text-xs text-muted-foreground">
          PDF, DOCX or TXT — up to 20 MB each
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => inputRef.current?.click()}
          disabled={isDisabled}
        >
          <FileUp className="size-4" aria-hidden />
          Choose files
        </Button>
      </div>
    </div>
  );
}

interface UploadStatus {
  id: number;
  file: File;
  state: "queued" | "uploading" | "done" | "error";
  message?: string;
}

/**
 * Sequential upload queue with per-file status. Upload progress is reported
 * only at the file granularity the backend supports (per-request completion).
 */
export function useUploadQueue(onUploaded: () => void) {
  const [items, setItems] = useState<UploadStatus[]>([]);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const nextIdRef = useRef(0);

  const enqueue = async (files: File[], upload: (f: File) => Promise<unknown>) => {
    if (busyRef.current || files.length === 0) return;
    busyRef.current = true;
    setBusy(true);

    try {
      const queue: UploadStatus[] = files.map((file) => {
        const id = ++nextIdRef.current;
        const error = validateFile(file);
        return error
          ? { id, file, state: "error" as const, message: error }
          : { id, file, state: "queued" as const };
      });
      setItems(queue);

      for (const item of queue) {
        if (item.state === "error") continue;

        setItems((prev) =>
          prev.map((p) =>
            p.id === item.id ? { ...p, state: "uploading" } : p,
          ),
        );

        try {
          await upload(item.file);
          setItems((prev) =>
            prev.map((p) =>
              p.id === item.id
                ? { ...p, state: "done", message: "Uploaded" }
                : p,
            ),
          );
        } catch (err) {
          setItems((prev) =>
            prev.map((p) =>
              p.id === item.id
                ? { ...p, state: "error", message: errorMessage(err) }
                : p,
            ),
          );
        }
      }

      onUploaded();
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  const clear = () => {
    if (busyRef.current) return;
    setItems([]);
  };

  const dismiss = (id: number) => {
    if (busyRef.current) return;
    setItems((prev) => prev.filter((item) => item.id !== id));
  };

  return { items, busy, enqueue, clear, dismiss };
}

export function UploadQueueList({
  items,
  onDismiss,
  disabled = false,
}: {
  items: UploadStatus[];
  onDismiss: (id: number) => void;
  disabled?: boolean;
}) {
  if (!items.length) return null;
  return (
    <ul className="space-y-1.5" aria-label="Upload status">
      {items.map((item) => (
        <li
          key={item.id}
          className="flex items-center gap-2 rounded-md border bg-card px-3 py-2 text-sm"
        >
          <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="min-w-0 flex-1 truncate">{item.file.name}</span>
          <span className="shrink-0 text-xs text-muted-foreground">
            {formatBytes(item.file.size)}
          </span>
          {item.state === "uploading" && <Loader2 className="size-4 animate-spin" aria-hidden />}
          {item.state === "done" && (
            <span className="text-xs font-medium text-emerald-600 dark:text-emerald-400">
              Uploaded
            </span>
          )}
          {item.state === "error" && (
            <span className="max-w-56 truncate text-xs text-destructive" title={item.message}>
              {item.message}
            </span>
          )}
          {(item.state === "done" || item.state === "error") && (
            <button
              className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              disabled={disabled}
              onClick={() => onDismiss(item.id)}
              aria-label={`Dismiss ${item.file.name}`}
            >
              <X className="size-3.5" />
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
