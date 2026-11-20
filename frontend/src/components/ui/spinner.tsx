import { Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";

export function Spinner({ className }: { className?: string }) {
  return (
    <Loader2
      className={cn("size-4 animate-spin text-muted-foreground", className)}
      aria-hidden
    />
  );
}

/** Honest indeterminate progress indicator (no fake percentage). */
export function IndeterminateBar({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "h-1 w-full overflow-hidden rounded-full bg-muted",
        className,
      )}
      role="progressbar"
      aria-label="Processing"
    >
      <div className="animate-indeterminate h-full w-1/4 rounded-full bg-primary" />
    </div>
  );
}
