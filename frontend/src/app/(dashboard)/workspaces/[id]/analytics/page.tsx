"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { toast } from "sonner";
import { analyticsService } from "@/lib/services/analytics.service";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { Header } from "@/components/layout/Header";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { WorkspaceAnalytics, EndpointStat, CollectionStat } from "@/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function pct(v: number) { return `${Math.round(v * 100)}%`; }
function ms(v: number | null) {
  if (v === null) return "—";
  return v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`;
}
function fmtDate(d: string) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(new Date(d + "T00:00:00"));
}

// ── KPI card ──────────────────────────────────────────────────────────────────

function KpiCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: "green" | "red" | "amber" | "blue";
}) {
  const colors = {
    green: "text-emerald-600",
    red:   "text-red-600",
    amber: "text-amber-600",
    blue:  "text-blue-600",
  };
  return (
    <div className="rounded-lg border bg-card p-4 space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-2xl font-semibold tabular-nums ${accent ? colors[accent] : ""}`}>
        {value}
      </p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

// ── Method badge ──────────────────────────────────────────────────────────────

const METHOD_COLORS: Record<string, string> = {
  GET:    "text-emerald-700 bg-emerald-500/10",
  POST:   "text-blue-700 bg-blue-500/10",
  PUT:    "text-amber-700 bg-amber-500/10",
  PATCH:  "text-purple-700 bg-purple-500/10",
  DELETE: "text-red-700 bg-red-500/10",
};
function MethodBadge({ method }: { method: string }) {
  const cls = METHOD_COLORS[method] ?? "text-zinc-600 bg-zinc-500/10";
  return <span className={`rounded px-1.5 py-0.5 text-[11px] font-mono font-semibold ${cls}`}>{method}</span>;
}

// ── Latency bar ───────────────────────────────────────────────────────────────

function LatencyBar({ value, max }: { value: number; max: number }) {
  const pctVal = max > 0 ? (value / max) * 100 : 0;
  const color = value > 1000 ? "bg-red-500" : value > 500 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pctVal}%` }} />
      </div>
      <span className="w-14 text-right text-xs tabular-nums text-muted-foreground">{ms(value)}</span>
    </div>
  );
}

// ── Pass rate pill ────────────────────────────────────────────────────────────

function PassRatePill({ rate }: { rate: number }) {
  const cls = rate >= 0.9 ? "bg-emerald-500/15 text-emerald-700"
    : rate >= 0.7          ? "bg-amber-500/15 text-amber-700"
                           : "bg-red-500/15 text-red-700";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {pct(rate)}
    </span>
  );
}

// ── Slowest endpoints table ───────────────────────────────────────────────────

function EndpointsTable({ endpoints }: { endpoints: EndpointStat[] }) {
  const maxAvg = Math.max(...endpoints.map(e => e.avg_response_time_ms), 1);

  if (endpoints.length === 0) {
    return (
      <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">
        No execution data yet
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th className="text-left px-4 py-2 text-xs font-medium text-muted-foreground">Endpoint</th>
            <th className="text-left px-4 py-2 text-xs font-medium text-muted-foreground">Avg latency</th>
            <th className="text-center px-4 py-2 text-xs font-medium text-muted-foreground">Max</th>
            <th className="text-center px-4 py-2 text-xs font-medium text-muted-foreground">Runs</th>
            <th className="text-center px-4 py-2 text-xs font-medium text-muted-foreground">Pass rate</th>
          </tr>
        </thead>
        <tbody>
          {endpoints.map((ep, i) => (
            <tr key={ep.request_id ?? i} className="border-b last:border-0 hover:bg-muted/20">
              <td className="px-4 py-2.5">
                <div className="flex items-center gap-2">
                  <MethodBadge method={ep.method} />
                  <span className="text-xs font-medium">{ep.name}</span>
                </div>
                <p className="mt-0.5 text-[11px] font-mono text-muted-foreground truncate max-w-[280px]">
                  {ep.url}
                </p>
              </td>
              <td className="px-4 py-2.5 w-48">
                <LatencyBar value={ep.avg_response_time_ms} max={maxAvg} />
              </td>
              <td className="px-4 py-2.5 text-center text-xs tabular-nums text-muted-foreground">
                {ms(ep.max_response_time_ms)}
              </td>
              <td className="px-4 py-2.5 text-center text-xs tabular-nums">
                {ep.total_executions}
              </td>
              <td className="px-4 py-2.5 text-center">
                <PassRatePill rate={ep.pass_rate} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Collection stats table ────────────────────────────────────────────────────

function CollectionsTable({ collections }: { collections: CollectionStat[] }) {
  if (collections.length === 0) {
    return (
      <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">
        No collection runs yet
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th className="text-left px-4 py-2 text-xs font-medium text-muted-foreground">Collection</th>
            <th className="text-center px-4 py-2 text-xs font-medium text-muted-foreground">Runs</th>
            <th className="text-left px-4 py-2 text-xs font-medium text-muted-foreground w-48">Pass rate</th>
            <th className="text-center px-4 py-2 text-xs font-medium text-muted-foreground">Avg latency</th>
          </tr>
        </thead>
        <tbody>
          {collections.map(col => (
            <tr key={col.collection_id} className="border-b last:border-0 hover:bg-muted/20">
              <td className="px-4 py-2.5 font-medium text-sm">{col.collection_name}</td>
              <td className="px-4 py-2.5 text-center text-xs tabular-nums">{col.total_runs}</td>
              <td className="px-4 py-2.5">
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                    <div
                      className={`h-full rounded-full ${col.pass_rate >= 0.9 ? "bg-emerald-500" : col.pass_rate >= 0.7 ? "bg-amber-500" : "bg-red-500"}`}
                      style={{ width: `${col.pass_rate * 100}%` }}
                    />
                  </div>
                  <span className="text-xs tabular-nums w-10 text-right">{pct(col.pass_rate)}</span>
                </div>
              </td>
              <td className="px-4 py-2.5 text-center text-xs tabular-nums text-muted-foreground">
                {ms(col.avg_response_time_ms)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Custom recharts tooltip ───────────────────────────────────────────────────

function TrendTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const total   = (payload.find((p: any) => p.dataKey === "passed")?.value ?? 0) +
                  (payload.find((p: any) => p.dataKey === "failed")?.value ?? 0);
  return (
    <div className="rounded-lg border bg-background shadow-md px-3 py-2 text-xs space-y-1">
      <p className="font-medium">{fmtDate(label)}</p>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="capitalize text-muted-foreground">{p.dataKey}:</span>
          <span className="font-medium">{p.value}</span>
        </div>
      ))}
      {total > 0 && (
        <p className="text-muted-foreground border-t pt-1">
          Pass rate: {pct((payload.find((p: any) => p.dataKey === "passed")?.value ?? 0) / total)}
        </p>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const DAY_OPTIONS = [
  { label: "Last 7 days",  value: "7" },
  { label: "Last 30 days", value: "30" },
  { label: "Last 90 days", value: "90" },
];

export default function AnalyticsPage() {
  const { id: workspaceId } = useParams<{ id: string }>();
  const { activeWorkspace } = useWorkspaceStore();

  const [days, setDays] = useState(30);
  const [data, setData] = useState<WorkspaceAnalytics | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    try {
      const r = await analyticsService.getWorkspaceAnalytics(workspaceId, days);
      setData(r.data);
    } catch {
      toast.error("Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, days]);

  useEffect(() => { load(); }, [load]);

  const s = data?.summary;

  return (
    <>
      <Header
        title="Analytics"
        description={activeWorkspace?.name ?? "Workspace analytics"}
        actions={
          <Select value={String(days)} onValueChange={v => setDays(Number(v))}>
            <SelectTrigger className="h-8 w-36 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DAY_OPTIONS.map(o => (
                <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />

      <div className="flex-1 overflow-auto p-6 space-y-6">

        {/* ── KPI cards ─────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {loading ? (
            [...Array(5)].map((_, i) => <Skeleton key={i} className="h-24 rounded-lg" />)
          ) : s ? (
            <>
              <KpiCard label="Total runs"    value={s.total_runs} />
              <KpiCard label="Success rate"  value={pct(s.pass_rate)}
                        accent={s.pass_rate >= 0.9 ? "green" : s.pass_rate >= 0.7 ? "amber" : "red"}
                        sub={`${s.passed_runs} passed`} />
              <KpiCard label="Failure rate"
                        value={pct(s.total_runs > 0 ? (s.failed_runs + s.error_runs) / s.total_runs : 0)}
                        accent={s.failed_runs + s.error_runs > 0 ? "red" : undefined}
                        sub={`${s.failed_runs} failed · ${s.error_runs} errors`} />
              <KpiCard label="Avg latency"   value={ms(s.avg_response_time_ms)}
                        accent={s.avg_response_time_ms !== null && s.avg_response_time_ms > 1000 ? "amber" : undefined}
                        sub={`p95: ${ms(s.p95_response_time_ms)}`} />
              <KpiCard label="Total executions" value={s.total_executions}
                        sub={`${s.passed_executions} passed`} />
            </>
          ) : null}
        </div>

        {/* ── Trend chart ────────────────────────────────────────────────────── */}
        <div className="rounded-lg border bg-card p-5">
          <h2 className="text-sm font-semibold mb-4">Pass / fail trend</h2>
          {loading ? (
            <Skeleton className="h-52" />
          ) : !data?.daily_trend.length ? (
            <div className="flex h-52 items-center justify-center text-sm text-muted-foreground">
              No run data in the selected period
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={data.daily_trend} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
                <defs>
                  <linearGradient id="gPassed" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#10b981" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gFailed" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#ef4444" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis
                  dataKey="date"
                  tickFormatter={fmtDate}
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip content={<TrendTooltip />} />
                <Legend
                  wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                  formatter={(value: string) => <span className="capitalize text-muted-foreground">{value}</span>}
                />
                <Area
                  type="monotone" dataKey="passed"
                  stroke="#10b981" strokeWidth={2}
                  fill="url(#gPassed)"
                />
                <Area
                  type="monotone" dataKey="failed"
                  stroke="#ef4444" strokeWidth={2}
                  fill="url(#gFailed)"
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* ── Bottom tables ──────────────────────────────────────────────────── */}
        <div className="grid gap-4 lg:grid-cols-2">

          {/* Slowest endpoints */}
          <div className="rounded-lg border bg-card">
            <div className="border-b px-5 py-3">
              <h2 className="text-sm font-semibold">Slowest endpoints</h2>
              <p className="text-xs text-muted-foreground">Top 10 by average response time</p>
            </div>
            {loading
              ? <div className="p-4 space-y-2">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
              : <EndpointsTable endpoints={data?.slowest_endpoints ?? []} />
            }
          </div>

          {/* Collection reliability */}
          <div className="rounded-lg border bg-card">
            <div className="border-b px-5 py-3">
              <h2 className="text-sm font-semibold">Collection reliability</h2>
              <p className="text-xs text-muted-foreground">Pass rate per collection</p>
            </div>
            {loading
              ? <div className="p-4 space-y-2">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
              : <CollectionsTable collections={data?.collection_stats ?? []} />
            }
          </div>

        </div>
      </div>
    </>
  );
}
