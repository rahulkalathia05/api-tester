"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  CheckCircle2,
  XCircle,
  AlertCircle,
  Clock,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  Filter,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { runnerService, type ListRunsParams } from "@/lib/services/runner.service";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import type { PaginatedResponse, RunStats, TestRun, SortDir } from "@/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  }).format(new Date(iso));
}

function passRate(run: TestRun): string {
  if (run.total === 0) return "—";
  return `${run.passed}/${run.total}`;
}

// ── Status badge ──────────────────────────────────────────────────────────────

const STATUS_CONFIG = {
  passed:  { label: "Passed",  className: "bg-emerald-500/15 text-emerald-600 border-emerald-200" },
  failed:  { label: "Failed",  className: "bg-red-500/15 text-red-600 border-red-200" },
  error:   { label: "Error",   className: "bg-orange-500/15 text-orange-600 border-orange-200" },
  running: { label: "Running", className: "bg-blue-500/15 text-blue-600 border-blue-200" },
  pending: { label: "Pending", className: "bg-zinc-500/15 text-zinc-600 border-zinc-200" },
} as const;

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status as keyof typeof STATUS_CONFIG] ?? STATUS_CONFIG.pending;
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${cfg.className}`}>
      {cfg.label}
    </span>
  );
}

// ── Stats card ────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

// ── Sort header ───────────────────────────────────────────────────────────────

function SortTh({
  label, field, current, dir, onSort,
}: {
  label: string;
  field: string;
  current: string;
  dir: SortDir;
  onSort: (f: string) => void;
}) {
  const active = current === field;
  const Icon = active ? (dir === "asc" ? ChevronUp : ChevronDown) : ChevronsUpDown;
  return (
    <th
      className="cursor-pointer select-none whitespace-nowrap px-4 py-3 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
      onClick={() => onSort(field)}
    >
      <span className="flex items-center gap-1">
        {label}
        <Icon className="h-3 w-3" />
      </span>
    </th>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function HistoryPage() {
  const { id: workspaceId } = useParams<{ id: string }>();
  const router = useRouter();
  const { activeWorkspace } = useWorkspaceStore();

  // ── State ──────────────────────────────────────────────────────────────────
  const [stats, setStats] = useState<RunStats | null>(null);
  const [page, setPage] = useState<PaginatedResponse<TestRun> | null>(null);
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);

  const [filters, setFilters] = useState<ListRunsParams>({
    page: 1,
    page_size: 20,
    sort_by: "started_at",
    sort_dir: "desc",
  });

  // ── Data fetching ──────────────────────────────────────────────────────────
  const loadStats = useCallback(async () => {
    if (!workspaceId) return;
    setStatsLoading(true);
    try {
      const r = await runnerService.getStats(workspaceId);
      setStats(r.data);
    } catch { /* silent */ }
    finally { setStatsLoading(false); }
  }, [workspaceId]);

  const loadRuns = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    try {
      const r = await runnerService.listRuns(workspaceId, filters);
      setPage(r.data);
    } catch {
      toast.error("Failed to load run history");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, filters]);

  useEffect(() => { loadStats(); }, [loadStats]);
  useEffect(() => { loadRuns(); }, [loadRuns]);

  // ── Filter helpers ─────────────────────────────────────────────────────────
  const setFilter = (key: keyof ListRunsParams, value: string | undefined) =>
    setFilters(f => ({ ...f, [key]: value || undefined, page: 1 }));

  const handleSort = (field: string) => {
    setFilters(f => ({
      ...f,
      sort_by: field,
      sort_dir: f.sort_by === field && f.sort_dir === "desc" ? "asc" : "desc",
      page: 1,
    }));
  };

  const clearFilters = () =>
    setFilters({ page: 1, page_size: 20, sort_by: "started_at", sort_dir: "desc" });

  const hasActiveFilters = !!(filters.status || filters.trigger_type || filters.started_after || filters.started_before);

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <>
      <Header
        title="History"
        description="All test runs in this workspace"
        actions={
          <Button variant="outline" size="sm" onClick={() => { loadStats(); loadRuns(); }}>
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
            Refresh
          </Button>
        }
      />

      <div className="flex-1 overflow-auto p-6 space-y-6">

        {/* Stats cards */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {statsLoading ? (
            [...Array(4)].map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" />)
          ) : stats ? (
            <>
              <StatCard label="Total runs" value={stats.total_runs} />
              <StatCard
                label="Pass rate"
                value={`${Math.round(stats.pass_rate * 100)}%`}
                sub={`${stats.passed_runs} passed`}
              />
              <StatCard label="Failed" value={stats.failed_runs} />
              <StatCard label="Errors" value={stats.error_runs} />
            </>
          ) : null}
        </div>

        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground" />

          <Select value={filters.status ?? ""} onValueChange={v => setFilter("status", v ?? undefined)}>
            <SelectTrigger className="h-8 w-36 text-xs">
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">All statuses</SelectItem>
              <SelectItem value="passed">Passed</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
              <SelectItem value="error">Error</SelectItem>
              <SelectItem value="running">Running</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
            </SelectContent>
          </Select>

          <Select value={filters.trigger_type ?? ""} onValueChange={v => setFilter("trigger_type", v ?? undefined)}>
            <SelectTrigger className="h-8 w-36 text-xs">
              <SelectValue placeholder="All triggers" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">All triggers</SelectItem>
              <SelectItem value="manual">Manual</SelectItem>
              <SelectItem value="scheduled">Scheduled</SelectItem>
              <SelectItem value="api">API</SelectItem>
            </SelectContent>
          </Select>

          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span>From</span>
            <Input
              type="datetime-local"
              className="h-8 w-44 text-xs"
              value={(filters.started_after ?? "").slice(0, 16)}
              onChange={e => setFilter("started_after", e.target.value ? e.target.value + ":00Z" : undefined)}
            />
            <span>to</span>
            <Input
              type="datetime-local"
              className="h-8 w-44 text-xs"
              value={(filters.started_before ?? "").slice(0, 16)}
              onChange={e => setFilter("started_before", e.target.value ? e.target.value + ":00Z" : undefined)}
            />
          </div>

          {hasActiveFilters && (
            <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={clearFilters}>
              Clear filters
            </Button>
          )}
        </div>

        {/* Table */}
        <div className="rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/40">
              <tr>
                <SortTh label="Started"      field="started_at"  current={filters.sort_by!} dir={filters.sort_dir as SortDir} onSort={handleSort} />
                <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground">Collection</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground">Trigger</th>
                <SortTh label="Status"       field="status"      current={filters.sort_by!} dir={filters.sort_dir as SortDir} onSort={handleSort} />
                <SortTh label="Pass"         field="passed"      current={filters.sort_by!} dir={filters.sort_dir as SortDir} onSort={handleSort} />
                <SortTh label="Duration"     field="completed_at" current={filters.sort_by!} dir={filters.sort_dir as SortDir} onSort={handleSort} />
              </tr>
            </thead>
            <tbody>
              {loading ? (
                [...Array(5)].map((_, i) => (
                  <tr key={i} className="border-b">
                    {[...Array(6)].map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <Skeleton className="h-4 w-full" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : !page?.items.length ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-sm text-muted-foreground">
                    No runs found.{hasActiveFilters && " Try clearing the filters."}
                  </td>
                </tr>
              ) : (
                page.items.map(run => (
                  <tr
                    key={run.id}
                    className="border-b cursor-pointer hover:bg-muted/30 transition-colors"
                    onClick={() => router.push(`/workspaces/${workspaceId}/runs/${run.id}`)}
                  >
                    <td className="px-4 py-3 tabular-nums text-xs">{fmtDate(run.started_at)}</td>
                    <td className="px-4 py-3 max-w-[180px] truncate text-xs text-muted-foreground">
                      {run.collection_name ?? <span className="italic">Single request</span>}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="secondary" className="text-xs capitalize">{run.trigger_type}</Badge>
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={run.status} /></td>
                    <td className="px-4 py-3 tabular-nums text-xs">
                      {run.total > 0 ? (
                        <span>
                          <span className="text-emerald-600">{run.passed}</span>
                          <span className="text-muted-foreground">/{run.total}</span>
                        </span>
                      ) : "—"}
                    </td>
                    <td className="px-4 py-3 tabular-nums text-xs text-muted-foreground">
                      {fmt(run.duration_ms)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {page && page.pages > 1 && (
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              {page.total} run{page.total !== 1 ? "s" : ""} · page {page.page} of {page.pages}
            </span>
            <div className="flex gap-1">
              <Button
                variant="outline" size="sm"
                disabled={page.page <= 1}
                onClick={() => setFilters(f => ({ ...f, page: (f.page ?? 1) - 1 }))}
              >
                Previous
              </Button>
              <Button
                variant="outline" size="sm"
                disabled={page.page >= page.pages}
                onClick={() => setFilters(f => ({ ...f, page: (f.page ?? 1) + 1 }))}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
