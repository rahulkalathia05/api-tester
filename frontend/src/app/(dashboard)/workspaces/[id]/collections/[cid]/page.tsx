"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import {
  Plus, Play, Trash2, CheckCircle2, XCircle,
  AlertCircle, Loader2, PlaySquare,
} from "lucide-react";
import { toast } from "sonner";
import { collectionService } from "@/lib/services/collection.service";
import { runnerService } from "@/lib/services/runner.service";
import { HeadersEditor, type HeaderRow, headersToRows, rowsToHeaders, newHeaderId } from "@/components/collections/HeadersEditor";
import { AuthEditor, type AuthConfig, authConfigToApiPayload, apiPayloadToAuthConfig } from "@/components/collections/AuthEditor";
import { ResponseHeadersViewer } from "@/components/results/ResponseHeadersViewer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { ApiRequest, Assertion, AssertionResult, TestResult } from "@/types";

// ── Constants ─────────────────────────────────────────────────────────────────

const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;
type Method = typeof METHODS[number];

const METHOD_COLORS: Record<string, string> = {
  GET:    "text-emerald-600 bg-emerald-500/10",
  POST:   "text-blue-600 bg-blue-500/10",
  PUT:    "text-amber-600 bg-amber-500/10",
  PATCH:  "text-purple-600 bg-purple-500/10",
  DELETE: "text-red-600 bg-red-500/10",
};

const ASSERTION_TYPES = ["status_code", "response_time", "body_contains", "json_path", "header"] as const;
const ASSERTION_OPERATORS = ["eq", "ne", "lt", "gt", "lte", "gte", "contains", "not_contains", "exists", "matches"] as const;

// ── Helpers ───────────────────────────────────────────────────────────────────

function MethodBadge({ method }: { method: string }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[11px] font-mono font-semibold ${METHOD_COLORS[method] ?? "text-zinc-600 bg-zinc-100"}`}>
      {method}
    </span>
  );
}

function getAuthToken(): string {
  try {
    const raw = localStorage.getItem("api-tester-auth");
    if (!raw) return "";
    return JSON.parse(raw)?.state?.accessToken ?? "";
  } catch { return ""; }
}

/** Strip accidental "METHOD + " prefix if user typed "GET + https://..." */
function cleanUrl(raw: string): string {
  return raw
    .replace(/^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*\+\s*/i, "")
    .trim();
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function CollectionPage() {
  const { cid: collectionId } = useParams<{ id: string; cid: string }>();
  const { activeEnvironment } = useWorkspaceStore();

  const [collectionName, setCollectionName] = useState("");
  const [requests, setRequests] = useState<ApiRequest[]>([]);
  const [loadingList, setLoadingList] = useState(true);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [assertions, setAssertions] = useState<Assertion[]>([]);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const [form, setForm] = useState({ name: "", method: "GET" as Method, url: "", body: "" });
  const [headerRows, setHeaderRows] = useState<HeaderRow[]>([]);
  const [authConfig, setAuthConfig] = useState<AuthConfig>({ type: "none" });
  const [savingForm, setSavingForm] = useState(false);

  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState({ name: "", method: "GET" as Method, url: "" });
  const [adding, setAdding] = useState(false);

  const [newAssertion, setNewAssertion] = useState({
    type: "status_code", operator: "eq", expected_value: "200", path: "",
  });

  const [activeTab, setActiveTab] = useState<"body" | "headers" | "auth" | "assertions" | "response">("body");
  const [runResult, setRunResult] = useState<TestResult | null>(null);
  const [running, setRunning] = useState(false);

  const [colRunning, setColRunning] = useState(false);
  const [colResults, setColResults] = useState<TestResult[]>([]);
  const [showColResults, setShowColResults] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Request search + method filter ─────────────────────────────────────
  const [requestSearch, setRequestSearch] = useState("");
  const [methodFilter, setMethodFilter] = useState<string[]>([]);

  const filteredRequests = requests.filter(r => {
    const matchSearch = !requestSearch || r.name.toLowerCase().includes(requestSearch.toLowerCase()) || r.url.toLowerCase().includes(requestSearch.toLowerCase());
    const matchMethod = methodFilter.length === 0 || methodFilter.includes(r.method);
    return matchSearch && matchMethod;
  });

  // ── Load collection ──────────────────────────────────────────────────────

  const loadCollection = useCallback(async () => {
    setLoadingList(true);
    try {
      const { data } = await collectionService.getWithRequests(collectionId);
      const d = data as any;
      setCollectionName(d.name ?? "Collection");
      const reqs: ApiRequest[] = d.requests ?? [];
      setRequests(reqs);
      if (reqs.length > 0) setSelectedId(prev => prev ?? reqs[0].id);
    } catch {
      toast.error("Failed to load collection");
    } finally {
      setLoadingList(false);
    }
  }, [collectionId]);

  useEffect(() => { loadCollection(); }, [loadCollection]);

  // ── Load request detail when selection changes ───────────────────────────

  useEffect(() => {
    if (!selectedId) return;
    setLoadingDetail(true);
    setRunResult(null);
    setAssertions([]);
    setHeaderRows([]);
    setAuthConfig({ type: "none" });

    const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
    fetch(`${apiBase}/requests/${selectedId}`, {
      headers: { Authorization: `Bearer ${getAuthToken()}` },
    })
      .then(r => r.json())
      .then(data => {
        setForm({
          name: data.name ?? "",
          method: (data.method ?? "GET") as Method,
          url: data.url ?? "",
          body: data.body ?? "",
        });
        setAssertions(data.assertions ?? []);
        setHeaderRows(headersToRows(data.headers ?? {}));
        setAuthConfig(apiPayloadToAuthConfig(data.auth_type ?? "none", data.auth_config ?? {}));
      })
      .catch(() => toast.error("Failed to load request"))
      .finally(() => setLoadingDetail(false));
  }, [selectedId]);

  // ── Add request ──────────────────────────────────────────────────────────

  const handleAddRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addForm.url.trim()) { toast.error("URL is required"); return; }
    setAdding(true);
    try {
      const { data } = await collectionService.createRequest(collectionId, {
        name: addForm.name.trim() || `${addForm.method} request`,
        method: addForm.method,
        url: addForm.url.trim(),
      });
      const req = data as ApiRequest;
      setRequests(prev => [...prev, req]);
      setSelectedId(req.id);
      setAddOpen(false);
      setAddForm({ name: "", method: "GET", url: "" });
      toast.success("Request added");
    } catch {
      toast.error("Failed to add request");
    } finally {
      setAdding(false);
    }
  };

  // ── Save request ─────────────────────────────────────────────────────────

  const handleSave = async () => {
    if (!selectedId) return;
    const cleanedUrl = cleanUrl(form.url);
    if (cleanedUrl !== form.url) setForm(f => ({ ...f, url: cleanedUrl }));
    setSavingForm(true);
    try {
      await collectionService.updateRequest(selectedId, {
        name: form.name,
        method: form.method as any,
        url: cleanedUrl,
        headers: rowsToHeaders(headerRows),
        body: form.body || null,
        body_type: form.body ? "json" : "none",
        ...authConfigToApiPayload(authConfig),
      } as any);
      setRequests(prev => prev.map(r => r.id === selectedId ? { ...r, ...form } : r));
      toast.success("Saved");
    } catch {
      toast.error("Failed to save");
    } finally {
      setSavingForm(false);
    }
  };

  // ── Delete request ───────────────────────────────────────────────────────

  const handleDeleteRequest = async (reqId: string) => {
    if (!confirm("Delete this request?")) return;
    try {
      await collectionService.deleteRequest(reqId);
      const remaining = requests.filter(r => r.id !== reqId);
      setRequests(remaining);
      if (selectedId === reqId) {
        setSelectedId(remaining[0]?.id ?? null);
        setAssertions([]);
        setRunResult(null);
      }
      toast.success("Deleted");
    } catch {
      toast.error("Failed to delete");
    }
  };

  // ── Assertions ───────────────────────────────────────────────────────────

  const handleAddAssertion = async () => {
    if (!selectedId) return;
    try {
      const { data } = await collectionService.createAssertion(selectedId, {
        type: newAssertion.type as any,
        operator: newAssertion.operator as any,
        expected_value: newAssertion.expected_value,
        path: newAssertion.path || null,
      });
      setAssertions(prev => [...prev, data as Assertion]);
      setNewAssertion({ type: "status_code", operator: "eq", expected_value: "200", path: "" });
      toast.success("Assertion added");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Failed to add assertion");
    }
  };

  const handleDeleteAssertion = async (assertionId: string) => {
    try {
      await collectionService.deleteAssertion(assertionId);
      setAssertions(prev => prev.filter(a => a.id !== assertionId));
    } catch {
      toast.error("Failed to delete");
    }
  };

  // ── Run single ───────────────────────────────────────────────────────────

  const handleRun = async () => {
    if (!selectedId) return;
    // Clean URL before saving so "GET + https://..." doesn't reach the backend
    setForm(f => ({ ...f, url: cleanUrl(f.url) }));
    await handleSave();
    setRunning(true);
    setRunResult(null);
    setActiveTab("response");
    try {
      const { data } = await runnerService.runSingle(selectedId, activeEnvironment?.id);
      setRunResult(data);
    } catch {
      toast.error("Run failed");
    } finally {
      setRunning(false);
    }
  };

  // ── Run collection ───────────────────────────────────────────────────────

  const handleRunCollection = async () => {
    setColRunning(true);
    setColResults([]);
    setShowColResults(true);
    try {
      const { data: run } = await runnerService.runCollection(collectionId, activeEnvironment?.id);
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const { data: detail } = await runnerService.getRun(run.id);
          if (!["pending", "running"].includes(detail.status)) {
            clearInterval(pollRef.current!);
            setColResults(detail.results ?? []);
            setColRunning(false);
            toast[detail.status === "passed" ? "success" : "error"](
              `${detail.passed}/${detail.total} requests passed`
            );
          }
        } catch { clearInterval(pollRef.current!); setColRunning(false); }
      }, 2000);
    } catch {
      toast.error("Failed to start run");
      setColRunning(false);
    }
  };

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full overflow-hidden">

      {/* ── Left sidebar: request list ─────────────────────────────────────── */}
      <aside className="flex w-56 shrink-0 flex-col border-r bg-muted/20">
        {/* Header */}
        <div className="flex items-center justify-between border-b px-3 py-2">
          <span className="truncate text-sm font-semibold">{collectionName}</span>
          <button
            className="flex h-6 w-6 items-center justify-center rounded hover:bg-muted transition-colors"
            onClick={() => setAddOpen(o => !o)}
            title="Add request"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Search + method filter */}
        <div className="border-b px-2 py-2 space-y-1.5">
          <div className="relative">
            <span className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground">
              <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
            </span>
            <Input
              className="h-7 pl-6 text-xs"
              placeholder="Filter requests…"
              value={requestSearch}
              onChange={e => setRequestSearch(e.target.value)}
            />
            {requestSearch && (
              <button className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setRequestSearch("")}>
                <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            )}
          </div>
          {/* Method chips */}
          <div className="flex flex-wrap gap-1">
            {(["GET","POST","PUT","PATCH","DELETE"] as const).map(m => {
              const active = methodFilter.includes(m);
              const cls = { GET:"text-emerald-700 bg-emerald-500/10", POST:"text-blue-700 bg-blue-500/10", PUT:"text-amber-700 bg-amber-500/10", PATCH:"text-purple-700 bg-purple-500/10", DELETE:"text-red-700 bg-red-500/10" }[m];
              return (
                <button key={m} type="button"
                  className={`rounded px-1.5 py-0.5 text-[10px] font-mono font-semibold transition-all ${active ? cls + " shadow-sm scale-105" : "text-muted-foreground bg-muted/40 hover:bg-muted"}`}
                  onClick={() => setMethodFilter(f => f.includes(m) ? f.filter(x => x !== m) : [...f, m])}>
                  {m}
                </button>
              );
            })}
          </div>
        </div>

        {/* Add request form */}
        {addOpen && (
          <form onSubmit={handleAddRequest} className="border-b bg-background p-2.5 space-y-1.5 text-xs">
            <select
              className="w-full rounded border bg-background px-2 py-1 text-xs font-mono"
              value={addForm.method}
              onChange={e => setAddForm(f => ({ ...f, method: e.target.value as Method }))}
            >
              {METHODS.map(m => <option key={m}>{m}</option>)}
            </select>
            <Input
              className="h-7 text-xs"
              placeholder="https://api.example.com/..."
              value={addForm.url}
              onChange={e => setAddForm(f => ({ ...f, url: e.target.value }))}
              autoFocus
            />
            <Input
              className="h-7 text-xs"
              placeholder="Name (optional)"
              value={addForm.name}
              onChange={e => setAddForm(f => ({ ...f, name: e.target.value }))}
            />
            <div className="flex gap-1">
              <Button type="submit" size="sm" className="h-6 flex-1 text-xs" disabled={adding}>
                {adding ? "Adding…" : "Add"}
              </Button>
              <Button type="button" variant="outline" size="sm" className="h-6 text-xs"
                onClick={() => setAddOpen(false)}>Cancel</Button>
            </div>
          </form>
        )}

        {/* List */}
        <div className="flex-1 overflow-auto py-1">
          {loadingList
            ? [...Array(3)].map((_, i) => <Skeleton key={i} className="mx-2 my-1 h-9 rounded" />)
            : filteredRequests.length === 0 && requests.length > 0
              ? <p className="px-3 py-4 text-center text-xs text-muted-foreground">No requests match the filter.</p>
              : requests.length === 0
                ? <p className="px-3 py-6 text-center text-xs text-muted-foreground">No requests.<br />Click + to add.</p>
                : filteredRequests.map(req => (
                <div
                  key={req.id}
                  className={`group flex cursor-pointer items-center gap-1.5 px-2 py-2 transition-colors hover:bg-muted/50 ${selectedId === req.id ? "bg-secondary" : ""}`}
                  onClick={() => setSelectedId(req.id)}
                >
                  <MethodBadge method={req.method} />
                  <span className="min-w-0 flex-1 truncate text-xs">{req.name}</span>
                  <button
                    className="hidden shrink-0 group-hover:block text-muted-foreground hover:text-red-600"
                    onClick={e => { e.stopPropagation(); handleDeleteRequest(req.id); }}
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))
          }
        </div>

        <Separator />
        <div className="p-2">
          <Button
            variant="outline" size="sm"
            className="w-full gap-1.5 text-xs"
            onClick={handleRunCollection}
            disabled={colRunning || requests.length === 0}
          >
            {colRunning
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <PlaySquare className="h-3.5 w-3.5" />}
            {colRunning ? "Running…" : "Run all"}
          </Button>
        </div>
      </aside>

      {/* ── Main editor area ────────────────────────────────────────────────── */}
      <div className="flex flex-1 flex-col overflow-hidden">

        {!selectedId ? (
          <div className="flex flex-1 items-center justify-center text-muted-foreground">
            <p className="text-sm">Select or add a request →</p>
          </div>
        ) : loadingDetail ? (
          <div className="p-4 space-y-2">
            <Skeleton className="h-7 w-full" />
            <Skeleton className="h-9 w-full" />
          </div>
        ) : (
          <>
            {/* URL bar */}
            <div className="border-b p-3 space-y-2">
              <Input
                className="h-7 text-sm font-medium"
                placeholder="Request name"
                value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              />
              <div className="flex gap-2">
                <select
                  className="rounded-md border bg-background px-2 py-1 text-xs font-mono font-bold"
                  value={form.method}
                  onChange={e => setForm(f => ({ ...f, method: e.target.value as Method }))}
                >
                  {METHODS.map(m => <option key={m}>{m}</option>)}
                </select>
                <Input
                  className="h-8 flex-1 font-mono text-xs"
                  placeholder="https://api.example.com/endpoint"
                  value={form.url}
                  onChange={e => setForm(f => ({ ...f, url: e.target.value }))}
                  onKeyDown={e => e.key === "Enter" && handleRun()}
                />
                <Button className="h-8 gap-1.5 px-4" onClick={handleRun} disabled={running}>
                  {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                  {running ? "Running…" : "Run"}
                </Button>
                <Button variant="outline" className="h-8" onClick={handleSave} disabled={savingForm}>
                  {savingForm ? "Saving…" : "Save"}
                </Button>
              </div>
            </div>

            {/* Tabs */}
            <div className="flex border-b text-xs">
              {(["body", "headers", "auth", "assertions", "response"] as const).map(tab => (
                <button
                  key={tab}
                  className={`px-4 py-2.5 capitalize transition-colors ${activeTab === tab ? "border-b-2 border-primary font-semibold" : "text-muted-foreground hover:text-foreground"}`}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab}
                  {tab === "auth" && authConfig.type !== "none" && (
                    <span className="ml-1.5 rounded-full bg-blue-500/15 text-blue-600 px-1.5 text-[10px] capitalize">{authConfig.type.replace("_", " ")}</span>
                  )}
                  {tab === "headers" && Object.keys(rowsToHeaders(headerRows)).length > 0 && (
                    <span className="ml-1.5 rounded-full bg-muted px-1.5 text-[10px]">{Object.keys(rowsToHeaders(headerRows)).length}</span>
                  )}
                  {tab === "assertions" && assertions.length > 0 && (
                    <span className="ml-1.5 rounded-full bg-muted px-1.5 text-[10px]">{assertions.length}</span>
                  )}
                  {tab === "response" && runResult && (
                    <span className={`ml-1.5 rounded-full px-1.5 text-[10px] ${runResult.status === "passed" ? "bg-emerald-500/15 text-emerald-700" : "bg-red-500/15 text-red-700"}`}>
                      {runResult.response_status ?? runResult.status}
                    </span>
                  )}
                </button>
              ))}
            </div>

            <div className="flex-1 overflow-auto">

              {/* Body */}
              {activeTab === "body" && (
                <div className="p-4">
                  <p className="mb-2 text-xs text-muted-foreground">Request body (JSON)</p>
                  <textarea
                    className="w-full rounded-md border bg-zinc-950 p-3 font-mono text-xs text-zinc-100 focus:outline-none resize-none"
                    rows={14}
                    placeholder='{"key": "value"}'
                    value={form.body}
                    onChange={e => setForm(f => ({ ...f, body: e.target.value }))}
                  />
                </div>
              )}

              {/* Headers */}
              {activeTab === "headers" && (
                <div className="p-4">
                  <HeadersEditor rows={headerRows} onChange={setHeaderRows} />
                </div>
              )}

              {/* Auth */}
              {activeTab === "auth" && (
                <div className="p-4">
                  <AuthEditor config={authConfig} onChange={setAuthConfig} />
                </div>
              )}

              {/* Assertions */}
              {activeTab === "assertions" && (
                <div className="p-4 space-y-4">
                  {assertions.length === 0
                    ? <p className="text-xs text-muted-foreground">No assertions. Add one below.</p>
                    : assertions.map(a => (
                      <div key={a.id} className="flex items-center gap-2 rounded-lg border bg-muted/20 px-3 py-2 text-xs">
                        <span className="w-28 shrink-0 font-mono text-blue-600">{a.type}</span>
                        <span className="w-20 shrink-0 text-muted-foreground">{a.operator}</span>
                        <span className="flex-1 font-semibold">{a.expected_value}</span>
                        {a.path && <span className="text-[11px] text-muted-foreground">{a.path}</span>}
                        <button onClick={() => handleDeleteAssertion(a.id)}
                          className="text-muted-foreground hover:text-red-600">
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    ))
                  }

                  {/* Add assertion */}
                  <div className="rounded-lg border bg-card p-3 space-y-2">
                    <p className="text-xs font-medium text-muted-foreground">Add assertion</p>
                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <p className="mb-1 text-[10px] text-muted-foreground">Type</p>
                        <select className="w-full rounded border bg-background px-2 py-1 text-xs"
                          value={newAssertion.type}
                          onChange={e => setNewAssertion(a => ({ ...a, type: e.target.value }))}>
                          {ASSERTION_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                        </select>
                      </div>
                      <div>
                        <p className="mb-1 text-[10px] text-muted-foreground">Operator</p>
                        <select className="w-full rounded border bg-background px-2 py-1 text-xs"
                          value={newAssertion.operator}
                          onChange={e => setNewAssertion(a => ({ ...a, operator: e.target.value }))}>
                          {ASSERTION_OPERATORS.map(o => <option key={o} value={o}>{o}</option>)}
                        </select>
                      </div>
                      <div>
                        <p className="mb-1 text-[10px] text-muted-foreground">Expected</p>
                        <Input className="h-7 text-xs"
                          value={newAssertion.expected_value}
                          onChange={e => setNewAssertion(a => ({ ...a, expected_value: e.target.value }))}
                          placeholder="200" />
                      </div>
                    </div>
                    {newAssertion.type === "json_path" && (
                      <Input className="h-7 text-xs font-mono"
                        value={newAssertion.path}
                        onChange={e => setNewAssertion(a => ({ ...a, path: e.target.value }))}
                        placeholder="$.data.id (JSONPath)" />
                    )}
                    <Button size="sm" className="h-7 gap-1 text-xs" onClick={handleAddAssertion}>
                      <Plus className="h-3 w-3" /> Add assertion
                    </Button>
                  </div>
                </div>
              )}

              {/* Response */}
              {activeTab === "response" && (
                <div className="p-4 space-y-4">
                  {!runResult && !running && (
                    <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
                      Click <Play className="mx-1.5 h-4 w-4" /> Run to execute this request
                    </div>
                  )}
                  {running && (
                    <div className="flex h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="h-5 w-5 animate-spin" /> Sending request…
                    </div>
                  )}
                  {runResult && !running && (
                    <div className="space-y-4">
                      {/* Summary */}
                      <div className="flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3">
                        <span className={`rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${
                          runResult.status === "passed" ? "bg-emerald-500/15 text-emerald-700 border-emerald-200"
                          : "bg-red-500/15 text-red-700 border-red-200"}`}>
                          {runResult.status}
                        </span>
                        {runResult.response_status != null && (
                          <span className={`text-lg font-bold tabular-nums ${runResult.response_status < 400 ? "text-emerald-600" : "text-red-600"}`}>
                            {runResult.response_status}
                          </span>
                        )}
                        {runResult.response_time_ms != null && (
                          <span className="text-sm text-muted-foreground">{runResult.response_time_ms} ms</span>
                        )}
                        {runResult.error_message && (
                          <span className="text-xs text-red-600">{runResult.error_message}</span>
                        )}
                        {runResult.assertion_results.length > 0 && (
                          <span className="ml-auto text-xs text-muted-foreground">
                            {runResult.assertion_results.filter(a => a.passed).length}/{runResult.assertion_results.length} assertions passed
                          </span>
                        )}
                      </div>

                      {/* Assertion results */}
                      {runResult.assertion_results.length > 0 && (
                        <div className="space-y-1.5">
                          <p className="text-xs font-semibold">Assertions</p>
                          {runResult.assertion_results.map((ar: AssertionResult) => (
                            <div key={ar.id}
                              className={`flex items-start gap-2 rounded-md border px-3 py-2 text-xs ${ar.passed ? "border-emerald-200 bg-emerald-500/8" : "border-red-200 bg-red-500/8"}`}>
                              {ar.passed
                                ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                                : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" />}
                              <div>
                                <span className="font-mono text-muted-foreground">{ar.assertion_snapshot?.type}</span>
                                {" "}<span>{ar.assertion_snapshot?.operator}</span>
                                {" "}<span className="font-semibold">{ar.assertion_snapshot?.expected_value}</span>
                                {ar.actual_value != null && (
                                  <span className="block text-muted-foreground">
                                    actual: <span className="font-semibold text-foreground">{ar.actual_value}</span>
                                  </span>
                                )}
                                {ar.error_message && <span className="block text-red-600">{ar.error_message}</span>}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Response headers */}
                      {Object.keys(runResult.response_headers).length > 0 && (
                        <div>
                          <p className="mb-1.5 text-xs font-semibold">Response headers</p>
                          <ResponseHeadersViewer headers={runResult.response_headers} maxHeight={200} />
                        </div>
                      )}

                      {/* Body */}
                      {runResult.response_body && (
                        <div>
                          <p className="mb-1.5 text-xs font-semibold">Response body</p>
                          <pre className="max-h-80 overflow-auto rounded-md bg-zinc-950 p-3 text-xs text-zinc-100 whitespace-pre-wrap break-all">
                            {(() => {
                              try { return JSON.stringify(JSON.parse(runResult.response_body!), null, 2); }
                              catch { return runResult.response_body; }
                            })()}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        )}

        {/* Collection run results banner */}
        {showColResults && (
          <div className="border-t bg-background">
            <div className="flex items-center justify-between border-b px-4 py-2 text-sm">
              <div className="flex items-center gap-2 font-medium">
                {colRunning
                  ? <><Loader2 className="h-4 w-4 animate-spin text-blue-500" /> Running all requests…</>
                  : <>
                    <PlaySquare className="h-4 w-4" />
                    {colResults.filter(r => r.status === "passed").length}/{colResults.length} passed
                  </>}
              </div>
              <button className="text-xs text-muted-foreground hover:text-foreground"
                onClick={() => setShowColResults(false)}>✕</button>
            </div>
            <div className="max-h-44 overflow-auto divide-y text-xs">
              {colRunning && colResults.length === 0 && (
                <p className="px-4 py-3 text-muted-foreground">Waiting for results…</p>
              )}
              {colResults.map((r, i) => (
                <div key={r.id ?? i} className="flex items-center gap-3 px-4 py-2">
                  {r.status === "passed"
                    ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                    : r.status === "error"
                      ? <AlertCircle className="h-3.5 w-3.5 shrink-0 text-orange-500" />
                      : <XCircle className="h-3.5 w-3.5 shrink-0 text-red-500" />}
                  <span className="font-medium">{(r.request_snapshot as any)?.name ?? `Request ${i + 1}`}</span>
                  <MethodBadge method={(r.request_snapshot as any)?.method ?? "GET"} />
                  {r.response_status != null && (
                    <span className={`font-mono font-semibold ${r.response_status < 400 ? "text-emerald-600" : "text-red-600"}`}>
                      {r.response_status}
                    </span>
                  )}
                  {r.response_time_ms != null && (
                    <span className="ml-auto text-muted-foreground">{r.response_time_ms}ms</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
