"use client";

import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Plus,
  Minus,
  ArrowLeftRight,
  CheckCircle2,
  Clock,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { FieldChange, ResultDiff, ResultSnapshot, SectionDiff } from "@/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(new Date(iso));
}

function fmtMs(ms: number | null): string {
  if (ms === null) return "—";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

// ── Change type styling ───────────────────────────────────────────────────────

const CHANGE_STYLES = {
  added:   { bg: "bg-emerald-500/8 border-emerald-200",  text: "text-emerald-700", icon: <Plus  className="h-3 w-3 shrink-0 text-emerald-500" />, label: "Added" },
  removed: { bg: "bg-red-500/8 border-red-200",          text: "text-red-700",     icon: <Minus className="h-3 w-3 shrink-0 text-red-500" />,     label: "Removed" },
  changed: { bg: "bg-amber-500/8 border-amber-200",      text: "text-amber-700",   icon: <ArrowLeftRight className="h-3 w-3 shrink-0 text-amber-500" />, label: "Changed" },
  unchanged: { bg: "", text: "", icon: null, label: "" },
} as const;

// ── Individual field change row ────────────────────────────────────────────────

function ChangeRow({ change }: { change: FieldChange }) {
  const style = CHANGE_STYLES[change.change_type];
  if (change.change_type === "unchanged") return null;

  return (
    <div className={`flex items-start gap-2 rounded border px-3 py-2 text-xs ${style.bg}`}>
      <span className="mt-0.5">{style.icon}</span>
      <div className="min-w-0 flex-1">
        <span className="font-mono text-muted-foreground">{change.path}</span>
        <div className="mt-0.5 flex flex-wrap items-center gap-2">
          {change.from_value !== null && (
            <span className={`font-mono ${change.change_type === "removed" ? style.text : "text-muted-foreground line-through"}`}>
              {change.from_value}
            </span>
          )}
          {change.change_type === "changed" && (
            <ArrowLeftRight className="h-3 w-3 text-muted-foreground" />
          )}
          {change.to_value !== null && (
            <span className={`font-mono ${change.change_type === "added" || change.change_type === "changed" ? style.text : ""}`}>
              {change.to_value}
            </span>
          )}
        </div>
      </div>
      <span className={`shrink-0 text-[10px] font-medium ${style.text}`}>{style.label}</span>
    </div>
  );
}

// ── Section accordion ─────────────────────────────────────────────────────────

function SectionPanel({ section }: { section: SectionDiff }) {
  const [open, setOpen] = useState(section.has_changes);

  const badgeColor = section.has_changes
    ? "bg-amber-500/15 text-amber-700 border-amber-200"
    : "bg-emerald-500/15 text-emerald-700 border-emerald-200";

  const sectionIcons: Record<string, React.ReactNode> = {
    status:  <CheckCircle2 className="h-4 w-4 text-muted-foreground" />,
    timing:  <Clock className="h-4 w-4 text-muted-foreground" />,
    headers: <ArrowLeftRight className="h-4 w-4 text-muted-foreground" />,
    body:    <Zap className="h-4 w-4 text-muted-foreground" />,
    schema:  <Zap className="h-4 w-4 text-muted-foreground" />,
  };

  return (
    <div className="rounded-lg border overflow-hidden">
      <button
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/30 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        {sectionIcons[section.section] ?? null}
        <span className="flex-1 text-sm font-medium">{section.label}</span>
        <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${badgeColor}`}>
          {section.has_changes ? `${section.changes.length} change${section.changes.length !== 1 ? "s" : ""}` : "No changes"}
        </span>
        <span className="text-xs text-muted-foreground">{section.summary}</span>
        {open
          ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
          : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
        }
      </button>

      {open && (
        <div className="border-t bg-muted/10 p-4 space-y-1.5">
          {section.changes.length === 0 ? (
            <p className="text-xs text-muted-foreground italic">No changes in this section.</p>
          ) : (
            section.changes.map((c, i) => <ChangeRow key={i} change={c} />)
          )}
        </div>
      )}
    </div>
  );
}

// ── Snapshot header card ──────────────────────────────────────────────────────

function SnapshotCard({ snap, label }: { snap: ResultSnapshot; label: string }) {
  const statusColor = snap.run_status === "passed"
    ? "text-emerald-600"
    : snap.run_status === "failed"
      ? "text-red-600"
      : "text-orange-600";

  return (
    <div className="rounded-lg border bg-card p-4 space-y-2">
      <div className="flex items-center justify-between">
        <Badge variant="secondary" className="text-xs">{label}</Badge>
        <span className={`text-sm font-semibold capitalize ${statusColor}`}>
          {snap.run_status}
        </span>
      </div>
      <div className="space-y-1 text-xs text-muted-foreground">
        <p>
          <span className="font-mono font-semibold text-foreground mr-1">{snap.request_method}</span>
          <span className="font-mono truncate">{snap.request_url}</span>
        </p>
        <p>HTTP {snap.status_code ?? "—"} · {fmtMs(snap.response_time_ms)}</p>
        <p>{fmtDate(snap.executed_at)}</p>
      </div>
    </div>
  );
}

// ── Summary badge ─────────────────────────────────────────────────────────────

function DiffSummary({ diff }: { diff: ResultDiff }) {
  if (diff.is_identical) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-500/8 px-4 py-3">
        <CheckCircle2 className="h-4 w-4 text-emerald-600" />
        <span className="text-sm font-medium text-emerald-700">Responses are identical</span>
      </div>
    );
  }

  const sections = diff.sections.filter(s => s.has_changes);
  return (
    <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-500/8 px-4 py-3">
      <ArrowLeftRight className="h-4 w-4 text-amber-600" />
      <span className="text-sm font-medium text-amber-700">
        {diff.total_changes} change{diff.total_changes !== 1 ? "s" : ""} across{" "}
        {sections.length} section{sections.length !== 1 ? "s" : ""}:{" "}
        {sections.map(s => s.label).join(", ")}
      </span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface DiffViewerProps {
  diff: ResultDiff;
}

export function DiffViewer({ diff }: DiffViewerProps) {
  return (
    <div className="space-y-4">
      {/* Snapshot headers */}
      <div className="grid grid-cols-2 gap-3">
        <SnapshotCard snap={diff.a} label="Baseline (A)" />
        <SnapshotCard snap={diff.b} label="Compared (B)" />
      </div>

      {/* Summary */}
      <DiffSummary diff={diff} />

      {/* Section accordions */}
      <div className="space-y-2">
        {diff.sections.map(s => (
          <SectionPanel key={s.section} section={s} />
        ))}
      </div>
    </div>
  );
}
