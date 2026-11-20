import { useState, type ReactNode } from "react";
import { cn } from "../../lib/utils";

/**
 * Minimal accessible tooltip: shows on hover/focus. Kept dependency-free.
 */
interface TooltipProps {
  children: ReactNode;
  content: ReactNode;
}

export function Tooltip({ children, content }: TooltipProps) {
  const [open, setOpen] = useState(false);
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      {open && (
        <span
          role="tooltip"
          className={cn(
            "absolute bottom-full left-1/2 z-50 mb-1.5 -translate-x-1/2",
            "whitespace-nowrap rounded-md bg-foreground px-2 py-1 text-xs text-background shadow-md",
          )}
        >
          {content}
        </span>
      )}
    </span>
  );
}

// API-compatible shim names so callers can use <Tooltip><TooltipTrigger/><TooltipContent/></Tooltip>
export function TooltipTrigger({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
export function TooltipContent({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
