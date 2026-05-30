"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Search, FolderOpen, Zap, History, ArrowRight,
  X, Loader2, CheckCircle2, XCircle, Clock,
} from "lucide-react";
import { collectionService } from "@/lib/services/collection.service";
import { runnerService } from "@/lib/services/runner.service";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { Collection, ApiRequest, TestRun } from "@/types";

// ── Types ─────────────────────────────────────────────────────────────────────

type ResultKind = "collection" | "request" | "run";

interface SearchResult {
  id: string;
  kind: ResultKind;
  title: string;
  subtitle?: string;
  meta?: string;
  status?: string;
  method?: string;
  href: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function highlight(text: string, query: string): string {
  return text; // rendering handled in JSX
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)  return "just now";
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

const METHOD_COLOR: Record<string, string> = {
  GET:    "text-emerald-600 bg-emerald-500/10",
  POST:   "text-blue-600 bg-blue-500/10",
  PUT:    "text-amber-600 bg-amber-500/10",
  PATCH:  "text-purple-600 bg-purple-500/10",
  DELETE: "text-red-600 bg-red-500/10",
};

const STATUS_COLOR: Record<string, string> = {
  passed:  "text-emerald-600",
  failed:  "text-red-600",
  error:   "text-orange-600",
  running: "text-blue-600",
  pending: "text-zinc-500",
};

// ── Result item ───────────────────────────────────────────────────────────────

function ResultItem({
  result, query, isSelected, onSelect,
}: {
  result: SearchResult; query: string; isSelected: boolean;
  onSelect: () => void;
}) {
  const parts = result.title.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"));

  return (
    <button
      className={`flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors ${isSelected ? "bg-accent" : "hover:bg-accent/50"}`}
      onClick={onSelect}
    >
      {/* Icon */}
      <span className="shrink-0 text-muted-foreground">
        {result.kind === "collection" && <FolderOpen className="h-4 w-4" />}
        {result.kind === "request" && result.method && (
          <span className={`rounded px-1 text-[10px] font-mono font-semibold ${METHOD_COLOR[result.method] ?? "text-zinc-600 bg-muted"}`}>
            {result.method}
          </span>
        )}
        {result.kind === "run" && (
          result.status === "passed" ? <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          : result.status === "failed" ? <XCircle className="h-4 w-4 text-red-500" />
          : <Clock className="h-4 w-4 text-zinc-400" />
        )}
      </span>

      {/* Title */}
      <span className="min-w-0 flex-1">
        <span className="block text-sm truncate">
          {query
            ? parts.map((p, i) =>
                p.toLowerCase() === query.toLowerCase()
                  ? <mark key={i} className="bg-yellow-200 text-yellow-900 rounded-sm px-0.5">{p}</mark>
                  : p
              )
            : result.title
          }
        </span>
        {result.subtitle && (
          <span className="block text-xs text-muted-foreground truncate">{result.subtitle}</span>
        )}
      </span>

      {/* Meta */}
      {result.meta && (
        <span className={`shrink-0 text-xs tabular-nums ${result.status ? STATUS_COLOR[result.status] ?? "text-muted-foreground" : "text-muted-foreground"}`}>
          {result.meta}
        </span>
      )}

      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100" />
    </button>
  );
}

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="flex items-center justify-between px-4 py-1.5 bg-muted/30 border-b">
      <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">{label}</span>
      <span className="text-[10px] text-muted-foreground">{count}</span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface CommandSearchProps {
  open: boolean;
  onClose: () => void;
}

export function CommandSearch({ open, onClose }: CommandSearchProps) {
  const router = useRouter();
  const { activeWorkspace } = useWorkspaceStore();
  const workspaceId = activeWorkspace?.id ?? "";

  const [query, setQuery]           = useState("");
  const [loading, setLoading]       = useState(false);
  const [collections, setCollections] = useState<SearchResult[]>([]);
  const [requests, setRequests]     = useState<SearchResult[]>([]);
  const [runs, setRuns]             = useState<SearchResult[]>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);

  const inputRef     = useRef<HTMLInputElement>(null);
  const debounceRef  = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Cache: collection_id → requests array
  const requestCache = useRef<Map<string, ApiRequest[]>>(new Map());
  // All collections (fetched once)
  const allCollections = useRef<Collection[]>([]);

  // ── Focus input on open ──────────────────────────────────────────────────

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
      setQuery("");
      setCollections([]);
      setRequests([]);
      setRuns([]);
      setSelectedIdx(0);
    }
  }, [open]);

  // ── Search ────────────────────────────────────────────────────────────────

  const doSearch = useCallback(async (q: string) => {
    if (!workspaceId) return;
    const term = q.trim().toLowerCase();
    setLoading(true);

    try {
      // ── Load collections if not cached ──────────────────────────────────
      if (allCollections.current.length === 0) {
        const { data } = await collectionService.list(workspaceId);
        allCollections.current = Array.isArray(data) ? data : (data as any).items ?? [];
      }

      // ── Collections: client-side filter ─────────────────────────────────
      const matchedCollections = allCollections.current
        .filter(c => !term || c.name.toLowerCase().includes(term))
        .slice(0, 5)
        .map(c => ({
          id: c.id, kind: "collection" as ResultKind,
          title: c.name,
          subtitle: c.description ?? undefined,
          href: `/workspaces/${workspaceId}/collections/${c.id}`,
        }));
      setCollections(matchedCollections);

      // ── Requests: lazy-load from first few collections ───────────────────
      const requestResults: SearchResult[] = [];
      const collectionsToSearch = allCollections.current.slice(0, 8);

      await Promise.all(collectionsToSearch.map(async col => {
        if (!requestCache.current.has(col.id)) {
          try {
            const { data } = await collectionService.getWithRequests(col.id);
            requestCache.current.set(col.id, (data as any).requests ?? []);
          } catch { requestCache.current.set(col.id, []); }
        }
        const reqs = requestCache.current.get(col.id) ?? [];
        reqs
          .filter(r => !term
            || r.name.toLowerCase().includes(term)
            || r.url.toLowerCase().includes(term)
            || r.method.toLowerCase().includes(term))
          .slice(0, 3)
          .forEach(r => requestResults.push({
            id: r.id, kind: "request",
            title: r.name,
            subtitle: `${col.name} · ${r.url}`,
            method: r.method,
            href: `/workspaces/${workspaceId}/collections/${col.id}`,
          }));
      }));
      setRequests(requestResults.slice(0, 8));

      // ── Runs: server-side filter ─────────────────────────────────────────
      const params: any = { page: 1, page_size: 5, sort_by: "started_at", sort_dir: "desc" };
      if (term) {
        // Backend filters by status or trigger_type; collection_name is client-side
        const matchesStatus = ["passed", "failed", "error", "running", "pending"].find(s => s.startsWith(term));
        if (matchesStatus) params.status = matchesStatus;
      }
      const { data: runData } = await runnerService.listRuns(workspaceId, params);
      const runItems = (Array.isArray(runData) ? runData : runData.items ?? []) as TestRun[];
      const filteredRuns = runItems
        .filter(r => !term
          || r.collection_name?.toLowerCase().includes(term)
          || r.status.includes(term)
          || r.trigger_type.includes(term))
        .slice(0, 5)
        .map(r => ({
          id: r.id, kind: "run" as ResultKind,
          title: r.collection_name ?? "Single request",
          subtitle: `${r.trigger_type} · ${r.passed}/${r.total} passed`,
          meta: fmtDate(r.started_at),
          status: r.status,
          href: `/workspaces/${workspaceId}/runs/${r.id}`,
        }));
      setRuns(filteredRuns);

    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  // ── Debounce ──────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!open) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(query), query ? 300 : 0);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query, open, doSearch]);

  // ── All results flat (for keyboard nav) ───────────────────────────────────

  const allResults = [...collections, ...requests, ...runs];

  // ── Keyboard navigation ───────────────────────────────────────────────────

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIdx(i => Math.min(i + 1, allResults.length - 1));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIdx(i => Math.max(i - 1, 0));
      }
      if (e.key === "Enter" && allResults[selectedIdx]) {
        router.push(allResults[selectedIdx].href);
        onClose();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, allResults, selectedIdx, router, onClose]);

  // Reset selection when results change
  useEffect(() => setSelectedIdx(0), [collections, requests, runs]);

  if (!open) return null;

  const totalResults = allResults.length;
  const isEmpty = !loading && totalResults === 0;

  // Result index offset for keyboard selection tracking
  let colStart = 0;
  let reqStart = collections.length;
  let runStart = collections.length + requests.length;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4"
      onClick={onClose}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

      {/* Panel */}
      <div
        className="relative w-full max-w-2xl rounded-xl border bg-background shadow-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 border-b px-4 py-3">
          {loading
            ? <Loader2 className="h-4 w-4 shrink-0 text-muted-foreground animate-spin" />
            : <Search className="h-4 w-4 shrink-0 text-muted-foreground" />}
          <input
            ref={inputRef}
            className="flex-1 bg-transparent text-sm placeholder:text-muted-foreground focus:outline-none"
            placeholder="Search collections, requests, runs…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          {query && (
            <button className="text-muted-foreground hover:text-foreground" onClick={() => setQuery("")}>
              <X className="h-4 w-4" />
            </button>
          )}
          <kbd className="shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground bg-muted">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div className="max-h-[420px] overflow-auto">
          {isEmpty && (
            <div className="flex flex-col items-center justify-center gap-2 py-12 text-muted-foreground">
              <Search className="h-8 w-8 opacity-30" />
              <p className="text-sm">{query ? `No results for "${query}"` : "Start typing to search…"}</p>
            </div>
          )}

          {collections.length > 0 && (
            <div>
              <SectionHeader label="Collections" count={collections.length} />
              {collections.map((r, i) => (
                <ResultItem key={r.id} result={r} query={query}
                  isSelected={selectedIdx === colStart + i}
                  onSelect={() => { router.push(r.href); onClose(); }} />
              ))}
            </div>
          )}

          {requests.length > 0 && (
            <div>
              <SectionHeader label="Requests" count={requests.length} />
              {requests.map((r, i) => (
                <ResultItem key={r.id} result={r} query={query}
                  isSelected={selectedIdx === reqStart + i}
                  onSelect={() => { router.push(r.href); onClose(); }} />
              ))}
            </div>
          )}

          {runs.length > 0 && (
            <div>
              <SectionHeader label="Recent Runs" count={runs.length} />
              {runs.map((r, i) => (
                <ResultItem key={r.id} result={r} query={query}
                  isSelected={selectedIdx === runStart + i}
                  onSelect={() => { router.push(r.href); onClose(); }} />
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        {totalResults > 0 && (
          <div className="flex items-center gap-4 border-t px-4 py-2 text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1"><kbd className="rounded border px-1 bg-muted">↑↓</kbd> navigate</span>
            <span className="flex items-center gap-1"><kbd className="rounded border px-1 bg-muted">↵</kbd> open</span>
            <span className="flex items-center gap-1"><kbd className="rounded border px-1 bg-muted">esc</kbd> close</span>
            <span className="ml-auto">{totalResults} result{totalResults !== 1 ? "s" : ""}</span>
          </div>
        )}
      </div>
    </div>
  );
}
