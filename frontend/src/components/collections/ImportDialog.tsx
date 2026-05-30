"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Upload, FileJson, CheckCircle2, AlertTriangle, X,
  Loader2, FolderOpen, Zap, ChevronDown,
} from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ImportResult {
  collection_id: string;
  collection_name: string;
  total_requests: number;
  skipped: number;
  errors: { request: string; reason: string }[];
  warnings: string[];
}

interface PostmanPreview {
  name: string;
  totalItems: number;
  folders: number;
  requests: number;
  hasAuth: boolean;
  schemaVersion: string;
}

// ── Postman client-side preview parser ────────────────────────────────────────

function countItems(items: any[]): { requests: number; folders: number } {
  let requests = 0, folders = 0;
  for (const item of items ?? []) {
    if (item?.item) {
      folders++;
      const sub = countItems(item.item);
      requests += sub.requests;
      folders  += sub.folders;
    } else if (item?.request) {
      requests++;
    }
  }
  return { requests, folders };
}

function previewPostmanFile(data: any): PostmanPreview | null {
  if (!data?.info) return null;
  const schema = data.info?.schema ?? "";
  if (!schema.includes("getpostman") && schema) return null;

  const version = schema.includes("v2.1") ? "v2.1" : schema.includes("v2.0") ? "v2.0" : "unknown";
  const { requests, folders } = countItems(data.item ?? []);

  return {
    name: data.info?.name ?? "Unnamed Collection",
    totalItems: (data.item ?? []).length,
    requests,
    folders,
    hasAuth: !!data.auth,
    schemaVersion: version,
  };
}

// ── Error list ────────────────────────────────────────────────────────────────

function ErrorList({ errors }: { errors: { request: string; reason: string }[] }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? errors : errors.slice(0, 3);

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 space-y-2">
      <p className="text-xs font-semibold text-amber-700">
        {errors.length} request{errors.length !== 1 ? "s" : ""} could not be imported
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

// ── Drop zone ─────────────────────────────────────────────────────────────────

function DropZone({ onFile }: { onFile: (file: File) => void }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) onFile(file);
  }, [onFile]);

  return (
    <div
      className={`flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-10 transition-colors cursor-pointer ${dragging ? "border-primary bg-primary/5" : "border-muted-foreground/25 hover:border-primary/50 hover:bg-muted/30"}`}
      onDragOver={e => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
    >
      <div className={`rounded-full p-4 ${dragging ? "bg-primary/10" : "bg-muted"}`}>
        <Upload className={`h-8 w-8 ${dragging ? "text-primary" : "text-muted-foreground"}`} />
      </div>
      <div className="text-center">
        <p className="font-medium text-sm">Drop Postman collection here</p>
        <p className="text-xs text-muted-foreground mt-1">or click to browse · JSON, v2.0 and v2.1</p>
      </div>
      <input ref={inputRef} type="file" accept=".json,application/json" className="hidden"
        onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f); }} />
    </div>
  );
}

// ── Preview card ──────────────────────────────────────────────────────────────

function PreviewCard({ preview, file, onClear }: {
  preview: PostmanPreview; file: File; onClear: () => void;
}) {
  return (
    <div className="rounded-xl border bg-card p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="rounded-lg bg-blue-500/10 p-2">
            <FileJson className="h-5 w-5 text-blue-600" />
          </div>
          <div>
            <p className="font-semibold text-sm">{preview.name}</p>
            <p className="text-[11px] text-muted-foreground">
              Postman Collection {preview.schemaVersion} · {file.name}
            </p>
          </div>
        </div>
        <button className="text-muted-foreground hover:text-foreground" onClick={onClear}>
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="grid grid-cols-3 gap-2">
        {[
          { icon: FolderOpen, label: "Requests", value: preview.requests },
          { icon: ChevronDown, label: "Folders",  value: preview.folders  },
          { icon: Zap,         label: "Auth",      value: preview.hasAuth ? "Yes" : "None" },
        ].map(({ icon: Icon, label, value }) => (
          <div key={label} className="rounded-lg bg-muted/40 px-3 py-2 text-center">
            <p className="text-lg font-bold tabular-nums">{value}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</p>
          </div>
        ))}
      </div>

      {preview.schemaVersion === "unknown" && (
        <div className="flex items-center gap-1.5 text-xs text-amber-600">
          <AlertTriangle className="h-3.5 w-3.5" />
          Schema version not recognised — import may be incomplete
        </div>
      )}
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
            <p className="text-[11px] text-muted-foreground">
              "{result.collection_name}" created
            </p>
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
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-500" />
          {w}
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
  const [file, setFile]       = useState<File | null>(null);
  const [preview, setPreview] = useState<PostmanPreview | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [result, setResult]   = useState<ImportResult | null>(null);

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
        const prev = previewPostmanFile(data);
        if (!prev) setParseError("This doesn't look like a Postman Collection. Make sure it's a v2.0 or v2.1 JSON export.");
        else setPreview(prev);
      } catch {
        setParseError("Invalid JSON file — could not parse the collection.");
      }
    };
    reader.readAsText(f);
  };

  const handleImport = async () => {
    if (!file) return;
    setImporting(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const { data } = await api.post<ImportResult>(
        `/workspaces/${workspaceId}/import/postman`,
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

  return (
    <Dialog open={open} onOpenChange={v => !v && handleClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileJson className="h-5 w-5 text-blue-500" />
            Import Postman Collection
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 pt-2">
          {/* Result state */}
          {result ? (
            <ResultCard result={result} workspaceId={workspaceId} />
          ) : (
            <>
              {/* Drop zone or preview */}
              {!file
                ? <DropZone onFile={handleFile} />
                : preview
                  ? <PreviewCard preview={preview} file={file} onClear={reset} />
                  : null
              }

              {/* Parse error */}
              {parseError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                  {parseError}
                </div>
              )}

              {/* Actions */}
              {preview && !parseError && (
                <div className="flex gap-2">
                  <Button variant="outline" className="flex-1" onClick={reset} disabled={importing}>
                    Choose different file
                  </Button>
                  <Button className="flex-1 gap-2" onClick={handleImport} disabled={importing}>
                    {importing ? <><Loader2 className="h-4 w-4 animate-spin" />Importing…</> : "Import collection"}
                  </Button>
                </div>
              )}
            </>
          )}

          {/* Format hint */}
          {!file && !result && (
            <p className="text-center text-[11px] text-muted-foreground">
              Export from Postman: <strong>Collection → ⋯ → Export → Collection v2.1</strong>
            </p>
          )}

          {result && (
            <Button variant="outline" className="w-full" onClick={handleClose}>
              Done
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
