"use client";

import { useState } from "react";
import { X, ChevronDown } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ActiveFilters {
  methods: string[];
  statusRanges: string[];   // "2xx" | "3xx" | "4xx" | "5xx"
  statuses: string[];       // "passed" | "failed" | "error" | "running" | "pending"
  startedAfter: string;
  startedBefore: string;
  triggerType: string;
}

export const EMPTY_FILTERS: ActiveFilters = {
  methods: [], statusRanges: [], statuses: [],
  startedAfter: "", startedBefore: "", triggerType: "",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];

const METHOD_COLORS: Record<string, { bg: string; text: string }> = {
  GET:    { bg: "bg-emerald-500/10", text: "text-emerald-700" },
  POST:   { bg: "bg-blue-500/10",    text: "text-blue-700"    },
  PUT:    { bg: "bg-amber-500/10",   text: "text-amber-700"   },
  PATCH:  { bg: "bg-purple-500/10",  text: "text-purple-700"  },
  DELETE: { bg: "bg-red-500/10",     text: "text-red-700"     },
};

const STATUS_RANGES = [
  { label: "2xx",  value: "2xx", cls: "text-emerald-600 bg-emerald-500/10" },
  { label: "3xx",  value: "3xx", cls: "text-blue-600 bg-blue-500/10"       },
  { label: "4xx",  value: "4xx", cls: "text-amber-600 bg-amber-500/10"     },
  { label: "5xx",  value: "5xx", cls: "text-red-600 bg-red-500/10"         },
];

const RUN_STATUSES = [
  { label: "Passed",  value: "passed",  cls: "text-emerald-600 bg-emerald-500/10" },
  { label: "Failed",  value: "failed",  cls: "text-red-600 bg-red-500/10"         },
  { label: "Error",   value: "error",   cls: "text-orange-600 bg-orange-500/10"   },
  { label: "Pending", value: "pending", cls: "text-zinc-500 bg-zinc-500/10"       },
];

function countActive(f: ActiveFilters): number {
  return f.methods.length + f.statusRanges.length + f.statuses.length
    + (f.startedAfter ? 1 : 0) + (f.startedBefore ? 1 : 0)
    + (f.triggerType ? 1 : 0);
}

// ── Toggle chip ───────────────────────────────────────────────────────────────

function ToggleChip({ label, active, className, onClick }: {
  label: string; active: boolean; className?: string; onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`rounded-full border px-2.5 py-0.5 text-xs font-medium transition-all ${
        active ? `${className} border-transparent shadow-sm scale-105` : "border-muted-foreground/20 text-muted-foreground hover:border-muted-foreground/40"
      }`}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

// ── Filter row ────────────────────────────────────────────────────────────────

function FilterRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <span className="w-24 shrink-0 pt-0.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  );
}

// ── Collapsible filter panel ──────────────────────────────────────────────────

interface FilterPanelProps {
  filters: ActiveFilters;
  onChange: (f: ActiveFilters) => void;
  /** Which filter sections to show */
  show?: {
    methods?: boolean;
    statusRanges?: boolean;   // HTTP status code ranges (for request results)
    runStatuses?: boolean;    // run pass/fail status (for history)
    dateRange?: boolean;
    triggerType?: boolean;
  };
  className?: string;
}

export function FilterPanel({
  filters, onChange,
  show = { methods: true, runStatuses: true, dateRange: true, triggerType: true },
  className,
}: FilterPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const activeCount = countActive(filters);

  const toggle = <T extends string>(arr: T[], val: T): T[] =>
    arr.includes(val) ? arr.filter(v => v !== val) : [...arr, val];

  const clear = () => onChange(EMPTY_FILTERS);

  return (
    <div className={className}>
      {/* Collapsed state — just a bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          className="flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium hover:bg-muted transition-colors"
          onClick={() => setExpanded(e => !e)}
        >
          <span>Filters</span>
          {activeCount > 0 && (
            <span className="rounded-full bg-primary text-primary-foreground px-1.5 text-[10px] font-semibold">
              {activeCount}
            </span>
          )}
          <ChevronDown className={`h-3 w-3 transition-transform ${expanded ? "rotate-180" : ""}`} />
        </button>

        {/* Active filter chips (always visible) */}
        {filters.methods.map(m => {
          const c = METHOD_COLORS[m];
          return (
            <span key={m} className={`flex items-center gap-1 rounded-full border-0 px-2 py-0.5 text-xs font-mono font-semibold ${c.bg} ${c.text}`}>
              {m}
              <button onClick={() => onChange({ ...filters, methods: filters.methods.filter(x => x !== m) })}>
                <X className="h-3 w-3" />
              </button>
            </span>
          );
        })}
        {filters.statuses.map(s => (
          <span key={s} className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs capitalize">
            {s}
            <button onClick={() => onChange({ ...filters, statuses: filters.statuses.filter(x => x !== s) })}>
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        {filters.triggerType && (
          <span className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs capitalize">
            {filters.triggerType}
            <button onClick={() => onChange({ ...filters, triggerType: "" })}>
              <X className="h-3 w-3" />
            </button>
          </span>
        )}
        {(filters.startedAfter || filters.startedBefore) && (
          <span className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs">
            Date range
            <button onClick={() => onChange({ ...filters, startedAfter: "", startedBefore: "" })}>
              <X className="h-3 w-3" />
            </button>
          </span>
        )}
        {activeCount > 0 && (
          <button className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2" onClick={clear}>
            Clear all
          </button>
        )}
      </div>

      {/* Expanded panel */}
      {expanded && (
        <div className="mt-3 rounded-lg border bg-card p-4 space-y-4">
          {show.methods && (
            <FilterRow label="Method">
              {HTTP_METHODS.map(m => {
                const c = METHOD_COLORS[m];
                return (
                  <ToggleChip key={m} label={m}
                    active={filters.methods.includes(m)}
                    className={`${c.bg} ${c.text} font-mono`}
                    onClick={() => onChange({ ...filters, methods: toggle(filters.methods, m) })}
                  />
                );
              })}
            </FilterRow>
          )}

          {show.statusRanges && (
            <FilterRow label="HTTP status">
              {STATUS_RANGES.map(s => (
                <ToggleChip key={s.value} label={s.label}
                  active={filters.statusRanges.includes(s.value)}
                  className={s.cls}
                  onClick={() => onChange({ ...filters, statusRanges: toggle(filters.statusRanges, s.value) })}
                />
              ))}
            </FilterRow>
          )}

          {show.runStatuses && (
            <FilterRow label="Run status">
              {RUN_STATUSES.map(s => (
                <ToggleChip key={s.value} label={s.label}
                  active={filters.statuses.includes(s.value)}
                  className={s.cls}
                  onClick={() => onChange({ ...filters, statuses: toggle(filters.statuses, s.value) })}
                />
              ))}
            </FilterRow>
          )}

          {show.triggerType && (
            <FilterRow label="Trigger">
              {["manual", "scheduled", "api"].map(t => (
                <ToggleChip key={t} label={t}
                  active={filters.triggerType === t}
                  className="bg-muted text-foreground capitalize"
                  onClick={() => onChange({ ...filters, triggerType: filters.triggerType === t ? "" : t })}
                />
              ))}
            </FilterRow>
          )}

          {show.dateRange && (
            <FilterRow label="Date range">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-muted-foreground">From</span>
                  <Input type="datetime-local" className="h-7 w-44 text-xs"
                    value={filters.startedAfter.slice(0, 16)}
                    onChange={e => onChange({ ...filters, startedAfter: e.target.value ? e.target.value + ":00Z" : "" })} />
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-muted-foreground">to</span>
                  <Input type="datetime-local" className="h-7 w-44 text-xs"
                    value={filters.startedBefore.slice(0, 16)}
                    onChange={e => onChange({ ...filters, startedBefore: e.target.value ? e.target.value + ":00Z" : "" })} />
                </div>
              </div>
            </FilterRow>
          )}

          <div className="flex justify-end border-t pt-3">
            <Button variant="ghost" size="sm" className="text-xs h-7" onClick={() => { clear(); setExpanded(false); }}>
              Reset all filters
            </Button>
            <Button size="sm" className="text-xs h-7 ml-2" onClick={() => setExpanded(false)}>
              Apply
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Utility: apply filters to history page params ─────────────────────────────

export function filtersToHistoryParams(f: ActiveFilters) {
  const params: Record<string, string | undefined> = {};
  if (f.statuses.length === 1) params.status = f.statuses[0];
  if (f.triggerType) params.trigger_type = f.triggerType;
  if (f.startedAfter) params.started_after = f.startedAfter;
  if (f.startedBefore) params.started_before = f.startedBefore;
  return params;
}
