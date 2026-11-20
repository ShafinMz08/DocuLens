import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  FileText,
  Menu,
  MessageSquare,
  Moon,
  ScanSearch,
  Sun,
  X,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { api } from "../../lib/api";
import { cn } from "../../lib/utils";
import { useTheme } from "../../lib/theme";
import { Button } from "../ui/button";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/documents", label: "Document Library", icon: FileText },
  { to: "/assistant", label: "AI Assistant", icon: MessageSquare },
  { to: "/search", label: "Semantic Search", icon: ScanSearch },
];

function HealthDot() {
  const { data, isError, isPending } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 30_000,
    retry: false,
  });

  const healthy = !isError && data?.status === "ok";
  const label = isPending
    ? "Checking backend…"
    : healthy
      ? "Backend connected"
      : "Backend unreachable";

  return (
    <div
      className="flex items-center gap-2 px-1 text-xs text-muted-foreground"
      title={label}
      role="status"
    >
      <span
        className={cn(
          "size-2 rounded-full",
          isPending && "bg-muted-foreground/50",
          healthy && "bg-emerald-500",
          isError && "bg-destructive",
        )}
      />
      <span className="truncate">{label}</span>
    </div>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center gap-2.5 border-b px-5">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <ScanSearch className="size-4.5" aria-hidden />
        </div>
        <div className="leading-tight">
          <p className="text-sm font-semibold tracking-tight">DocuLens</p>
          <p className="text-[11px] text-muted-foreground">
            Document Intelligence
          </p>
        </div>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto p-3" aria-label="Main">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                isActive
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
              )
            }
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t p-3">
        <HealthDot />
      </div>
    </div>
  );
}

export function AppLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { theme, toggle } = useTheme();
  const location = useLocation();

  const pageTitle =
    NAV_ITEMS.find((item) => location.pathname.startsWith(item.to))?.label ??
    "DocuLens";

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 border-r bg-card md:block">
        <SidebarContent />
      </aside>

      {/* Mobile sidebar */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setMobileOpen(false)}
            aria-hidden
          />
          <aside className="absolute inset-y-0 left-0 w-64 bg-card shadow-xl">
            <button
              className="absolute right-2 top-3 rounded-md p-1.5 text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => setMobileOpen(false)}
              aria-label="Close navigation"
            >
              <X className="size-5" />
            </button>
            <SidebarContent onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-card/60 px-4 backdrop-blur">
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="size-5" />
          </Button>
          <h1 className="text-sm font-semibold">{pageTitle}</h1>
          <div className="ml-auto">
            <Button
              variant="ghost"
              size="icon"
              onClick={toggle}
              aria-label={
                theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
              }
            >
              {theme === "dark" ? (
                <Sun className="size-4" />
              ) : (
                <Moon className="size-4" />
              )}
            </Button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
