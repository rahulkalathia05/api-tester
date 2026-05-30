"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  CheckCircle2,
  XCircle,
  AlertCircle,
  Clock,
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  GitCompare,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { runnerService } from "@/lib/services/runner.service";
import { Header } from "@/components/layout/Header";
import { DiffViewer } from "@/components/diff/DiffViewer";
import { AIAnalysisPanel } from "@/components/ai/AIAnalysisPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ResultDiff, ResultHistoryItem, TestResult, TestRunDetail } from "@/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(ms: number | null): string {
  if (ms === null) return "—";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium", timeStyle: "short",
  }).format(new Date(iso));
}

function fmtShort(iso: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  }).format(new Date(iso));
}

const STATUS_ICON = {
  passed:  <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
  failed:  <XCircle      className="h-4 w-4 text-red-500" />,
  error:   <AlertCircle  className="h-4 w-4 text-orange-500" />,
  skipped: <Clock        className="h-4 w-4 text-zinc-400" />,
};

const STATUS_BADGE = {
  passed:  "bg-emerald-500/15 text-emerald-600 border-emerald-200",
  failed:  "bg-red-500/15 text-red-600 border-red-200",
  error:   "bg-orange-500/15 text-orange-600 border-orange-200",
  running: "bg-blue-500/15 text-blue-600 border-blue-200",
  pending: "bg-zinc-500/15 text-zinc-600 border-zinc-200",
  skipped: "bg-zinc-500/15 text-zinc-500 border-zinc-200",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_BADGE[status as keyof typeof STATUS_BADGE] ?? STATUS_BADGE.pending;
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${cls}`}>
      {status}
    </span>
  );
}

function PassRateBar({ passed, total }: { passed: number; total: number }) {
  const pct = total > 0 ? (passed / total) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="h-2 flex-1 rounded-full bg-muted overflow-hidden">
        <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm tabular-nums text-muted-foreground w-16 text-right">
        {passed}/{total} passed
      </span>
    </div>
  );
}

const METHOD_COLORS: Record<string, string> = {
  GET:    "text-emerald-600 bg-emerald-500/10",
  POST:   "text-blue-600 bg-blue-500/10",
  PUT:    "text-amber-600 bg-amber-500/10",
  PATCH:  "text-purple-600 bg-purple-500/10",
  DELETE: "text-red-600 bg-red-500/10",
};

function MethodBadge({ method }: { method: string }) {
  const cls = METHOD_COLORS[method] ?? "text-zinc-600 bg-zinc-500/10";
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-mono font-semibold ${cls}`}>
      {method}
    </span>
  );
}

// ── Diff panel for a single result ────────────────────────────────────────────

function DiffPanel({ result }: { result: TestResult }) {
  const requestId = result.request_id;
  const [history, setHistory] = useState<ResultHistoryItem[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [diff, setDiff] = useState<ResultDiff | null>(null);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [shown, setShown] = useState(false);

  const loadHistory = useCallback(async () => {
    if (!requestId || historyLoading) return;
    setHistoryLoading(true);
    try {
      const r = await runnerService.getRequestHistory(requestId, 10);
      // Exclude the current result itself
      setHistory(r.data.filter(h => h.id !== result.id));
    } catch {
      toast.error("Failed to load execution history");
    } finally {
      setHistoryLoading(false);
    }
  }, [requestId, result.id, historyLoading]);

  const runDiff = async (compareId: string) => {
    if (!compareId) return;
    setLoading(true);
    setDiff(null);
    try {
      const r = await runnerService.diffResults(result.id, compareId);
      setDiff(r.data);
    } catch {
      toast.error("Failed to compute diff");
    } finally {
      setLoading(false);
    }
  };

  if (!shown) {
    return (
      <button
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
        onClick={() => { setShown(true); loadHistory(); }}
      >
        <GitCompare className="h-3.5 w-3.5" />
        Compare with previous
      </button>
    );
  }

  return (
    <div className="border-t bg-muted/10 p-4 space-y-4">
      <div className="flex items-center gap-3">
        <GitCompare className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-medium">Compare with</span>

        <Select
          value={selectedId}
          onValueChange={v => {
            setSelectedId(v ?? "");
            if (v) runDiff(v);
          }}
        >
          <SelectTrigger className="h-8 w-64 text-xs">
            <SelectValue placeholder={historyLoading ? "Loading…" : history.length === 0 ? "No previous executions" : "Select execution"} />
          </SelectTrigger>
          <SelectContent>
            {history.map(h => (
              <SelectItem key={h.id} value={h.id}>
                <span className="flex items-center gap-2 text-xs">
                  <span className={h.status === "passed" ? "text-emerald-600" : "text-red-600"}>
                    {h.status}
                  </span>
                  <span>HTTP {h.response_status ?? "—"}</span>
                  <span className="text-muted-foreground">{fmtShort(h.executed_at)}</span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <button
          className="ml-auto text-muted-foreground hover:text-foreground"
          onClick={() => { setShown(false); setDiff(null); setSelectedId(""); }}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {loading && (
        <div className="space-y-2">
          <Skeleton className="h-24 rounded-lg" />
          <Skeleton className="h-12 rounded-lg" />
          <Skeleton className="h-12 rounded-lg" />
        </div>
      )}

      {diff && !loading && <DiffViewer diff={diff} />}

      {!loading && !diff && selectedId && (
        <p className="text-xs text-muted-foreground italic">Select an execution above to see the diff.</p>
      )}
    </div>
  );
}

// ── Single result row ─────────────────────────────────────────────────────────

function ResultRow({ result }: { result: TestResult }) {
  const [open, setOpen] = useState(false);
  const snap = result.request_snapshot as { method?: string; url?: string; name?: string };
  const allPassed = result.assertion_results.every(a => a.passed);

  return (
    <div className="border rounded-lg overflow-hidden">
      <button
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/30 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <span className="shrink-0">
          {STATUS_ICON[result.status as keyof typeof STATUS_ICON] ?? STATUS_ICON.skipped}
        </span>
        <MethodBadge method={snap?.method ?? "?"} />
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
          {snap?.url ?? "—"}
        </span>
        <span className="shrink-0 text-xs font-medium tabular-nums">
          {result.response_status !== null && (
            <span className={result.response_status < 400 ? "text-emerald-600" : "text-red-600"}>
              {result.response_status}
            </span>
          )}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums w-14 text-right">
          {fmt(result.response_time_ms)}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground w-16 text-right">
          {result.assertion_results.length > 0 && (
            <span className={allPassed ? "text-emerald-600" : "text-red-600"}>
              {result.assertion_results.filter(a => a.passed).length}/{result.assertion_results.length}
            </span>
          )}
        </span>
        {open ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
               : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
      </button>

      {open && (
        <div className="border-t bg-muted/20">
          <Tabs defaultValue="response" className="p-4">
            <TabsList className="h-8 text-xs">
              <TabsTrigger value="response" className="text-xs">Response</TabsTrigger>
              <TabsTrigger value="headers"  className="text-xs">Headers</TabsTrigger>
              <TabsTrigger value="assertions" className="text-xs">
                Assertions
                {result.assertion_results.length > 0 && (
                  <span className={`ml-1.5 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                    allPassed ? "bg-emerald-500/15 text-emerald-600" : "bg-red-500/15 text-red-600"
                  }`}>
                    {result.assertion_results.filter(a => a.passed).length}/{result.assertion_results.length}
                  </span>
                )}
              </TabsTrigger>
              {(result.status === "failed" || result.status === "error") && (
                <TabsTrigger value="ai" className="text-xs gap-1.5">
                  <span className="text-violet-500">✦</span>
                  AI Analysis
                </TabsTrigger>
              )}
            </TabsList>

            <TabsContent value="response" className="mt-3">
              {result.error_message && (
                <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                  {result.error_message}
                </div>
              )}
              {result.response_body ? (
                <pre className="max-h-64 overflow-auto rounded-md bg-zinc-900 p-3 text-xs text-zinc-100 whitespace-pre-wrap break-all">
                  {(() => {
                    try { return JSON.stringify(JSON.parse(result.response_body), null, 2); }
                    catch { return result.response_body; }
                  })()}
                </pre>
              ) : (
                <p className="text-xs text-muted-foreground italic">No response body</p>
              )}
            </TabsContent>

            <TabsContent value="headers" className="mt-3">
              {Object.keys(result.response_headers).length === 0 ? (
                <p className="text-xs text-muted-foreground italic">No headers captured</p>
              ) : (
                <div className="space-y-1">
                  {Object.entries(result.response_headers).map(([k, v]) => (
                    <div key={k} className="flex gap-3 text-xs">
                      <span className="w-48 shrink-0 truncate font-mono text-muted-foreground">{k}</span>
                      <span className="font-mono text-foreground break-all">{v}</span>
                    </div>
                  ))}
                </div>
              )}
            </TabsContent>

            <TabsContent value="assertions" className="mt-3">
              {result.assertion_results.length === 0 ? (
                <p className="text-xs text-muted-foreground italic">No assertions defined</p>
              ) : (
                <div className="space-y-2">
                  {result.assertion_results.map(ar => (
                    <div key={ar.id} className={`flex items-start gap-2 rounded-md px-3 py-2 text-xs ${
                      ar.passed ? "bg-emerald-500/8 border border-emerald-200" : "bg-red-500/8 border border-red-200"
                    }`}>
                      {ar.passed
                        ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                        : <XCircle      className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" />}
                      <div className="min-w-0">
                        <span className="font-mono text-muted-foreground">
                          {ar.assertion_snapshot.type}
                          {ar.assertion_snapshot.path && ` (${ar.assertion_snapshot.path})`}
                        </span>
                        {" "}<span>{ar.assertion_snapshot.operator}</span>
                        {" "}<span className="font-semibold">{ar.assertion_snapshot.expected_value}</span>
                        {ar.actual_value !== null && (
                          <span className="block text-muted-foreground">
                            actual: <span className="font-semibold text-foreground">{ar.actual_value}</span>
                          </span>
                        )}
                        {ar.error_message && (
                          <span className="block text-red-600">{ar.error_message}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </TabsContent>

            {/* AI Analysis tab */}
            {(result.status === "failed" || result.status === "error") && (
              <TabsContent value="ai" className="mt-3">
                <AIAnalysisPanel resultId={result.id} resultStatus={result.status} />
              </TabsContent>
            )}
          </Tabs>

          {/* Diff panel — always available for any result */}
          {result.request_id && <DiffPanel result={result} />}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function RunDetailPage() {
  const { id: workspaceId, rid: runId } = useParams<{ id: string; rid: string }>();
  const router = useRouter();
  const [run, setRun] = useState<TestRunDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!runId) return;
    runnerService.getRun(runId)
      .then(r => setRun(r.data))
      .catch(() => toast.error("Failed to load run"))
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading) {
    return (
      <>
        <Header title="Run detail" />
        <div className="p-6 space-y-4">
          <Skeleton className="h-28 rounded-lg" />
          <Skeleton className="h-16 rounded-lg" />
          <Skeleton className="h-16 rounded-lg" />
        </div>
      </>
    );
  }

  if (!run) {
    return (
      <>
        <Header title="Run not found" />
        <div className="flex h-64 items-center justify-center text-muted-foreground">
          <p className="text-sm">This run does not exist or you don't have access to it.</p>
        </div>
      </>
    );
  }

  const duration = run.duration_ms !== null ? fmt(run.duration_ms)
    : (run.started_at && run.completed_at)
      ? fmt(new Date(run.completed_at).getTime() - new Date(run.started_at).getTime())
      : "—";

  return (
    <>
      <Header
        title="Run detail"
        description={fmtDate(run.started_at)}
        actions={
          <Button variant="outline" size="sm"
                  onClick={() => router.push(`/workspaces/${workspaceId}/history`)}>
            <ArrowLeft className="mr-1.5 h-3.5 w-3.5" />
            Back to history
          </Button>
        }
      />

      <div className="flex-1 overflow-auto p-6 space-y-6">
        {/* Run summary */}
        <div className="rounded-lg border bg-card p-4 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <StatusBadge status={run.status} />
                <span className="text-sm font-medium">{run.collection_name ?? "Single request"}</span>
                <Badge variant="secondary" className="text-xs capitalize">{run.trigger_type}</Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                Started {fmtDate(run.started_at)} · Duration {duration}
              </p>
            </div>
            <div className="flex gap-6 text-sm">
              <div className="text-center">
                <p className="text-xl font-semibold tabular-nums text-emerald-600">{run.passed}</p>
                <p className="text-xs text-muted-foreground">Passed</p>
              </div>
              <div className="text-center">
                <p className="text-xl font-semibold tabular-nums text-red-600">{run.failed}</p>
                <p className="text-xs text-muted-foreground">Failed</p>
              </div>
              <div className="text-center">
                <p className="text-xl font-semibold tabular-nums">{run.total}</p>
                <p className="text-xs text-muted-foreground">Total</p>
              </div>
            </div>
          </div>
          {run.total > 0 && <PassRateBar passed={run.passed} total={run.total} />}
        </div>

        {/* Results */}
        <div className="space-y-2">
          {run.results.length === 0 ? (
            <div className="flex h-32 items-center justify-center rounded-lg border text-sm text-muted-foreground">
              No results yet — the run may still be processing.
            </div>
          ) : (
            run.results.map(result => (
              <ResultRow key={result.id} result={result} />
            ))
          )}
        </div>
      </div>
    </>
  );
}
