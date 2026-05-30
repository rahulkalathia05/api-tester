"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ChevronUp, ChevronDown, ChevronsUpDown, Filter, RefreshCw,
  CheckCircle2, XCircle, AlertCircle, Clock, ExternalLink,
  ChevronRight, ChevronDown as ChevronDownIcon,
} from "lucide-react";
import { toast } from "sonner";
import { runnerService, type ListRunsParams } from "@/lib/services/runner.service";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AIAnalysisPanel } from "@/components/ai/AIAnalysisPanel";
import type { PaginatedResponse, RunStats, TestRun, TestRunDetail, TestResult, SortDir } from "@/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtMs(ms: number | null): { text: string; color: string } {
  if (ms === null) return { text: "—", color: "text-muted-foreground" };
  const text = ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
  const color = ms < 500 ? "text-emerald-600" : ms < 2000 ? "text-amber-600" : "text-red-600";
  return { text, color };
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(iso));
}

function fmtDateFull(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium", timeStyle: "short",
  }).format(new Date(iso));
}

const STATUS_CFG = {
  passed:  { label: "Passed",  cls: "bg-emerald-500/15 text-emerald-600 border-emerald-200", icon: CheckCircle2 },
  failed:  { label: "Failed",  cls: "bg-red-500/15 text-red-600 border-red-200",             icon: XCircle },
  error:   { label: "Error",   cls: "bg-orange-500/15 text-orange-600 border-orange-200",     icon: AlertCircle },
  running: { label: "Running", cls: "bg-blue-500/15 text-blue-600 border-blue-200",           icon: RefreshCw },
  pending: { label: "Pending", cls: "bg-zinc-500/15 text-zinc-500 border-zinc-200",           icon: Clock },
  cancelled: { label: "Cancelled", cls: "bg-zinc-500/15 text-zinc-500 border-zinc-200",      icon: Clock },
} as const;

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CFG[status as keyof typeof STATUS_CFG] ?? STATUS_CFG.pending;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${cfg.cls}`}>
      {status === "running" && <cfg.icon className="h-3 w-3 animate-spin" />}
      {cfg.label}
    </span>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, accent }: {
  label: string; value: string | number; sub?: string;
  accent?: "green" | "red" | "amber";
}) {
  const colors = { green: "text-emerald-600", red: "text-red-600", amber: "text-amber-600" };
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${accent ? colors[accent] : ""}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

// ── Sort header ───────────────────────────────────────────────────────────────

function SortTh({ label, field, current, dir, onSort }: {
  label: string; field: string; current: string; dir: SortDir;
  onSort: (f: string) => void;
}) {
  const active = current === field;
  const Icon = active ? (dir === "asc" ? ChevronUp : ChevronDown) : ChevronsUpDown;
  return (
    <th className="cursor-pointer select-none whitespace-nowrap px-4 py-3 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
      onClick={() => onSort(field)}>
      <span className="flex items-center gap-1">{label}<Icon className="h-3 w-3" /></span>
    </th>
  );
}

// ── Pass rate bar ─────────────────────────────────────────────────────────────

function PassBar({ passed, total }: { passed: number; total: number }) {
  if (total === 0) return <span className="text-muted-foreground text-xs">—</span>;
  const pct = (passed / total) * 100;
  return (
    <div className="flex items-center gap-2 min-w-[80px]">
      <div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${pct === 100 ? "bg-emerald-500" : pct > 50 ? "bg-amber-500" : "bg-red-500"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`text-xs tabular-nums ${pct === 100 ? "text-emerald-600" : pct > 50 ? "text-amber-600" : "text-red-600"}`}>
        {passed}/{total}
      </span>
    </div>
  );
}

// ── Execution Details Drawer ──────────────────────────────────────────────────

function ResultRow({ result }: { result: TestResult }) {
  const [open, setOpen] = useState(false);
  const snap = result.request_snapshot as any;
  const allPassed = result.assertion_results.every(a => a.passed);
  const cfg = STATUS_CFG[result.status as keyof typeof STATUS_CFG] ?? STATUS_CFG.pending;
  const { text: latText, color: latColor } = fmtMs(result.response_time_ms);

  return (
    <div className="border rounded-lg overflow-hidden text-xs">
      <button
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-muted/30 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <span className={`h-2 w-2 rounded-full shrink-0 ${cfg.cls.includes("emerald") ? "bg-emerald-500" : cfg.cls.includes("red") ? "bg-red-500" : cfg.cls.includes("orange") ? "bg-orange-500" : "bg-zinc-400"}`} />
        <span className={`rounded px-1 py-0.5 font-mono font-semibold text-[10px] ${snap?.method === "GET" ? "text-emerald-600 bg-emerald-500/10" : snap?.method === "POST" ? "text-blue-600 bg-blue-500/10" : snap?.method === "DELETE" ? "text-red-600 bg-red-500/10" : "text-amber-600 bg-amber-500/10"}`}>
          {snap?.method}
        </span>
        <span className="flex-1 truncate font-medium">{snap?.name}</span>
        {result.response_status && (
          <span className={`font-mono font-semibold ${result.response_status < 400 ? "text-emerald-600" : "text-red-600"}`}>
            {result.response_status}
          </span>
        )}
        <span className={`tabular-nums ${latColor}`}>{latText}</span>
        {result.assertion_results.length > 0 && (
          <span className={`${allPassed ? "text-emerald-600" : "text-red-600"}`}>
            {result.assertion_results.filter(a => a.passed).length}/{result.assertion_results.length} assertions
          </span>
        )}
        {open ? <ChevronDownIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
               : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
      </button>

      {open && (
        <div className="border-t bg-muted/20">
          <Tabs defaultValue={result.status === "failed" || result.status === "error" ? "ai" : "response"} className="p-3">
            <TabsList className="h-7 text-xs mb-3">
              <TabsTrigger value="response" className="text-xs">Response</TabsTrigger>
              <TabsTrigger value="assertions" className="text-xs">
                Assertions {result.assertion_results.length > 0 && (
                  <span className={`ml-1 text-[10px] ${allPassed ? "text-emerald-600" : "text-red-600"}`}>
                    ({result.assertion_results.filter(a => a.passed).length}/{result.assertion_results.length})
                  </span>
                )}
              </TabsTrigger>
              {(result.status === "failed" || result.status === "error") && (
                <TabsTrigger value="ai" className="text-xs gap-1">
                  <span className="text-violet-500">✦</span>AI
                </TabsTrigger>
              )}
            </TabsList>

            <TabsContent value="response" className="mt-0 space-y-2">
              {result.error_message && (
                <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                  {result.error_message}
                </div>
              )}
              {result.response_body ? (
                <pre className="max-h-48 overflow-auto rounded bg-zinc-950 p-2.5 text-[11px] text-zinc-100 whitespace-pre-wrap break-all">
                  {(() => { try { return JSON.stringify(JSON.parse(result.response_body!), null, 2); } catch { return result.response_body; } })()}
                </pre>
              ) : <p className="text-xs text-muted-foreground italic">No response body</p>}
            </TabsContent>

            <TabsContent value="assertions" className="mt-0">
              {result.assertion_results.length === 0 ? (
                <p className="text-xs text-muted-foreground italic">No assertions</p>
              ) : (
                <div className="space-y-1.5">
                  {result.assertion_results.map(ar => (
                    <div key={ar.id} className={`flex items-start gap-2 rounded border px-2.5 py-1.5 ${ar.passed ? "border-emerald-200 bg-emerald-500/5" : "border-red-200 bg-red-500/5"}`}>
                      {ar.passed ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500 mt-0.5" />
                                 : <XCircle className="h-3.5 w-3.5 shrink-0 text-red-500 mt-0.5" />}
                      <div>
                        <span className="font-mono text-muted-foreground">{ar.assertion_snapshot?.type}</span>
                        {" "}<span>{ar.assertion_snapshot?.operator}</span>
                        {" "}<span className="font-semibold">{ar.assertion_snapshot?.expected_value}</span>
                        {ar.actual_value != null && (
                          <span className="block text-muted-foreground">actual: <span className="font-semibold text-foreground">{ar.actual_value}</span></span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </TabsContent>

            {(result.status === "failed" || result.status === "error") && (
              <TabsContent value="ai" className="mt-0">
                <AIAnalysisPanel resultId={result.id} resultStatus={result.status} />
              </TabsContent>
            )}
          </Tabs>
        </div>
      )}
    </div>
  );
}

function RunDetailsDrawer({
  runId, workspaceId, open, onClose,
}: { runId: string | null; workspaceId: string; open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [detail, setDetail] = useState<TestRunDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!runId || !open) return;
    setDetail(null);
    setLoading(true);
    runnerService.getRun(runId)
      .then(r => setDetail(r.data))
      .catch(() => toast.error("Failed to load run details"))
      .finally(() => setLoading(false));
  }, [runId, open]);

  const run = detail;
  const duration = run?.duration_ms !== null ? fmtMs(run?.duration_ms ?? null).text
    : run?.started_at && run?.completed_at
      ? fmtMs(new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()).text
      : "—";

  return (
    <Sheet open={open} onOpenChange={v => !v && onClose()}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto p-0">
        <SheetHeader className="border-b px-6 py-4 sticky top-0 bg-background z-10">
          <div className="flex items-center justify-between">
            <SheetTitle className="text-base">Run Details</SheetTitle>
            {run && (
              <Button variant="ghost" size="sm" className="gap-1.5 text-xs"
                onClick={() => { onClose(); router.push(`/workspaces/${workspaceId}/runs/${run.id}`); }}>
                <ExternalLink className="h-3.5 w-3.5" /> Full page
              </Button>
            )}
          </div>
        </SheetHeader>

        <div className="p-6 space-y-5">
          {loading ? (
            <div className="space-y-3">
              <Skeleton className="h-24 rounded-lg" />
              <Skeleton className="h-16 rounded-lg" />
              <Skeleton className="h-16 rounded-lg" />
            </div>
          ) : !run ? null : (
            <>
              {/* Summary card */}
              <div className="rounded-lg border bg-card p-4 space-y-3">
                <div className="flex items-start justify-between gap-4 flex-wrap">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <StatusBadge status={run.status} />
                      <span className="font-semibold text-sm">{run.collection_name ?? "Single request"}</span>
                      <Badge variant="secondary" className="text-xs capitalize">{run.trigger_type}</Badge>
                    </div>
                    <p className="mt-1.5 text-xs text-muted-foreground">
                      Started {fmtDateFull(run.started_at)} · Duration {duration}
                    </p>
                  </div>
                  <div className="flex gap-5 text-center">
                    {[
                      { n: run.passed, label: "Passed", color: "text-emerald-600" },
                      { n: run.failed, label: "Failed", color: "text-red-600" },
                      { n: run.total,  label: "Total",  color: "" },
                    ].map(({ n, label, color }) => (
                      <div key={label}>
                        <p className={`text-lg font-bold tabular-nums ${color}`}>{n}</p>
                        <p className="text-[11px] text-muted-foreground">{label}</p>
                      </div>
                    ))}
                  </div>
                </div>

                {run.total > 0 && (
                  <div className="flex items-center gap-3">
                    <div className="h-2 flex-1 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full rounded-full bg-emerald-500 transition-all"
                        style={{ width: `${(run.passed / run.total) * 100}%` }}
                      />
                    </div>
                    <span className="text-xs tabular-nums text-muted-foreground w-16 text-right">
                      {run.passed}/{run.total} passed
                    </span>
                  </div>
                )}
              </div>

              {/* Results */}
              <div>
                <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wide">
                  Requests ({run.results.length})
                </p>
                {run.results.length === 0 ? (
                  <div className="flex h-24 items-center justify-center rounded-lg border text-xs text-muted-foreground">
                    No results yet — run may still be processing
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {run.results.map(r => <ResultRow key={r.id} result={r} />)}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function HistoryPage() {
  const { id: workspaceId } = useParams<{ id: string }>();
  const { activeWorkspace } = useWorkspaceStore();

  const [stats, setStats] = useState<RunStats | null>(null);
  const [page, setPage] = useState<PaginatedResponse<TestRun> | null>(null);
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const [filters, setFilters] = useState<ListRunsParams>({
    page: 1, page_size: 20, sort_by: "started_at", sort_dir: "desc",
  });

  const autoRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Load data ───────────────────────────────────────────────────────────────

  const loadStats = useCallback(async () => {
    if (!workspaceId) return;
    setStatsLoading(true);
    try { setStats((await runnerService.getStats(workspaceId)).data); }
    catch { /* silent */ }
    finally { setStatsLoading(false); }
  }, [workspaceId]);

  const loadRuns = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    try {
      const r = await runnerService.listRuns(workspaceId, filters);
      setPage(r.data);

      // Auto-refresh if any run is pending/running
      const hasLive = r.data.items.some(run => ["pending", "running"].includes(run.status));
      if (hasLive) {
        if (!autoRefreshRef.current) {
          autoRefreshRef.current = setInterval(() => {
            runnerService.listRuns(workspaceId, filters).then(fresh => setPage(fresh.data));
          }, 3000);
        }
      } else {
        if (autoRefreshRef.current) { clearInterval(autoRefreshRef.current); autoRefreshRef.current = null; }
      }
    } catch {
      toast.error("Failed to load run history");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, filters]);

  useEffect(() => { loadStats(); }, [loadStats]);
  useEffect(() => { loadRuns(); }, [loadRuns]);
  useEffect(() => () => { if (autoRefreshRef.current) clearInterval(autoRefreshRef.current); }, []);

  // ── Filter / sort helpers ────────────────────────────────────────────────────

  const setFilter = (key: keyof ListRunsParams, value: string | undefined) =>
    setFilters(f => ({ ...f, [key]: value || undefined, page: 1 }));

  const handleSort = (field: string) =>
    setFilters(f => ({
      ...f, sort_by: field,
      sort_dir: f.sort_by === field && f.sort_dir === "desc" ? "asc" : "desc",
      page: 1,
    }));

  const clearFilters = () =>
    setFilters({ page: 1, page_size: 20, sort_by: "started_at", sort_dir: "desc" });

  const hasActiveFilters = !!(filters.status || filters.trigger_type || filters.started_after || filters.started_before);

  const openDrawer = (runId: string) => { setSelectedRunId(runId); setDrawerOpen(true); };

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <>
      <Header
        title="History"
        description="All test runs in this workspace"
        actions={
          <div className="flex items-center gap-2">
            {autoRefreshRef.current && (
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <RefreshCw className="h-3 w-3 animate-spin" /> Auto-refreshing
              </span>
            )}
            <Button variant="outline" size="sm" onClick={() => { loadStats(); loadRuns(); }}>
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" />Refresh
            </Button>
          </div>
        }
      />

      <div className="flex-1 overflow-auto p-6 space-y-5">

        {/* Stats */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {statsLoading
            ? [...Array(4)].map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" />)
            : stats ? <>
                <StatCard label="Total runs" value={stats.total_runs} />
                <StatCard label="Pass rate"
                  value={`${Math.round(stats.pass_rate * 100)}%`}
                  sub={`${stats.passed_runs} passed`}
                  accent={stats.pass_rate >= 0.9 ? "green" : stats.pass_rate >= 0.7 ? "amber" : "red"}
                />
                <StatCard label="Failed" value={stats.failed_runs} accent={stats.failed_runs > 0 ? "red" : undefined} />
                <StatCard label="Errors"  value={stats.error_runs}  accent={stats.error_runs > 0 ? "amber" : undefined} />
              </> : null
          }
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground shrink-0" />

          <Select value={filters.status ?? ""} onValueChange={v => setFilter("status", v ?? undefined)}>
            <SelectTrigger className="h-8 w-36 text-xs"><SelectValue placeholder="All statuses" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="">All statuses</SelectItem>
              {["passed", "failed", "error", "running", "pending"].map(s => (
                <SelectItem key={s} value={s} className="capitalize">{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={filters.trigger_type ?? ""} onValueChange={v => setFilter("trigger_type", v ?? undefined)}>
            <SelectTrigger className="h-8 w-36 text-xs"><SelectValue placeholder="All triggers" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="">All triggers</SelectItem>
              {["manual", "scheduled", "api"].map(t => (
                <SelectItem key={t} value={t} className="capitalize">{t}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span>From</span>
            <Input type="datetime-local" className="h-8 w-44 text-xs"
              value={(filters.started_after ?? "").slice(0, 16)}
              onChange={e => setFilter("started_after", e.target.value ? e.target.value + ":00Z" : undefined)} />
            <span>to</span>
            <Input type="datetime-local" className="h-8 w-44 text-xs"
              value={(filters.started_before ?? "").slice(0, 16)}
              onChange={e => setFilter("started_before", e.target.value ? e.target.value + ":00Z" : undefined)} />
          </div>

          {hasActiveFilters && (
            <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={clearFilters}>
              Clear filters
            </Button>
          )}

          <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
            <span>Show</span>
            <Select value={String(filters.page_size ?? 20)} onValueChange={v => setFilters(f => ({ ...f, page_size: Number(v), page: 1 }))}>
              <SelectTrigger className="h-8 w-20 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {[10, 20, 50].map(n => <SelectItem key={n} value={String(n)}>{n} rows</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Table */}
        <div className="rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/40">
              <tr>
                <SortTh label="Started"    field="started_at"   current={filters.sort_by!} dir={filters.sort_dir as SortDir} onSort={handleSort} />
                <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground">Collection</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground">Trigger</th>
                <SortTh label="Status"     field="status"       current={filters.sort_by!} dir={filters.sort_dir as SortDir} onSort={handleSort} />
                <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground min-w-[120px]">Pass rate</th>
                <SortTh label="Duration"   field="completed_at" current={filters.sort_by!} dir={filters.sort_dir as SortDir} onSort={handleSort} />
              </tr>
            </thead>
            <tbody>
              {loading ? (
                [...Array(5)].map((_, i) => (
                  <tr key={i} className="border-b">
                    {[...Array(6)].map((_, j) => (
                      <td key={j} className="px-4 py-3"><Skeleton className="h-4 w-full" /></td>
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
                page.items.map(run => {
                  const { text: durText, color: durColor } = fmtMs(run.duration_ms);
                  return (
                    <tr
                      key={run.id}
                      className="border-b cursor-pointer hover:bg-muted/30 transition-colors"
                      onClick={() => openDrawer(run.id)}
                    >
                      <td className="px-4 py-3 tabular-nums text-xs whitespace-nowrap">{fmtDate(run.started_at)}</td>
                      <td className="px-4 py-3 max-w-[160px] truncate text-xs text-muted-foreground">
                        {run.collection_name ?? <span className="italic">Single request</span>}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant="secondary" className="text-xs capitalize">{run.trigger_type}</Badge>
                      </td>
                      <td className="px-4 py-3"><StatusBadge status={run.status} /></td>
                      <td className="px-4 py-3">
                        <PassBar passed={run.passed} total={run.total} />
                      </td>
                      <td className={`px-4 py-3 tabular-nums text-xs ${durColor}`}>{durText}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {page && page.pages > 1 && (
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground text-xs">
              {page.total} run{page.total !== 1 ? "s" : ""} · page {page.page} of {page.pages}
            </span>
            <div className="flex gap-1">
              <Button variant="outline" size="sm"
                disabled={page.page <= 1}
                onClick={() => setFilters(f => ({ ...f, page: (f.page ?? 1) - 1 }))}>
                Previous
              </Button>
              <Button variant="outline" size="sm"
                disabled={page.page >= page.pages}
                onClick={() => setFilters(f => ({ ...f, page: (f.page ?? 1) + 1 }))}>
                Next
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Execution details drawer */}
      <RunDetailsDrawer
        runId={selectedRunId}
        workspaceId={workspaceId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </>
  );
}
