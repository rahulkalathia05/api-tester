"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Upload, FileJson, CheckCircle2, AlertTriangle, X,
  Loader2, FolderOpen, Zap, ChevronDown, Code2,
} from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

// ── Types ─────────────────────────────────────────────────────────────────────

type ImportFormat = "postman" | "openapi" | null;

interface ImportResult {
  collection_id: string;
  collection_name: string;
  total_requests: number;
  skipped: number;
  errors: { request: string; reason: string }[];
  warnings: string[];
}

interface FilePreview {
  format: ImportFormat;
  name: string;
  description?: string;
  // Postman-specific
  folders?: number;
  requests?: number;
  hasAuth?: boolean;
  schemaVersion?: string;
  // OpenAPI-specific
  pathCount?: number;
  operationCount?: number;
  serverUrl?: string;
  hasSecuritySchemes?: boolean;
}

// ── Client-side format detection & preview ────────────────────────────────────

function detectFormat(data: any): ImportFormat {
  if (!data || typeof data !== "object") return null;
  if (data.info?.schema?.includes("getpostman") || data.info?.name && data.item !== undefined) return "postman";
  if (typeof data.openapi === "string" && data.openapi.startsWith("3")) return "openapi";
  if (data.swagger === "2.0") return "openapi";
  return null;
}

function countPostmanItems(items: any[]): { requests: number; folders: number } {
  let requests = 0, folders = 0;
  for (const item of items ?? []) {
    if (item?.item) { folders++; const s = countPostmanItems(item.item); requests += s.requests; folders += s.folders; }
    else if (item?.request) requests++;
  }
  return { requests, folders };
}

function countOASOperations(paths: Record<string, any>): number {
  const HTTP = ["get","post","put","patch","delete","head","options"];
  let count = 0;
  for (const item of Object.values(paths ?? {})) {
    for (const m of HTTP) { if (item?.[m]) count++; }
  }
  return count;
}

function buildPreview(data: any): FilePreview | null {
  const fmt = detectFormat(data);
  if (!fmt) return null;

  if (fmt === "postman") {
    const { requests, folders } = countPostmanItems(data.item ?? []);
    const schema = data.info?.schema ?? "";
    return {
      format: "postman",
      name: data.info?.name ?? "Postman Collection",
      requests, folders,
      hasAuth: !!data.auth,
      schemaVersion: schema.includes("v2.1") ? "v2.1" : "v2.0",
    };
  }

  // OpenAPI / Swagger
  const paths = data.paths ?? {};
  const servers = data.servers ?? [];
  return {
    format: "openapi",
    name: data.info?.title ?? "OpenAPI Spec",
    description: data.info?.description,
    pathCount: Object.keys(paths).length,
    operationCount: countOASOperations(paths),
    serverUrl: servers[0]?.url ?? data.host ?? "",
    hasSecuritySchemes: !!(
      data.components?.securitySchemes || data.securityDefinitions
    ),
    schemaVersion: data.openapi ?? data.swagger ?? "",
  };
}

// ── Error list ────────────────────────────────────────────────────────────────

function ErrorList({ errors }: { errors: { request: string; reason: string }[] }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? errors : errors.slice(0, 3);
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 space-y-2">
      <p className="text-xs font-semibold text-amber-700">
        {errors.length} item{errors.length !== 1 ? "s" : ""} could not be imported
      </p>
      <div className="space-y-1">
        {shown.map((e, i) => (
          <div key={i} className="flex items-start gap-1.5 text-xs text-amber-700">
            <span className="shrink-0">•</span>
            <span><strong>{e.request}</strong>: {e.reason}</span>
          </div>
        ))}
      </div>
      {errors.length > 3 && (
        <button className="text-[11px] text-amber-600 underline underline-offset-2"
          onClick={() => setExpanded(e => !e)}>
          {expanded ? "Show less" : `Show ${errors.length - 3} more`}
        </button>
      )}
    </div>
  );
}

// ── Format picker ─────────────────────────────────────────────────────────────

function FormatPicker({ selected, onChange }: {
  selected: "postman" | "openapi";
  onChange: (f: "postman" | "openapi") => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {([
        { value: "postman" as const,  label: "Postman",       icon: FolderOpen, desc: "Collection v2.0 / v2.1" },
        { value: "openapi" as const,  label: "OpenAPI / Swagger", icon: Code2,  desc: "OAS 3.x or Swagger 2.0" },
      ]).map(({ value, label, icon: Icon, desc }) => (
        <button key={value} type="button"
          className={`flex flex-col items-center gap-1.5 rounded-lg border p-3 text-xs transition-all ${selected === value ? "border-primary bg-primary/5 text-primary shadow-sm" : "border-border text-muted-foreground hover:border-muted-foreground/40"}`}
          onClick={() => onChange(value)}>
          <Icon className="h-5 w-5" />
          <span className="font-medium">{label}</span>
          <span className="text-[10px] text-muted-foreground">{desc}</span>
        </button>
      ))}
    </div>
  );
}

// ── Drop zone ─────────────────────────────────────────────────────────────────

function DropZone({ onFile, accept }: { onFile: (file: File) => void; accept: string }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) onFile(f);
  }, [onFile]);

  return (
    <div
      className={`flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-10 cursor-pointer transition-colors ${dragging ? "border-primary bg-primary/5" : "border-muted-foreground/25 hover:border-primary/50 hover:bg-muted/30"}`}
      onDragOver={e => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
    >
      <div className={`rounded-full p-4 ${dragging ? "bg-primary/10" : "bg-muted"}`}>
        <Upload className={`h-8 w-8 ${dragging ? "text-primary" : "text-muted-foreground"}`} />
      </div>
      <div className="text-center">
        <p className="font-medium text-sm">Drop your file here</p>
        <p className="text-xs text-muted-foreground mt-1">or click to browse · JSON (YAML coming soon)</p>
      </div>
      <input ref={inputRef} type="file" accept={accept} className="hidden"
        onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f); }} />
    </div>
  );
}

// ── Preview card ──────────────────────────────────────────────────────────────

function PreviewCard({ preview, file, onClear }: {
  preview: FilePreview; file: File; onClear: () => void;
}) {
  const isOAS = preview.format === "openapi";
  const Icon  = isOAS ? Code2 : FolderOpen;
  const color = isOAS ? "bg-violet-500/10 text-violet-600" : "bg-blue-500/10 text-blue-600";

  const stats = isOAS
    ? [
        { label: "Paths",       value: preview.pathCount ?? 0 },
        { label: "Endpoints",   value: preview.operationCount ?? 0 },
        { label: "Security",    value: preview.hasSecuritySchemes ? "Yes" : "None" },
      ]
    : [
        { label: "Requests",  value: preview.requests ?? 0 },
        { label: "Folders",   value: preview.folders  ?? 0 },
        { label: "Auth",      value: preview.hasAuth ? "Yes" : "None" },
      ];

  return (
    <div className="rounded-xl border bg-card p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className={`rounded-lg p-2 ${color}`}>
            <Icon className="h-5 w-5" />
          </div>
          <div>
            <p className="font-semibold text-sm">{preview.name}</p>
            <p className="text-[11px] text-muted-foreground">
              {isOAS ? `OpenAPI ${preview.schemaVersion}` : `Postman ${preview.schemaVersion}`}
              {" · "}{file.name}
            </p>
            {preview.serverUrl && (
              <p className="text-[11px] font-mono text-muted-foreground truncate max-w-[280px]">
                {preview.serverUrl}
              </p>
            )}
          </div>
        </div>
        <button className="text-muted-foreground hover:text-foreground" onClick={onClear}>
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="grid grid-cols-3 gap-2">
        {stats.map(({ label, value }) => (
          <div key={label} className="rounded-lg bg-muted/40 px-3 py-2 text-center">
            <p className="text-lg font-bold tabular-nums">{value}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Result card ───────────────────────────────────────────────────────────────

function ResultCard({ result, workspaceId }: { result: ImportResult; workspaceId: string }) {
  const router = useRouter();
  return (
    <div className="space-y-3">
      <div className="rounded-xl border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-5 w-5 text-emerald-500" />
          <div>
            <p className="font-semibold text-sm">Import complete</p>
            <p className="text-[11px] text-muted-foreground">"{result.collection_name}" created</p>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-center">
          <div className="rounded-lg bg-emerald-500/10 px-3 py-2">
            <p className="text-xl font-bold text-emerald-600">{result.total_requests}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Imported</p>
          </div>
          <div className={`rounded-lg px-3 py-2 ${result.skipped > 0 ? "bg-amber-500/10" : "bg-muted/40"}`}>
            <p className={`text-xl font-bold ${result.skipped > 0 ? "text-amber-600" : "text-muted-foreground"}`}>
              {result.skipped}
            </p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Skipped</p>
          </div>
        </div>
        <Button className="w-full gap-2" size="sm"
          onClick={() => router.push(`/workspaces/${workspaceId}/collections/${result.collection_id}`)}>
          Open collection →
        </Button>
      </div>
      {result.errors.length > 0 && <ErrorList errors={result.errors} />}
      {result.warnings.map((w, i) => (
        <p key={i} className="text-xs text-muted-foreground flex items-center gap-1.5">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-500" />{w}
        </p>
      ))}
    </div>
  );
}

// ── Main dialog ───────────────────────────────────────────────────────────────

interface ImportDialogProps {
  open: boolean;
  onClose: () => void;
  workspaceId: string;
  onSuccess?: () => void;
}

export function ImportDialog({ open, onClose, workspaceId, onSuccess }: ImportDialogProps) {
  const [manualFormat, setManualFormat] = useState<"postman" | "openapi">("postman");
  const [file, setFile]         = useState<File | null>(null);
  const [preview, setPreview]   = useState<FilePreview | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [result, setResult]     = useState<ImportResult | null>(null);

  const reset = () => {
    setFile(null); setPreview(null); setParseError(null);
    setImporting(false); setResult(null);
  };

  const handleClose = () => { reset(); onClose(); };

  const handleFile = (f: File) => {
    setFile(f); setPreview(null); setParseError(null); setResult(null);
    const reader = new FileReader();
    reader.onload = e => {
      try {
        const data = JSON.parse(e.target?.result as string);
        const prev = buildPreview(data);
        if (!prev) {
          setParseError("Could not recognise the file format. Make sure it's a Postman Collection v2.x or an OpenAPI/Swagger JSON spec.");
          return;
        }
        setPreview(prev);
        // Auto-switch format picker to match detected format
        if (prev.format) setManualFormat(prev.format);
      } catch {
        setParseError("Invalid JSON — could not parse the file.");
      }
    };
    reader.readAsText(f);
  };

  const handleImport = async () => {
    if (!file) return;
    const format = preview?.format ?? manualFormat;
    const endpoint = format === "openapi" ? "openapi" : "postman";
    setImporting(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const { data } = await api.post<ImportResult>(
        `/workspaces/${workspaceId}/import/${endpoint}`,
        formData,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      setResult(data);
      onSuccess?.();
      toast.success(`Imported ${data.total_requests} requests into "${data.collection_name}"`);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Import failed";
      setParseError(typeof detail === "string" ? detail : JSON.stringify(detail));
      toast.error("Import failed");
    } finally {
      setImporting(false);
    }
  };

  const hints: Record<string, string> = {
    postman: "Postman: Collection → ⋯ → Export → Collection v2.1",
    openapi: "OpenAPI: download your spec from /openapi.json or Swagger UI",
  };

  return (
    <Dialog open={open} onOpenChange={v => !v && handleClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Upload className="h-5 w-5 text-muted-foreground" />
            Import Collection
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 pt-2">
          {result ? (
            <>
              <ResultCard result={result} workspaceId={workspaceId} />
              <Button variant="outline" className="w-full" onClick={handleClose}>Done</Button>
            </>
          ) : (
            <>
              {/* Format selector (always visible) */}
              {!file && <FormatPicker selected={manualFormat} onChange={setManualFormat} />}

              {/* Drop zone or preview */}
              {!file
                ? <DropZone onFile={handleFile} accept=".json,.yaml,.yml" />
                : preview
                  ? <PreviewCard preview={preview} file={file} onClear={reset} />
                  : null
              }

              {/* Parse error */}
              {parseError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />{parseError}
                </div>
              )}

              {/* Actions */}
              {preview && !parseError && (
                <div className="flex gap-2">
                  <Button variant="outline" className="flex-1" onClick={reset} disabled={importing}>
                    Choose different file
                  </Button>
                  <Button className="flex-1 gap-2" onClick={handleImport} disabled={importing}>
                    {importing
                      ? <><Loader2 className="h-4 w-4 animate-spin" />Importing…</>
                      : "Import collection"}
                  </Button>
                </div>
              )}

              {/* Format hint */}
              {!file && (
                <p className="text-center text-[11px] text-muted-foreground">
                  {hints[manualFormat]}
                </p>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
