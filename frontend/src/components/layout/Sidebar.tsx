"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, FolderOpen, History, BarChart3,
  Settings2, Zap, LogOut, ChevronDown, Search,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/authStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { authService } from "@/lib/services/auth.service";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { CommandSearch } from "@/components/search/CommandSearch";
import { useRouter } from "next/navigation";

const NAV = [
  { label: "Dashboard",    icon: LayoutDashboard, href: "/dashboard" },
  { label: "Collections",  icon: FolderOpen,      href: (id: string) => `/workspaces/${id}` },
  { label: "History",      icon: History,         href: (id: string) => `/workspaces/${id}/history` },
  { label: "Analytics",    icon: BarChart3,        href: (id: string) => `/workspaces/${id}/analytics` },
  { label: "Environments", icon: Settings2,        href: (id: string) => `/workspaces/${id}/environments` },
] as const;

export function Sidebar() {
  const pathname = usePathname();
  const router   = useRouter();
  const { user, refreshToken, clearAuth } = useAuthStore();
  const { activeWorkspace } = useWorkspaceStore();
  const [searchOpen, setSearchOpen] = useState(false);

  // ── Cmd+K / Ctrl+K shortcut ──────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen(o => !o);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const handleLogout = async () => {
    try { await authService.logout(refreshToken); } catch {}
    clearAuth();
    router.push("/login");
  };

  const href = (nav: typeof NAV[number]) =>
    typeof nav.href === "function"
      ? activeWorkspace ? nav.href(activeWorkspace.id) : "/dashboard"
      : nav.href;

  return (
    <>
      <aside className="flex h-screen w-56 flex-col border-r bg-background">
        {/* Logo */}
        <div className="flex h-14 items-center gap-2 border-b px-4">
          <Zap className="h-5 w-5 text-primary" />
          <span className="font-semibold tracking-tight">API Tester</span>
        </div>

        {/* Search button */}
        <div className="border-b px-3 py-2">
          <button
            className="flex w-full items-center gap-2 rounded-md border bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted/60 transition-colors"
            onClick={() => setSearchOpen(true)}
          >
            <Search className="h-3.5 w-3.5" />
            <span className="flex-1 text-left">Search…</span>
            <kbd className="rounded border px-1 py-0.5 text-[10px] bg-background">
              ⌘K
            </kbd>
          </button>
        </div>

        {/* Workspace picker */}
        {activeWorkspace && (
          <div className="border-b px-3 py-2">
            <DropdownMenu>
              <DropdownMenuTrigger className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-accent">
                <span className="truncate">{activeWorkspace.name}</span>
                <ChevronDown className="h-3 w-3 opacity-50" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-48">
                <DropdownMenuItem onSelect={() => router.push("/dashboard")}>
                  Switch workspace
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}

        {/* Nav */}
        <nav className="flex-1 space-y-1 p-2">
          {NAV.map((item) => {
            const to     = href(item);
            const active = pathname === to || pathname.startsWith(to + "/");
            return (
              <Link
                key={item.label}
                href={to}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-secondary text-secondary-foreground font-medium"
                    : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                )}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* User */}
        <div className="border-t p-3">
          <div className="flex items-center justify-between">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{user?.name}</p>
              <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
            </div>
            <Button variant="ghost" size="icon" onClick={handleLogout} title="Logout">
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </aside>

      {/* Global search palette */}
      <CommandSearch open={searchOpen} onClose={() => setSearchOpen(false)} />
    </>
  );
}
