"use client";

import { useEffect, useState } from "react";
import {
  Plus, Play, Pause, Trash2, Clock, CheckCircle2, XCircle,
  Loader2, ChevronDown, History, CalendarClock,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import api from "@/lib/api";
import { environmentService } from "@/lib/services/environment.service";
import type { Environment } from "@/types";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SchedulePreset {
  label: string;
  cron: string;
  description: string;
}

interface ScheduleOut {
  id: string;
  collection_id: string;
  environment_id: string | null;
  cron_expression: string;
  cron_description: string;
  is_active: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
}

interface HistoryItem {
  run_id: string;
  status: string;
  total: number;
  passed: number;
  failed: number;
  started_at: string | null;
  duration_ms: number | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ── History drawer ────────────────────────────────────────────────────────────

function HistoryDrawer({ scheduleId, onClose }: { scheduleId: string; onClose: () => void }) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<HistoryItem[]>(`/schedules/${scheduleId}/history?limit=20`)
      .then(r => setItems(r.data))
      .catch(() => toast.error("Failed to load history"))
      .finally(() => setLoading(false));
  }, [scheduleId]);

  return (
    <div className="mt-3 rounded-lg border bg-muted/10">
      <div className="flex items-center justify-between px-3 py-2 border-b">
        <span className="text-xs font-semibold flex items-center gap-1.5">
          <History className="h-3.5 w-3.5" /> Recent runs
        </span>
        <button className="text-xs text-muted-foreground hover:text-foreground" onClick={onClose}>
          Hide
        </button>
      </div>
      {loading ? (
        <div className="flex justify-center py-4">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
      ) : items.length === 0 ? (
        <p className="py-4 text-center text-xs text-muted-foreground">No runs yet</p>
      ) : (
        <div className="divide-y">
          {items.map(item => (
            <div key={item.run_id} className="flex items-center gap-3 px-3 py-2 text-xs">
              {item.status === "passed"
                ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                : <XCircle className="h-3.5 w-3.5 shrink-0 text-red-500" />}
              <span className={`capitalize font-medium ${item.status === "passed" ? "text-emerald-600" : "text-red-600"}`}>
                {item.status}
              </span>
              <span className="text-muted-foreground">
                {item.passed}/{item.total} passed
              </span>
              {item.duration_ms != null && (
                <span className="text-muted-foreground">{fmtDuration(item.duration_ms)}</span>
              )}
              <span className="ml-auto text-muted-foreground tabular-nums">
                {fmtDate(item.started_at)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Single schedule row ───────────────────────────────────────────────────────

function ScheduleRow({
  schedule, environments, onToggle, onDelete,
}: {
  schedule: ScheduleOut;
  environments: Environment[];
  onToggle: (id: string, active: boolean) => void;
  onDelete: (id: string) => void;
}) {
  const [toggling, setToggling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const envName = environments.find(e => e.id === schedule.environment_id)?.name;

  const handleToggle = async () => {
    setToggling(true);
    try {
      const action = schedule.is_active ? "deactivate" : "activate";
      await api.post(`/schedules/${schedule.id}/${action}`);
      onToggle(schedule.id, !schedule.is_active);
      toast.success(schedule.is_active ? "Schedule paused" : "Schedule activated");
    } catch {
      toast.error("Failed to update schedule");
    } finally {
      setToggling(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm("Delete this schedule?")) return;
    setDeleting(true);
    try {
      await api.delete(`/schedules/${schedule.id}`);
      onDelete(schedule.id);
      toast.success("Schedule deleted");
    } catch {
      toast.error("Failed to delete schedule");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className={`rounded-lg border p-3 space-y-2 transition-colors ${schedule.is_active ? "border-emerald-200 bg-emerald-500/5" : "bg-muted/20"}`}>
      {/* Top row */}
      <div className="flex items-start gap-2">
        <div className="mt-0.5">
          {schedule.is_active
            ? <CheckCircle2 className="h-4 w-4 text-emerald-500" />
            : <Pause className="h-4 w-4 text-muted-foreground" />}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <code className="text-xs font-mono bg-muted px-1.5 py-0.5 rounded">
              {schedule.cron_expression}
            </code>
            <span className="text-xs text-muted-foreground">{schedule.cron_description}</span>
            {envName && (
              <span className="text-[10px] rounded border px-1.5 py-0.5 bg-background text-muted-foreground">
                env: {envName}
              </span>
            )}
          </div>

          <div className="mt-1.5 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Next: <span className="font-medium text-foreground">{fmtDate(schedule.next_run_at)}</span>
            </span>
            {schedule.last_run_at && (
              <span>Last: {fmtDate(schedule.last_run_at)}</span>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0">
          <button
            className="rounded p-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            title="Run history"
            onClick={() => setShowHistory(h => !h)}
          >
            <History className="h-3.5 w-3.5" />
          </button>
          <button
            className={`rounded p-1.5 text-xs transition-colors ${
              schedule.is_active
                ? "text-amber-600 hover:bg-amber-500/10"
                : "text-emerald-600 hover:bg-emerald-500/10"
            }`}
            title={schedule.is_active ? "Pause" : "Activate"}
            onClick={handleToggle}
            disabled={toggling}
          >
            {toggling
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : schedule.is_active
                ? <Pause className="h-3.5 w-3.5" />
                : <Play className="h-3.5 w-3.5" />}
          </button>
          <button
            className="rounded p-1.5 text-xs text-red-500 hover:bg-red-500/10 transition-colors"
            title="Delete schedule"
            onClick={handleDelete}
            disabled={deleting}
          >
            {deleting
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <Trash2 className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      {showHistory && (
        <HistoryDrawer scheduleId={schedule.id} onClose={() => setShowHistory(false)} />
      )}
    </div>
  );
}

// ── Create form ───────────────────────────────────────────────────────────────

function CreateForm({
  collectionId, workspaceId,
  presets, environments,
  onCreate,
}: {
  collectionId: string;
  workspaceId: string;
  presets: SchedulePreset[];
  environments: Environment[];
  onCreate: (s: ScheduleOut) => void;
}) {
  const [cron, setCron] = useState("0 9 * * *");
  const [envId, setEnvId] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [description, setDescription] = useState("Every day at 09:00 UTC");

  const applyPreset = (p: SchedulePreset) => {
    setCron(p.cron);
    setDescription(p.description);
  };

  const handleCreate = async () => {
    setSaving(true);
    try {
      const { data } = await api.post<ScheduleOut>(
        `/collections/${collectionId}/schedules`,
        {
          cron_expression: cron,
          environment_id: envId || null,
          is_active: true,
        },
      );
      onCreate(data);
      setCron("0 9 * * *");
      setEnvId("");
      toast.success("Schedule created");
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Invalid cron expression");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
        New schedule
      </p>

      {/* Preset pills */}
      <div className="flex flex-wrap gap-1.5">
        {presets.map(p => (
          <button
            key={p.cron}
            className={`rounded-full border px-2.5 py-0.5 text-xs transition-all hover:border-primary/50 ${
              cron === p.cron
                ? "border-primary bg-primary/10 text-primary font-medium"
                : "border-muted-foreground/20 text-muted-foreground"
            }`}
            onClick={() => applyPreset(p)}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Cron input */}
      <div className="space-y-1">
        <label className="text-[11px] text-muted-foreground font-medium">Cron expression</label>
        <Input
          className="h-8 font-mono text-xs"
          value={cron}
          onChange={e => { setCron(e.target.value); setDescription(""); }}
          placeholder="0 9 * * *"
        />
        {description && (
          <p className="text-[11px] text-muted-foreground flex items-center gap-1">
            <Clock className="h-3 w-3" /> {description}
          </p>
        )}
      </div>

      {/* Environment selector */}
      {environments.length > 0 && (
        <div className="space-y-1">
          <label className="text-[11px] text-muted-foreground font-medium">
            Environment <span className="font-normal">(optional)</span>
          </label>
          <select
            className="h-8 w-full rounded-md border bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            value={envId}
            onChange={e => setEnvId(e.target.value)}
          >
            <option value="">No environment</option>
            {environments.map(e => (
              <option key={e.id} value={e.id}>{e.name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Cron reference */}
      <div className="rounded-md bg-muted/40 px-3 py-2 text-[10px] text-muted-foreground font-mono space-y-0.5">
        <p className="font-semibold text-foreground text-[11px] mb-1">Cron format: minute hour day month weekday</p>
        <p>0 9 * * *    → Daily at 9:00 AM UTC</p>
        <p>0 */6 * * *  → Every 6 hours</p>
        <p>0 9 * * 1    → Every Monday at 9 AM</p>
        <p>*/15 * * * * → Every 15 minutes</p>
      </div>

      <Button className="w-full h-8 text-xs gap-1.5" onClick={handleCreate} disabled={saving || !cron.trim()}>
        {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
        Create schedule
      </Button>
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

interface SchedulesTabProps {
  collectionId: string;
  workspaceId: string;
}

export function SchedulesTab({ collectionId, workspaceId }: SchedulesTabProps) {
  const [schedules, setSchedules] = useState<ScheduleOut[]>([]);
  const [presets, setPresets] = useState<SchedulePreset[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  useEffect(() => {
    Promise.all([
      api.get<ScheduleOut[]>(`/collections/${collectionId}/schedules`),
      api.get<SchedulePreset[]>("/schedules/presets"),
      environmentService.list(workspaceId),
    ])
      .then(([s, p, e]) => {
        setSchedules(s.data);
        setPresets(p.data);
        setEnvironments(e.data);
        if (s.data.length === 0) setShowForm(true);
      })
      .catch(() => toast.error("Failed to load schedules"))
      .finally(() => setLoading(false));
  }, [collectionId, workspaceId]);

  const handleCreate = (s: ScheduleOut) => {
    setSchedules(prev => [s, ...prev]);
    setShowForm(false);
  };

  const handleToggle = (id: string, active: boolean) => {
    setSchedules(prev => prev.map(s => s.id === id ? { ...s, is_active: active } : s));
  };

  const handleDelete = (id: string) => {
    setSchedules(prev => prev.filter(s => s.id !== id));
  };

  if (loading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CalendarClock className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">Scheduled runs</span>
          {schedules.length > 0 && (
            <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold">
              {schedules.length}
            </span>
          )}
        </div>
        <button
          className="flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs font-medium hover:bg-muted transition-colors"
          onClick={() => setShowForm(f => !f)}
        >
          <Plus className="h-3.5 w-3.5" />
          New schedule
          <ChevronDown className={`h-3 w-3 transition-transform ${showForm ? "rotate-180" : ""}`} />
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <CreateForm
          collectionId={collectionId}
          workspaceId={workspaceId}
          presets={presets}
          environments={environments}
          onCreate={handleCreate}
        />
      )}

      {/* Schedule list */}
      {schedules.length === 0 && !showForm ? (
        <div className="flex h-32 flex-col items-center justify-center gap-2 text-center text-muted-foreground">
          <CalendarClock className="h-8 w-8 opacity-20" />
          <p className="text-sm">No schedules yet</p>
          <p className="text-xs">Click <strong>New schedule</strong> to auto-run this collection</p>
        </div>
      ) : (
        <div className="space-y-2">
          {schedules.map(s => (
            <ScheduleRow
              key={s.id}
              schedule={s}
              environments={environments}
              onToggle={handleToggle}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}
