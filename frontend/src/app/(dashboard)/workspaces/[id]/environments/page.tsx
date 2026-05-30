"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  Plus, Trash2, Eye, EyeOff, Lock, CheckCircle2,
  Settings2, X, Save, RefreshCw, Play,
} from "lucide-react";
import { toast } from "sonner";
import { environmentService, type BulkVariable } from "@/lib/services/environment.service";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import type { Environment, EnvVariable } from "@/types";

const SECRET_SENTINEL = "***";

interface EditableRow {
  id?: string;
  key: string;
  value: string;
  is_secret: boolean;
  revealed: boolean;
  dirty: boolean;
}

function fromVar(v: EnvVariable): EditableRow {
  return { id: v.id, key: v.key, value: v.value, is_secret: v.is_secret, revealed: false, dirty: false };
}

// ── Environment list item ─────────────────────────────────────────────────────

function EnvListItem({
  env, isSelected, onSelect, onActivate, onDeactivate, onDelete, onRename,
}: {
  env: Environment; isSelected: boolean;
  onSelect: () => void; onActivate: () => void; onDeactivate: () => void;
  onDelete: () => void; onRename: (name: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(env.name);

  const commit = () => {
    if (name.trim() && name !== env.name) onRename(name.trim());
    setEditing(false);
  };

  return (
    <div
      className={`group flex items-center gap-2 rounded-md px-3 py-2 cursor-pointer transition-colors ${
        isSelected ? "bg-secondary" : "hover:bg-muted/50"
      }`}
      onClick={onSelect}
    >
      <div className="flex-1 min-w-0">
        {editing ? (
          <Input autoFocus className="h-6 text-sm px-1" value={name}
            onChange={e => setName(e.target.value)}
            onBlur={commit}
            onKeyDown={e => { if (e.key === "Enter") commit(); if (e.key === "Escape") { setName(env.name); setEditing(false); } }}
            onClick={e => e.stopPropagation()} />
        ) : (
          <p className="text-sm font-medium truncate">{env.name}</p>
        )}
        <p className="text-xs text-muted-foreground">
          {env.variable_count ?? 0} variable{(env.variable_count ?? 0) !== 1 ? "s" : ""}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {env.is_active && (
          <span className="rounded-full border px-1.5 py-0 text-[10px] font-medium bg-emerald-500/15 text-emerald-700 border-emerald-200">
            Active
          </span>
        )}
        <div className="hidden group-hover:flex items-center gap-0.5">
          <button className="rounded p-1 hover:bg-muted text-muted-foreground hover:text-foreground"
            onClick={e => { e.stopPropagation(); setEditing(true); }} title="Rename">
            <Settings2 className="h-3 w-3" />
          </button>
          <button className="rounded p-1 hover:bg-muted text-muted-foreground hover:text-red-600"
            onClick={e => { e.stopPropagation(); onDelete(); }} title="Delete">
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Variable row ──────────────────────────────────────────────────────────────

function VariableRow({ row, index, onChange, onDelete }: {
  row: EditableRow; index: number;
  onChange: (i: number, patch: Partial<EditableRow>) => void;
  onDelete: (i: number) => void;
}) {
  const showValue = !row.is_secret || row.revealed;
  return (
    <tr className={`border-b last:border-0 ${row.dirty ? "bg-amber-500/3" : ""}`}>
      <td className="px-3 py-1.5 w-48">
        <Input className="h-7 text-xs font-mono" placeholder="VARIABLE_NAME"
          value={row.key} onChange={e => onChange(index, { key: e.target.value, dirty: true })} />
      </td>
      <td className="px-3 py-1.5">
        <div className="flex items-center gap-1">
          <Input className="h-7 text-xs font-mono flex-1"
            placeholder={row.is_secret ? "Enter secret value…" : "value"}
            type={showValue ? "text" : "password"}
            value={row.value}
            onFocus={() => {
              if (row.is_secret && !row.revealed && row.value === SECRET_SENTINEL)
                onChange(index, { value: "", revealed: true });
            }}
            onChange={e => onChange(index, { value: e.target.value, dirty: true })} />
          {row.is_secret && (
            <button type="button" className="shrink-0 text-muted-foreground hover:text-foreground"
              onClick={() => onChange(index, { revealed: !row.revealed })}
              title={row.revealed ? "Hide" : "Show"}>
              {row.revealed ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
          )}
        </div>
      </td>
      <td className="px-3 py-1.5 w-16 text-center">
        <button type="button"
          className={`rounded p-1 transition-colors ${row.is_secret ? "text-amber-600 bg-amber-500/10" : "text-muted-foreground hover:text-foreground"}`}
          onClick={() => onChange(index, { is_secret: !row.is_secret, dirty: true })}
          title={row.is_secret ? "Mark as plain" : "Mark as secret"}>
          <Lock className="h-3.5 w-3.5" />
        </button>
      </td>
      <td className="px-3 py-1.5 w-10 text-center">
        <button type="button" className="rounded p-1 text-muted-foreground hover:text-red-600"
          onClick={() => onDelete(index)}>
          <X className="h-3.5 w-3.5" />
        </button>
      </td>
    </tr>
  );
}

// ── Preview panel ─────────────────────────────────────────────────────────────

function PreviewPanel({ envId }: { envId: string }) {
  const [template, setTemplate] = useState("{{env.BASE_URL}}/users");
  const [result, setResult] = useState("");
  const [resolved, setResolved] = useState<string[]>([]);
  const [unresolved, setUnresolved] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    setLoading(true);
    try {
      const r = await environmentService.preview(envId, template);
      setResult(r.data.result);
      setResolved(r.data.resolved_keys);
      setUnresolved(r.data.unresolved_keys);
    } catch { toast.error("Preview failed"); }
    finally { setLoading(false); }
  };

  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      <h3 className="text-sm font-semibold flex items-center gap-2">
        <Play className="h-4 w-4 text-muted-foreground" />
        Variable preview
      </h3>
      <p className="text-xs text-muted-foreground">
        Test how <code className="font-mono bg-muted px-1 rounded">{"{{env.KEY}}"}</code> placeholders
        resolve with this environment's variables.
      </p>
      <div className="flex gap-2">
        <Input className="h-8 text-xs font-mono flex-1" placeholder="{{env.BASE_URL}}/endpoint"
          value={template} onChange={e => setTemplate(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") run(); }} />
        <Button size="sm" className="h-8" onClick={run} disabled={loading}>
          {loading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : "Preview"}
        </Button>
      </div>
      {result !== "" && (
        <div className="space-y-2">
          <div className="rounded-md bg-muted px-3 py-2">
            <p className="text-[11px] text-muted-foreground mb-1">Result</p>
            <p className="text-sm font-mono break-all">{result}</p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {resolved.map(k => (
              <span key={k} className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 text-emerald-700 px-2 py-0.5 text-[11px]">
                <CheckCircle2 className="h-3 w-3" />{k}
              </span>
            ))}
            {unresolved.map(k => (
              <span key={k} className="inline-flex items-center gap-1 rounded-full bg-red-500/10 text-red-700 px-2 py-0.5 text-[11px]">
                <X className="h-3 w-3" />{k} (missing)
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function EnvironmentsPage() {
  const { id: workspaceId } = useParams<{ id: string }>();
  const { setActiveEnvironment } = useWorkspaceStore();

  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [rows, setRows] = useState<EditableRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const loadEnvs = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    try { setEnvironments((await environmentService.list(workspaceId)).data); }
    catch { toast.error("Failed to load environments"); }
    finally { setLoading(false); }
  }, [workspaceId]);

  useEffect(() => { loadEnvs(); }, [loadEnvs]);

  const selectEnv = useCallback(async (envId: string) => {
    setSelectedId(envId);
    try { setRows((await environmentService.get(envId)).data.variables.map(fromVar)); }
    catch { toast.error("Failed to load variables"); }
  }, []);

  const patchRow = (i: number, patch: Partial<EditableRow>) =>
    setRows(rs => rs.map((r, idx) => idx === i ? { ...r, ...patch } : r));
  const deleteRow = (i: number) => setRows(rs => rs.filter((_, idx) => idx !== i));
  const addRow    = () => setRows(rs => [...rs, { key: "", value: "", is_secret: false, revealed: false, dirty: true }]);

  const save = async () => {
    if (!selectedId) return;
    if (rows.some(r => !r.key.trim())) { toast.error("All variables must have a key"); return; }
    setSaving(true);
    try {
      const vars: BulkVariable[] = rows.map(r => ({ key: r.key.trim(), value: r.value, is_secret: r.is_secret }));
      const res = await environmentService.bulkUpsert(selectedId, vars);
      setRows(res.data.map(fromVar));
      setEnvironments(envs => envs.map(e => e.id === selectedId ? { ...e, variable_count: res.data.length } : e));
      toast.success("Variables saved");
    } catch { toast.error("Failed to save"); }
    finally { setSaving(false); }
  };

  const createEnv = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const r = await environmentService.create(workspaceId, newName.trim());
      setEnvironments(e => [...e, r.data]);
      setNewName("");
      await selectEnv(r.data.id);
      toast.success(`"${r.data.name}" created`);
    } catch { toast.error("Failed to create environment"); }
    finally { setCreating(false); }
  };

  const activate = async (envId: string) => {
    try {
      await environmentService.activate(envId);
      const updated = environments.map(e => ({ ...e, is_active: e.id === envId }));
      setEnvironments(updated);
      const active = updated.find(e => e.id === envId);
      if (active) setActiveEnvironment(active);
      toast.success("Environment activated");
    } catch { toast.error("Failed to activate"); }
  };

  const deactivate = async (envId: string) => {
    try {
      await environmentService.deactivate(envId);
      setEnvironments(envs => envs.map(e => e.id === envId ? { ...e, is_active: false } : e));
      setActiveEnvironment(null);
    } catch { toast.error("Failed to deactivate"); }
  };

  const rename = async (envId: string, name: string) => {
    try {
      await environmentService.update(envId, name);
      setEnvironments(envs => envs.map(e => e.id === envId ? { ...e, name } : e));
    } catch { toast.error("Failed to rename"); }
  };

  const deleteEnv = async (envId: string) => {
    try {
      await environmentService.delete(envId);
      setEnvironments(envs => envs.filter(e => e.id !== envId));
      if (selectedId === envId) { setSelectedId(null); setRows([]); }
      toast.success("Deleted");
    } catch { toast.error("Failed to delete"); }
  };

  const selected  = environments.find(e => e.id === selectedId);
  const hasDirty  = rows.some(r => r.dirty);

  return (
    <>
      <Header title="Environments" description="Variable sets for Development, Staging, and Production" />

      <div className="flex flex-1 overflow-hidden">

        {/* Left: env list */}
        <aside className="flex w-56 flex-col border-r bg-muted/20">
          <div className="flex-1 overflow-auto p-2 space-y-0.5">
            {loading ? [...Array(3)].map((_, i) => <Skeleton key={i} className="h-12 rounded-md" />) :
             environments.length === 0 ? (
               <p className="px-3 py-6 text-center text-xs text-muted-foreground">No environments yet</p>
             ) : environments.map(env => (
               <EnvListItem key={env.id} env={env} isSelected={selectedId === env.id}
                 onSelect={() => selectEnv(env.id)}
                 onActivate={() => activate(env.id)} onDeactivate={() => deactivate(env.id)}
                 onDelete={() => deleteEnv(env.id)} onRename={name => rename(env.id, name)} />
             ))}
          </div>
          <div className="border-t p-2 space-y-1.5">
            <Input className="h-7 text-xs" placeholder="New environment…" value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") createEnv(); }} />
            <Button size="sm" className="w-full h-7 text-xs" disabled={!newName.trim() || creating} onClick={createEnv}>
              <Plus className="mr-1.5 h-3 w-3" />Create
            </Button>
          </div>
        </aside>

        {/* Right: variable editor */}
        {!selectedId ? (
          <div className="flex flex-1 items-center justify-center">
            <div className="text-center">
              <Settings2 className="mx-auto mb-3 h-8 w-8 text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">Select an environment to manage its variables</p>
              <p className="text-xs text-muted-foreground mt-1">
                Use <code className="font-mono bg-muted px-1 rounded text-[11px]">{"{{env.KEY}}"}</code> in request URLs, headers, and bodies
              </p>
            </div>
          </div>
        ) : (
          <div className="flex flex-1 flex-col overflow-hidden">
            {/* Toolbar */}
            <div className="flex items-center justify-between border-b px-5 py-3">
              <div className="flex items-center gap-3">
                <span className="font-semibold">{selected?.name}</span>
                {selected?.is_active && (
                  <span className="rounded-full border px-2 py-0.5 text-[11px] font-medium bg-emerald-500/15 text-emerald-700 border-emerald-200">
                    Active
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {selected?.is_active ? (
                  <Button variant="outline" size="sm" onClick={() => deactivate(selectedId)}>Deactivate</Button>
                ) : (
                  <Button variant="outline" size="sm" onClick={() => activate(selectedId)}>
                    <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />Set as active
                  </Button>
                )}
                <Button size="sm" disabled={!hasDirty || saving} onClick={save}>
                  <Save className="mr-1.5 h-3.5 w-3.5" />
                  {saving ? "Saving…" : "Save"}
                  {hasDirty && !saving && <span className="ml-1.5 h-1.5 w-1.5 rounded-full bg-amber-400" />}
                </Button>
              </div>
            </div>

            <div className="flex-1 overflow-auto p-5 space-y-5">
              {/* Variable table */}
              <div className="rounded-lg border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 border-b">
                    <tr>
                      <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">Key</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">Value</th>
                      <th className="px-3 py-2 text-center text-xs font-medium text-muted-foreground w-16" title="Secret values are masked in API responses">
                        Secret
                      </th>
                      <th className="px-3 py-2 w-10" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.length === 0 ? (
                      <tr><td colSpan={4} className="px-3 py-8 text-center text-xs text-muted-foreground">No variables — add one below</td></tr>
                    ) : rows.map((row, i) => (
                      <VariableRow key={i} row={row} index={i} onChange={patchRow} onDelete={deleteRow} />
                    ))}
                  </tbody>
                </table>
                <div className="border-t bg-muted/20 px-3 py-2">
                  <button className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground" onClick={addRow}>
                    <Plus className="h-3.5 w-3.5" />Add variable
                  </button>
                </div>
              </div>

              {/* Quick presets */}
              {rows.length === 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">Quick add:</p>
                  <div className="flex flex-wrap gap-2">
                    {[
                      { key: "BASE_URL", value: "https://api.example.com", secret: false },
                      { key: "TOKEN",    value: "",    secret: true },
                      { key: "API_KEY",  value: "",    secret: true },
                    ].map(p => (
                      <button key={p.key}
                        className="rounded-full border px-3 py-1 text-xs hover:bg-muted transition-colors"
                        onClick={() => setRows(rs => [...rs, { key: p.key, value: p.value, is_secret: p.secret, revealed: false, dirty: true }])}>
                        + {p.key}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <Separator />
              <PreviewPanel envId={selectedId} />
            </div>
          </div>
        )}
      </div>
    </>
  );
}
