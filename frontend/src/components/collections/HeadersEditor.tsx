"use client";

import { useEffect, useId, useState } from "react";
import { Plus, Trash2, Download, Upload, ChevronDown, Check } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface HeaderRow {
  id: string;
  key: string;
  value: string;
  enabled: boolean;
}

// ── Common header name suggestions ────────────────────────────────────────────

const COMMON_HEADERS = [
  "Accept", "Accept-Encoding", "Accept-Language", "Authorization",
  "Cache-Control", "Content-Type", "Content-Length", "Cookie",
  "Origin", "Referer", "User-Agent", "X-API-Key", "X-Auth-Token",
  "X-Forwarded-For", "X-Request-ID", "X-Requested-With",
];

// ── Header presets ────────────────────────────────────────────────────────────

const PRESETS: { label: string; headers: Record<string, string> }[] = [
  {
    label: "JSON API",
    headers: {
      "Content-Type": "application/json",
      "Accept":        "application/json",
    },
  },
  {
    label: "Bearer auth",
    headers: { "Authorization": "Bearer {{env.TOKEN}}" },
  },
  {
    label: "API key",
    headers: { "X-API-Key": "{{env.API_KEY}}" },
  },
  {
    label: "Form data",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  },
  {
    label: "No cache",
    headers: { "Cache-Control": "no-cache", "Pragma": "no-cache" },
  },
];

// ── Validation helpers ────────────────────────────────────────────────────────

// RFC 7230: header field names are tokens — printable ASCII except delimiters
const VALID_HEADER_KEY = /^[a-zA-Z0-9\-_!#$%&'*+.^`|~]+$/;

function isValidKey(k: string): boolean {
  return k === "" || VALID_HEADER_KEY.test(k);
}

// ── Import parsing ────────────────────────────────────────────────────────────

function parseCurl(text: string): Record<string, string> {
  const result: Record<string, string> = {};
  // Match -H "Key: Value" or -H 'Key: Value'
  const re = /-H\s+['"]([^'"]+)['"]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const colon = m[1].indexOf(":");
    if (colon > 0) {
      const key = m[1].slice(0, colon).trim();
      const val = m[1].slice(colon + 1).trim();
      result[key] = val;
    }
  }
  return result;
}

function parseJson(text: string): Record<string, string> | null {
  try {
    const obj = JSON.parse(text);
    if (typeof obj !== "object" || Array.isArray(obj)) return null;
    const result: Record<string, string> = {};
    for (const [k, v] of Object.entries(obj)) {
      result[k] = String(v);
    }
    return result;
  } catch { return null; }
}

// ── Row ID factory ────────────────────────────────────────────────────────────

let _id = 0;
export function newHeaderId() { return `h-${++_id}`; }

export function headersToRows(obj: Record<string, string>): HeaderRow[] {
  return Object.entries(obj).map(([key, value]) => ({
    id: newHeaderId(), key, value, enabled: true,
  }));
}

export function rowsToHeaders(rows: HeaderRow[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const r of rows) {
    if (r.enabled && r.key.trim()) result[r.key.trim()] = r.value;
  }
  return result;
}

// ── Suggestion dropdown for key input ─────────────────────────────────────────

function KeyInput({ value, onChange, invalid, isDuplicate }: {
  value: string;
  onChange: (v: string) => void;
  invalid: boolean;
  isDuplicate: boolean;
}) {
  const [open, setOpen] = useState(false);
  const filtered = COMMON_HEADERS.filter(
    h => h.toLowerCase().startsWith(value.toLowerCase()) && h.toLowerCase() !== value.toLowerCase()
  ).slice(0, 6);

  return (
    <div className="relative flex-1">
      <Input
        className={`h-7 text-xs font-mono ${invalid || isDuplicate ? "border-red-400 focus-visible:ring-red-300" : ""}`}
        placeholder="Header-Name"
        value={value}
        onChange={e => { onChange(e.target.value); setOpen(true); }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onFocus={() => value && setOpen(true)}
        autoComplete="off"
        spellCheck={false}
      />
      {(isDuplicate || invalid) && (
        <p className="absolute -bottom-4 left-0 text-[10px] text-red-500 whitespace-nowrap z-10">
          {isDuplicate ? "Duplicate key" : "Invalid header name"}
        </p>
      )}
      {open && filtered.length > 0 && (
        <ul className="absolute z-50 mt-0.5 w-full rounded-md border bg-background shadow-lg text-xs overflow-hidden">
          {filtered.map(h => (
            <li
              key={h}
              className="px-3 py-1.5 cursor-pointer hover:bg-muted transition-colors font-mono"
              onMouseDown={() => { onChange(h); setOpen(false); }}
            >
              {h}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Single header row ─────────────────────────────────────────────────────────

function HeaderRowItem({ row, rows, onChange, onDelete }: {
  row: HeaderRow;
  rows: HeaderRow[];
  onChange: (patch: Partial<HeaderRow>) => void;
  onDelete: () => void;
}) {
  const keyInvalid  = !isValidKey(row.key);
  const isDuplicate = row.key.trim() !== "" && rows.filter(r => r.id !== row.id && r.key.trim().toLowerCase() === row.key.trim().toLowerCase()).length > 0;

  return (
    <div className={`group flex items-center gap-2 py-1.5 border-b last:border-0 ${!row.enabled ? "opacity-50" : ""}`}>
      {/* Enable toggle */}
      <button
        type="button"
        className={`shrink-0 h-4 w-4 rounded border transition-colors ${row.enabled ? "bg-primary border-primary" : "border-muted-foreground/40"}`}
        onClick={() => onChange({ enabled: !row.enabled })}
        title={row.enabled ? "Disable header" : "Enable header"}
      >
        {row.enabled && <Check className="h-3 w-3 text-primary-foreground m-auto" />}
      </button>

      {/* Key */}
      <KeyInput
        value={row.key}
        onChange={key => onChange({ key })}
        invalid={keyInvalid}
        isDuplicate={isDuplicate}
      />

      {/* Separator */}
      <span className="text-muted-foreground text-xs shrink-0">:</span>

      {/* Value */}
      <Input
        className="h-7 flex-1 text-xs font-mono"
        placeholder="value or {{env.VAR}}"
        value={row.value}
        onChange={e => onChange({ value: e.target.value })}
        spellCheck={false}
      />

      {/* Delete */}
      <button
        type="button"
        className="shrink-0 text-muted-foreground hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all"
        onClick={onDelete}
        title="Remove header"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ── Import modal ──────────────────────────────────────────────────────────────

function ImportModal({ onImport, onClose }: {
  onImport: (rows: HeaderRow[]) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"curl" | "json">("json");
  const [text, setText] = useState("");

  const handle = () => {
    let parsed: Record<string, string> | null = null;
    if (tab === "curl") parsed = parseCurl(text);
    else parsed = parseJson(text);

    if (!parsed || Object.keys(parsed).length === 0) {
      toast.error(tab === "curl" ? "No -H flags found in curl command" : "Invalid JSON object");
      return;
    }
    onImport(headersToRows(parsed));
    onClose();
    toast.success(`Imported ${Object.keys(parsed).length} header(s)`);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl border bg-background shadow-xl p-5 space-y-4" onClick={e => e.stopPropagation()}>
        <div>
          <h3 className="font-semibold text-sm">Import headers</h3>
          <p className="text-xs text-muted-foreground mt-0.5">Paste a curl command or JSON object</p>
        </div>

        <div className="flex gap-1 rounded-lg border p-0.5 bg-muted w-fit">
          {(["json", "curl"] as const).map(t => (
            <button
              key={t}
              className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${tab === t ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
              onClick={() => setTab(t)}
            >
              {t === "json" ? "JSON" : "curl"}
            </button>
          ))}
        </div>

        <textarea
          className="w-full rounded-md border bg-muted/30 p-3 font-mono text-xs resize-none focus:outline-none focus:ring-1 focus:ring-primary"
          rows={6}
          placeholder={tab === "curl"
            ? `curl -X POST https://api.example.com/data \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer token"`
            : `{\n  "Content-Type": "application/json",\n  "Authorization": "Bearer token"\n}`}
          value={text}
          onChange={e => setText(e.target.value)}
          autoFocus
        />

        <div className="flex gap-2 justify-end">
          <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={handle}>Import</Button>
        </div>
      </div>
    </div>
  );
}

// ── Export dropdown ───────────────────────────────────────────────────────────

async function exportAsJson(rows: HeaderRow[]) {
  const obj = rowsToHeaders(rows);
  await navigator.clipboard.writeText(JSON.stringify(obj, null, 2));
  toast.success("Headers copied as JSON");
}

async function exportAsCurl(rows: HeaderRow[]) {
  const flags = rows
    .filter(r => r.enabled && r.key.trim())
    .map(r => `-H "${r.key.trim()}: ${r.value}"`)
    .join(" \\\n  ");
  await navigator.clipboard.writeText(flags);
  toast.success("Headers copied as curl -H flags");
}

// ── Main component ────────────────────────────────────────────────────────────

interface HeadersEditorProps {
  rows: HeaderRow[];
  onChange: (rows: HeaderRow[]) => void;
}

export function HeadersEditor({ rows, onChange }: HeadersEditorProps) {
  const [showImport, setShowImport] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [showPresets, setShowPresets] = useState(false);

  const enabled = rows.filter(r => r.enabled && r.key.trim()).length;

  const addRow = () =>
    onChange([...rows, { id: newHeaderId(), key: "", value: "", enabled: true }]);

  const updateRow = (id: string, patch: Partial<HeaderRow>) =>
    onChange(rows.map(r => r.id === id ? { ...r, ...patch } : r));

  const deleteRow = (id: string) =>
    onChange(rows.filter(r => r.id !== id));

  const applyPreset = (headers: Record<string, string>) => {
    const newRows = headersToRows(headers);
    // Merge: don't overwrite existing keys
    const existingKeys = new Set(rows.map(r => r.key.toLowerCase()));
    const toAdd = newRows.filter(r => !existingKeys.has(r.key.toLowerCase()));
    onChange([...rows, ...toAdd]);
    setShowPresets(false);
    toast.success(`Added ${toAdd.length} header(s) from preset`);
  };

  const handleImport = (newRows: HeaderRow[]) => {
    const existingKeys = new Set(rows.map(r => r.key.toLowerCase()));
    const toAdd = newRows.filter(r => !existingKeys.has(r.key.toLowerCase()));
    const toUpdate = newRows.filter(r => existingKeys.has(r.key.toLowerCase()));
    onChange([
      ...rows.map(r => {
        const match = toUpdate.find(u => u.key.toLowerCase() === r.key.toLowerCase());
        return match ? { ...r, value: match.value, enabled: true } : r;
      }),
      ...toAdd,
    ]);
  };

  return (
    <div className="space-y-2">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span>{rows.length} header{rows.length !== 1 ? "s" : ""}</span>
          {enabled !== rows.length && (
            <span className="text-muted-foreground/60">({enabled} active)</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {/* Presets dropdown */}
          <div className="relative">
            <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs px-2"
              onClick={() => { setShowPresets(o => !o); setShowExport(false); }}>
              Presets <ChevronDown className="h-3 w-3" />
            </Button>
            {showPresets && (
              <div className="absolute right-0 top-full mt-1 z-50 w-44 rounded-lg border bg-background shadow-lg py-1 text-xs">
                {PRESETS.map(p => (
                  <button key={p.label} className="w-full px-3 py-2 text-left hover:bg-muted transition-colors"
                    onClick={() => applyPreset(p.headers)}>
                    {p.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Import */}
          <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs px-2"
            onClick={() => { setShowImport(true); setShowExport(false); setShowPresets(false); }}>
            <Upload className="h-3 w-3" /> Import
          </Button>

          {/* Export dropdown */}
          {rows.length > 0 && (
            <div className="relative">
              <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs px-2"
                onClick={() => { setShowExport(o => !o); setShowPresets(false); }}>
                <Download className="h-3 w-3" /> Export <ChevronDown className="h-3 w-3" />
              </Button>
              {showExport && (
                <div className="absolute right-0 top-full mt-1 z-50 w-44 rounded-lg border bg-background shadow-lg py-1 text-xs">
                  <button className="w-full px-3 py-2 text-left hover:bg-muted transition-colors"
                    onClick={() => { exportAsJson(rows); setShowExport(false); }}>
                    Copy as JSON
                  </button>
                  <button className="w-full px-3 py-2 text-left hover:bg-muted transition-colors"
                    onClick={() => { exportAsCurl(rows); setShowExport(false); }}>
                    Copy as curl -H flags
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Header rows */}
      <div className="rounded-lg border bg-card overflow-hidden">
        {/* Column labels */}
        <div className="flex items-center gap-2 px-3 py-1.5 border-b bg-muted/30 text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
          <span className="w-4 shrink-0" />
          <span className="flex-1">Key</span>
          <span className="w-2 shrink-0" />
          <span className="flex-1">Value</span>
          <span className="w-5 shrink-0" />
        </div>

        <div className="divide-y px-3">
          {rows.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted-foreground">
              No headers — click + or choose a preset
            </p>
          ) : (
            rows.map(row => (
              <HeaderRowItem
                key={row.id}
                row={row}
                rows={rows}
                onChange={patch => updateRow(row.id, patch)}
                onDelete={() => deleteRow(row.id)}
              />
            ))
          )}
        </div>

        <div className="border-t px-3 py-2 bg-muted/10">
          <button
            type="button"
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            onClick={addRow}
          >
            <Plus className="h-3.5 w-3.5" />
            Add header
          </button>
        </div>
      </div>

      {/* Validation summary */}
      {rows.some(r => r.key && !isValidKey(r.key)) && (
        <p className="text-[11px] text-red-500">
          Some header names are invalid. Header names must be ASCII letters, digits, or <code>-_!#$%&amp;'*+.^`|~</code>
        </p>
      )}

      {/* Import modal */}
      {showImport && (
        <ImportModal onImport={handleImport} onClose={() => setShowImport(false)} />
      )}

      {/* Close dropdowns on outside click */}
      {(showExport || showPresets) && (
        <div className="fixed inset-0 z-40" onClick={() => { setShowExport(false); setShowPresets(false); }} />
      )}
    </div>
  );
}
