"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, PieChart, Pie, Cell,
  BarChart, Bar, LineChart, Line,
} from "recharts";
import { RefreshCw, Zap, CheckCircle2, XCircle, Clock, Activity, TrendingUp, TrendingDown } from "lucide-react";
import { toast } from "sonner";
import { analyticsService } from "@/lib/services/analytics.service";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { Header } from "@/components/layout/Header";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { WorkspaceAnalytics, EndpointStat, CollectionStat } from "@/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function pct(v: number) { return `${Math.round(v * 100)}%`; }
function fmtMs(v: number | null) {
  if (v === null) return "—";
  return v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`;
}
function fmtDate(d: string) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(new Date(d + "T00:00:00"));
}

// ── KPI card ──────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, accent, icon: Icon }: {
  label: string; value: string | number; sub?: string;
  accent?: "green" | "red" | "amber" | "blue"; icon: React.ElementType;
}) {
  const textColor = { green: "text-emerald-600", red: "text-red-600", amber: "text-amber-600", blue: "text-blue-600" };
  const bgColor   = { green: "bg-emerald-500/10", red: "bg-red-500/10", amber: "bg-amber-500/10", blue: "bg-blue-500/10" };
  return (
    <div className="rounded-xl border bg-card p-5 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <div className={`rounded-lg p-2 ${accent ? bgColor[accent] : "bg-muted"}`}>
          <Icon className={`h-4 w-4 ${accent ? textColor[accent] : "text-muted-foreground"}`} />
        </div>
      </div>
      <div>
        <p className={`text-2xl font-bold tabular-nums ${accent ? textColor[accent] : ""}`}>{value}</p>
        {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
      </div>
    </div>
  );
}

// ── Insight banner ────────────────────────────────────────────────────────────

function InsightBanner({ data, days }: { data: WorkspaceAnalytics; days: number }) {
  const s = data.summary;
  if (s.total_runs === 0) return null;
  const insights: { text: string; good: boolean }[] = [];

  if (s.pass_rate >= 0.95) insights.push({ text: `${pct(s.pass_rate)} pass rate — excellent reliability`, good: true });
  else if (s.pass_rate < 0.7) insights.push({ text: `${pct(s.pass_rate)} pass rate — high failure rate detected`, good: false });

  if (s.avg_response_time_ms !== null && s.avg_response_time_ms > 1000)
    insights.push({ text: `Average latency ${fmtMs(s.avg_response_time_ms)} — consider optimising slow endpoints`, good: false });

  if (data.slowest_endpoints[0]?.avg_response_time_ms > 2000)
    insights.push({ text: `"${data.slowest_endpoints[0].name}" is your slowest endpoint at ${fmtMs(data.slowest_endpoints[0].avg_response_time_ms)}`, good: false });

  if (!insights.length) return null;

  return (
    <div className="rounded-xl border bg-card px-5 py-4 space-y-2">
      <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Insights · last {days} days</p>
      <div className="space-y-1.5">
        {insights.map((ins, i) => (
          <div key={i} className="flex items-center gap-2 text-sm">
            {ins.good
              ? <TrendingUp className="h-4 w-4 shrink-0 text-emerald-600" />
              : <TrendingDown className="h-4 w-4 shrink-0 text-red-600" />}
            <span>{ins.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Tooltips ──────────────────────────────────────────────────────────────────

function TrendTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const passed = payload.find((p: any) => p.dataKey === "passed")?.value ?? 0;
  const failed = payload.find((p: any) => p.dataKey === "failed")?.value ?? 0;
  const total  = passed + failed;
  return (
    <div className="rounded-lg border bg-background shadow-lg px-3 py-2.5 text-xs space-y-1.5">
      <p className="font-semibold">{fmtDate(label)}</p>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="capitalize text-muted-foreground">{p.dataKey}:</span>
          <span className="font-medium">{p.value}</span>
        </div>
      ))}
      {total > 0 && <p className="text-muted-foreground border-t pt-1.5">Pass rate: <span className="font-semibold">{pct(passed / total)}</span></p>}
    </div>
  );
}

function RateTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-background shadow-lg px-3 py-2.5 text-xs space-y-1">
      <p className="font-semibold">{fmtDate(label)}</p>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="text-muted-foreground">Pass rate:</span>
          <span className="font-medium">{pct(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

// ── Donut chart ───────────────────────────────────────────────────────────────

function DonutChart({ s }: { s: WorkspaceAnalytics["summary"] }) {
  const slices = [
    { name: "Passed", value: s.passed_runs, color: "#10b981" },
    { name: "Failed", value: s.failed_runs, color: "#ef4444" },
    { name: "Errors", value: s.error_runs,  color: "#f97316" },
  ].filter(d => d.value > 0);

  if (s.total_runs === 0) return (
    <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">No data yet</div>
  );

  return (
    <div className="flex items-center gap-6 py-2">
      <ResponsiveContainer width={150} height={150}>
        <PieChart>
          <Pie data={slices} cx="50%" cy="50%" innerRadius={44} outerRadius={68} dataKey="value" stroke="none">
            {slices.map((e, i) => <Cell key={i} fill={e.color} />)}
          </Pie>
          <Tooltip />
        </PieChart>
      </ResponsiveContainer>
      <div className="space-y-2.5 flex-1">
        {slices.map(d => (
          <div key={d.name} className="flex items-center gap-2 text-sm">
            <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: d.color }} />
            <span className="text-muted-foreground flex-1">{d.name}</span>
            <span className="font-semibold tabular-nums">{d.value}</span>
            <span className="text-xs text-muted-foreground w-9 text-right">{pct(d.value / s.total_runs)}</span>
          </div>
        ))}
        <div className="border-t pt-2 text-xs text-muted-foreground">{s.total_runs} total runs</div>
      </div>
    </div>
  );
}

// ── Method badge ──────────────────────────────────────────────────────────────

const METHOD_COLORS: Record<string, string> = {
  GET: "text-emerald-700 bg-emerald-500/10", POST: "text-blue-700 bg-blue-500/10",
  PUT: "text-amber-700 bg-amber-500/10",     PATCH: "text-purple-700 bg-purple-500/10",
  DELETE: "text-red-700 bg-red-500/10",
};
function MethodBadge({ method }: { method: string }) {
  return <span className={`rounded px-1.5 py-0.5 text-[11px] font-mono font-semibold ${METHOD_COLORS[method] ?? "text-zinc-600 bg-zinc-500/10"}`}>{method}</span>;
}

function LatencyBar({ value, max }: { value: number; max: number }) {
  const w     = max > 0 ? (value / max) * 100 : 0;
  const color = value > 1000 ? "bg-red-500" : value > 500 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${w}%` }} />
      </div>
      <span className="w-14 text-right text-xs tabular-nums text-muted-foreground">{fmtMs(value)}</span>
    </div>
  );
}

function PassRatePill({ rate }: { rate: number }) {
  const cls = rate >= 0.9 ? "bg-emerald-500/15 text-emerald-700" : rate >= 0.7 ? "bg-amber-500/15 text-amber-700" : "bg-red-500/15 text-red-700";
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{pct(rate)}</span>;
}

// ── Endpoints table ───────────────────────────────────────────────────────────

function EndpointsTable({ endpoints }: { endpoints: EndpointStat[] }) {
  const maxAvg = Math.max(...endpoints.map(e => e.avg_response_time_ms), 1);
  if (!endpoints.length) return (
    <div className="flex flex-col items-center justify-center h-32 gap-2 text-muted-foreground">
      <Activity className="h-8 w-8 opacity-30" />
      <p className="text-sm">Run some requests to see latency data</p>
    </div>
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            {["Endpoint","Avg latency","Max","Runs","Pass rate"].map((h,i) => (
              <th key={h} className={`px-4 py-2.5 text-xs font-medium text-muted-foreground ${i===0?"text-left":"text-center"}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {endpoints.map((ep, i) => (
            <tr key={ep.request_id ?? i} className="border-b last:border-0 hover:bg-muted/20 transition-colors">
              <td className="px-4 py-3">
                <div className="flex items-center gap-2"><MethodBadge method={ep.method} /><span className="text-xs font-medium">{ep.name}</span></div>
                <p className="mt-0.5 text-[11px] font-mono text-muted-foreground truncate max-w-[260px]">{ep.url}</p>
              </td>
              <td className="px-4 py-3 w-44"><LatencyBar value={ep.avg_response_time_ms} max={maxAvg} /></td>
              <td className="px-4 py-3 text-center text-xs tabular-nums text-muted-foreground">{fmtMs(ep.max_response_time_ms)}</td>
              <td className="px-4 py-3 text-center text-xs tabular-nums">{ep.total_executions}</td>
              <td className="px-4 py-3 text-center"><PassRatePill rate={ep.pass_rate} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Collections table ─────────────────────────────────────────────────────────

function CollectionsTable({ collections }: { collections: CollectionStat[] }) {
  if (!collections.length) return (
    <div className="flex flex-col items-center justify-center h-32 gap-2 text-muted-foreground">
      <CheckCircle2 className="h-8 w-8 opacity-30" />
      <p className="text-sm">No collection runs yet</p>
    </div>
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            {["Collection","Runs","Pass rate","Avg latency"].map((h,i) => (
              <th key={h} className={`px-4 py-2.5 text-xs font-medium text-muted-foreground ${i===0||i===2?"text-left":"text-center"}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {collections.map(col => (
            <tr key={col.collection_id} className="border-b last:border-0 hover:bg-muted/20 transition-colors">
              <td className="px-4 py-3 font-medium text-sm">{col.collection_name}</td>
              <td className="px-4 py-3 text-center text-xs tabular-nums">{col.total_runs}</td>
              <td className="px-4 py-3">
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                    <div className={`h-full rounded-full ${col.pass_rate>=0.9?"bg-emerald-500":col.pass_rate>=0.7?"bg-amber-500":"bg-red-500"}`}
                      style={{ width: `${col.pass_rate*100}%` }} />
                  </div>
                  <span className="text-xs tabular-nums w-10 text-right">{pct(col.pass_rate)}</span>
                </div>
              </td>
              <td className="px-4 py-3 text-center text-xs tabular-nums text-muted-foreground">{fmtMs(col.avg_response_time_ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Empty & Skeleton ──────────────────────────────────────────────────────────

function EmptyState({ days }: { days: number }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed bg-muted/20 py-16 text-center space-y-3">
      <Activity className="h-12 w-12 text-muted-foreground/30" />
      <div>
        <p className="font-semibold">No data for the last {days} days</p>
        <p className="text-sm text-muted-foreground mt-1">Run some API requests — analytics will appear here.</p>
      </div>
    </div>
  );
}

function PageSkeleton() {
  return (
    <div className="p-6 space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
      </div>
      <Skeleton className="h-14 rounded-xl" />
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="lg:col-span-2 h-72 rounded-xl" />
        <Skeleton className="h-72 rounded-xl" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-56 rounded-xl" />
        <Skeleton className="h-56 rounded-xl" />
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const DAY_OPTIONS = [
  { label: "Last 7 days",  value: "7"  },
  { label: "Last 30 days", value: "30" },
  { label: "Last 90 days", value: "90" },
];

export default function AnalyticsPage() {
  const { id: workspaceId } = useParams<{ id: string }>();
  const { activeWorkspace } = useWorkspaceStore();

  const [days, setDays]         = useState(30);
  const [data, setData]         = useState<WorkspaceAnalytics | null>(null);
  const [loading, setLoading]   = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (silent = false) => {
    if (!workspaceId) return;
    if (!silent) setLoading(true); else setRefreshing(true);
    try {
      const r = await analyticsService.getWorkspaceAnalytics(workspaceId, days);
      setData(r.data);
    } catch { toast.error("Failed to load analytics"); }
    finally { setLoading(false); setRefreshing(false); }
  }, [workspaceId, days]);

  useEffect(() => { load(); }, [load]);

  const s       = data?.summary;
  const hasData = s && s.total_runs > 0;

  return (
    <>
      <Header
        title="Analytics"
        description={activeWorkspace?.name ?? "Workspace analytics"}
        actions={
          <div className="flex items-center gap-2">
            <Select value={String(days)} onValueChange={v => setDays(Number(v))}>
              <SelectTrigger className="h-8 w-36 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {DAY_OPTIONS.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" onClick={() => load(true)} disabled={refreshing}>
              <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        }
      />

      {loading ? <PageSkeleton /> : (
        <div className="flex-1 overflow-auto p-6 space-y-6">

          {/* KPI row */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <KpiCard label="Total runs"       value={s?.total_runs ?? 0}       icon={Activity} />
            <KpiCard label="Success rate"     value={pct(s?.pass_rate ?? 0)}
              accent={(s?.pass_rate??0)>=0.9?"green":(s?.pass_rate??0)>=0.7?"amber":"red"}
              sub={`${s?.passed_runs??0} passed`}                              icon={CheckCircle2} />
            <KpiCard label="Failure rate"
              value={pct(s ? (s.failed_runs+s.error_runs)/Math.max(s.total_runs,1) : 0)}
              accent={(s?.failed_runs??0)+(s?.error_runs??0)>0?"red":undefined}
              sub={`${s?.failed_runs??0} failed · ${s?.error_runs??0} errors`} icon={XCircle} />
            <KpiCard label="Avg latency"      value={fmtMs(s?.avg_response_time_ms??null)}
              accent={(s?.avg_response_time_ms??0)>1000?"amber":undefined}
              sub={`p95: ${fmtMs(s?.p95_response_time_ms??null)}`}             icon={Zap} />
            <KpiCard label="Total executions" value={s?.total_executions??0}
              sub={`${s?.passed_executions??0} passed`}                        icon={Clock} />
          </div>

          {/* Insights */}
          {data && hasData && <InsightBanner data={data} days={days} />}

          {!hasData ? <EmptyState days={days} /> : (
            <>
              {/* Charts row */}
              <div className="grid gap-4 lg:grid-cols-3">

                {/* Trend chart */}
                <div className="lg:col-span-2 rounded-xl border bg-card p-5">
                  <Tabs defaultValue="area">
                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <h2 className="text-sm font-semibold">Run history</h2>
                        <p className="text-xs text-muted-foreground">Daily pass / fail over time</p>
                      </div>
                      <TabsList className="h-7">
                        <TabsTrigger value="area"  className="text-xs px-3">Area</TabsTrigger>
                        <TabsTrigger value="bar"   className="text-xs px-3">Bar</TabsTrigger>
                        <TabsTrigger value="rate"  className="text-xs px-3">Pass %</TabsTrigger>
                      </TabsList>
                    </div>

                    <TabsContent value="area" className="mt-0">
                      <ResponsiveContainer width="100%" height={210}>
                        <AreaChart data={data?.daily_trend} margin={{ top:4, right:4, bottom:0, left:-20 }}>
                          <defs>
                            <linearGradient id="gP" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%"  stopColor="#10b981" stopOpacity={0.3} />
                              <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                            </linearGradient>
                            <linearGradient id="gF" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%"  stopColor="#ef4444" stopOpacity={0.2} />
                              <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                          <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize:11 }} tickLine={false} axisLine={false} />
                          <YAxis allowDecimals={false} tick={{ fontSize:11 }} tickLine={false} axisLine={false} />
                          <Tooltip content={<TrendTooltip />} />
                          <Legend wrapperStyle={{ fontSize:12, paddingTop:8 }}
                            formatter={(v: string) => <span className="capitalize text-muted-foreground">{v}</span>} />
                          <Area type="monotone" dataKey="passed" stroke="#10b981" strokeWidth={2} fill="url(#gP)" />
                          <Area type="monotone" dataKey="failed" stroke="#ef4444" strokeWidth={2} fill="url(#gF)" />
                        </AreaChart>
                      </ResponsiveContainer>
                    </TabsContent>

                    <TabsContent value="bar" className="mt-0">
                      <ResponsiveContainer width="100%" height={210}>
                        <BarChart data={data?.daily_trend} margin={{ top:4, right:4, bottom:0, left:-20 }}>
                          <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                          <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize:11 }} tickLine={false} axisLine={false} />
                          <YAxis allowDecimals={false} tick={{ fontSize:11 }} tickLine={false} axisLine={false} />
                          <Tooltip content={<TrendTooltip />} />
                          <Legend wrapperStyle={{ fontSize:12, paddingTop:8 }}
                            formatter={(v: string) => <span className="capitalize text-muted-foreground">{v}</span>} />
                          <Bar dataKey="passed" stackId="a" fill="#10b981" />
                          <Bar dataKey="failed" stackId="a" fill="#ef4444" radius={[3,3,0,0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </TabsContent>

                    <TabsContent value="rate" className="mt-0">
                      <ResponsiveContainer width="100%" height={210}>
                        <LineChart data={data?.daily_trend} margin={{ top:4, right:4, bottom:0, left:-20 }}>
                          <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                          <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize:11 }} tickLine={false} axisLine={false} />
                          <YAxis domain={[0,1]} tickFormatter={(v: number) => `${Math.round(v*100)}%`}
                            tick={{ fontSize:11 }} tickLine={false} axisLine={false} />
                          <Tooltip content={<RateTooltip />} />
                          <Line type="monotone" dataKey="pass_rate" stroke="#6366f1" strokeWidth={2}
                            dot={{ fill:"#6366f1", r:3 }} activeDot={{ r:5 }} />
                        </LineChart>
                      </ResponsiveContainer>
                    </TabsContent>
                  </Tabs>
                </div>

                {/* Donut */}
                <div className="rounded-xl border bg-card p-5">
                  <h2 className="text-sm font-semibold mb-1">Run breakdown</h2>
                  <p className="text-xs text-muted-foreground mb-4">Pass / fail / error split</p>
                  {s && <DonutChart s={s} />}
                </div>
              </div>

              {/* Tables */}
              <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-xl border bg-card">
                  <div className="border-b px-5 py-3.5">
                    <h2 className="text-sm font-semibold">Slowest endpoints</h2>
                    <p className="text-xs text-muted-foreground">Top 10 by average response time</p>
                  </div>
                  <EndpointsTable endpoints={data?.slowest_endpoints ?? []} />
                </div>
                <div className="rounded-xl border bg-card">
                  <div className="border-b px-5 py-3.5">
                    <h2 className="text-sm font-semibold">Collection reliability</h2>
                    <p className="text-xs text-muted-foreground">Pass rate per collection</p>
                  </div>
                  <CollectionsTable collections={data?.collection_stats ?? []} />
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
}
