"use client";

import { useMemo, useState } from "react";
import { Search, Copy, Check, ChevronDown, ChevronUp, X, Download } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";

// ── Header categorisation ──────────────────────────────────────────────────────

const CATEGORIES: Record<string, { label: string; keys: string[]; color: string }> = {
  content: {
    label: "Content",
    color: "bg-blue-500/10 text-blue-700 border-blue-200",
    keys: [
      "content-type", "content-length", "content-encoding",
      "content-language", "content-disposition", "content-range",
      "transfer-encoding",
    ],
  },
  caching: {
    label: "Caching",
    color: "bg-amber-500/10 text-amber-700 border-amber-200",
    keys: [
      "cache-control", "etag", "last-modified", "expires",
      "age", "vary", "pragma", "if-none-match", "if-modified-since",
    ],
  },
  security: {
    label: "Security",
    color: "bg-red-500/10 text-red-700 border-red-200",
    keys: [
      "strict-transport-security", "x-content-type-options", "x-frame-options",
      "x-xss-protection", "content-security-policy", "referrer-policy",
      "permissions-policy", "cross-origin-embedder-policy",
      "cross-origin-opener-policy", "cross-origin-resource-policy",
    ],
  },
  cors: {
    label: "CORS",
    color: "bg-violet-500/10 text-violet-700 border-violet-200",
    keys: [
      "access-control-allow-origin", "access-control-allow-methods",
      "access-control-allow-headers", "access-control-allow-credentials",
      "access-control-max-age", "access-control-expose-headers",
    ],
  },
  auth: {
    label: "Auth",
    color: "bg-orange-500/10 text-orange-700 border-orange-200",
    keys: ["www-authenticate", "set-cookie", "authorization", "proxy-authenticate"],
  },
  server: {
    label: "Server",
    color: "bg-zinc-500/10 text-zinc-600 border-zinc-200",
    keys: [
      "server", "x-powered-by", "date", "connection",
      "keep-alive", "x-request-id", "x-trace-id", "x-correlation-id",
      "request-id", "cf-ray", "x-amzn-requestid",
    ],
  },
};

function categorise(key: string): string {
  const lk = key.toLowerCase();
  for (const [cat, { keys }] of Object.entries(CATEGORIES)) {
    if (keys.includes(lk)) return cat;
  }
  return "custom";
}

const CUSTOM_COLOR = "bg-emerald-500/10 text-emerald-700 border-emerald-200";
const CUSTOM_LABEL = "Custom";

function getCategoryStyle(cat: string) {
  return CATEGORIES[cat]
    ? { label: CATEGORIES[cat].label, color: CATEGORIES[cat].color }
    : { label: CUSTOM_LABEL, color: CUSTOM_COLOR };
}

// ── Copy helpers ───────────────────────────────────────────────────────────────

async function copyText(text: string, label: string) {
  await navigator.clipboard.writeText(text);
  toast.success(`${label} copied`);
}

function headersToJson(headers: Record<string, string>): string {
  return JSON.stringify(headers, null, 2);
}

function headersToCurl(headers: Record<string, string>): string {
  return Object.entries(headers)
    .map(([k, v]) => `-H "${k}: ${v}"`)
    .join(" \\\n  ");
}

// ── Category badge ─────────────────────────────────────────────────────────────

function CategoryBadge({ category }: { category: string }) {
  const { label, color } = getCategoryStyle(category);
  return (
    <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold ${color}`}>
      {label}
    </span>
  );
}

// ── Single header row ──────────────────────────────────────────────────────────

const VALUE_TRUNCATE_LENGTH = 120;

function HeaderRow({ headerKey, value, query }: {
  headerKey: string;
  value: string;
  query: string;
}) {
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const isLong    = value.length > VALUE_TRUNCATE_LENGTH;
  const displayed = isLong && !expanded ? value.slice(0, VALUE_TRUNCATE_LENGTH) + "…" : value;
  const category  = categorise(headerKey);

  const handleCopy = async () => {
    await copyText(value, headerKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Highlight matching query
  const highlight = (text: string) => {
    if (!query) return text;
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const parts = text.split(new RegExp(`(${escaped})`, "gi"));
    return parts.map((p, i) =>
      p.toLowerCase() === query.toLowerCase()
        ? <mark key={i} className="bg-yellow-200 text-yellow-900 rounded-sm px-0.5">{p}</mark>
        : p
    );
  };

  return (
    <div className="group flex items-start gap-3 px-3 py-2.5 border-b last:border-0 hover:bg-muted/20 transition-colors">
      {/* Category badge */}
      <div className="mt-0.5">
        <CategoryBadge category={category} />
      </div>

      {/* Key */}
      <div className="w-56 shrink-0">
        <span className="font-mono text-xs text-muted-foreground select-all">
          {highlight(headerKey)}
        </span>
      </div>

      {/* Value */}
      <div className="flex-1 min-w-0">
        <p className={`font-mono text-xs break-all ${category === "security" ? "text-red-700" : "text-foreground"}`}>
          {highlight(displayed)}
        </p>
        {isLong && (
          <button
            className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
            onClick={() => setExpanded(e => !e)}
          >
            {expanded
              ? <><ChevronUp className="h-3 w-3" /> Show less</>
              : <><ChevronDown className="h-3 w-3" /> Show all ({value.length} chars)</>}
          </button>
        )}
      </div>

      {/* Copy button */}
      <button
        className="shrink-0 rounded p-1 text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-foreground hover:bg-muted transition-all"
        onClick={handleCopy}
        title="Copy value"
      >
        {copied
          ? <Check className="h-3.5 w-3.5 text-emerald-500" />
          : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

// ── Export dropdown ────────────────────────────────────────────────────────────

function ExportMenu({ headers }: { headers: Record<string, string> }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        className="flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium hover:bg-muted transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <Download className="h-3.5 w-3.5" />
        Export
        <ChevronDown className="h-3 w-3" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 w-44 rounded-lg border bg-background shadow-lg py-1 text-xs">
            <button className="w-full px-3 py-2 text-left hover:bg-muted transition-colors"
              onClick={() => { copyText(headersToJson(headers), "Headers JSON"); setOpen(false); }}>
              Copy as JSON
            </button>
            <button className="w-full px-3 py-2 text-left hover:bg-muted transition-colors"
              onClick={() => { copyText(headersToCurl(headers), "curl -H flags"); setOpen(false); }}>
              Copy as curl -H flags
            </button>
            <button className="w-full px-3 py-2 text-left hover:bg-muted transition-colors"
              onClick={() => {
                const raw = Object.entries(headers).map(([k, v]) => `${k}: ${v}`).join("\n");
                copyText(raw, "Raw headers");
                setOpen(false);
              }}>
              Copy as raw text
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ── Category summary bar ───────────────────────────────────────────────────────

function CategorySummary({ headers }: { headers: Record<string, string> }) {
  const counts: Record<string, number> = {};
  for (const key of Object.keys(headers)) {
    const cat = categorise(key);
    counts[cat] = (counts[cat] ?? 0) + 1;
  }

  const entries = Object.entries(counts).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5 px-3 py-2 border-b bg-muted/20">
      {entries.map(([cat, count]) => {
        const { label, color } = getCategoryStyle(cat);
        return (
          <span key={cat} className={`rounded border px-2 py-0.5 text-[10px] font-semibold ${color}`}>
            {label} {count}
          </span>
        );
      })}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

interface ResponseHeadersViewerProps {
  headers: Record<string, string>;
  /** Max height of the scrollable list in px — defaults to 400 */
  maxHeight?: number;
}

export function ResponseHeadersViewer({
  headers,
  maxHeight = 400,
}: ResponseHeadersViewerProps) {
  const [query, setQuery] = useState("");

  const allEntries = useMemo(
    () => Object.entries(headers).sort(([a], [b]) => a.localeCompare(b)),
    [headers]
  );

  const filtered = useMemo(() => {
    if (!query.trim()) return allEntries;
    const q = query.toLowerCase();
    return allEntries.filter(
      ([k, v]) => k.toLowerCase().includes(q) || v.toLowerCase().includes(q)
    );
  }, [allEntries, query]);

  const total    = allEntries.length;
  const showing  = filtered.length;
  const isEmpty  = total === 0;
  const noMatch  = !isEmpty && showing === 0;

  if (isEmpty) {
    return (
      <p className="px-3 py-6 text-center text-xs text-muted-foreground italic">
        No response headers captured
      </p>
    );
  }

  return (
    <div className="flex flex-col rounded-lg border overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b bg-muted/10">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            className="h-7 pl-7 text-xs"
            placeholder="Search headers…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          {query && (
            <button
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onClick={() => setQuery("")}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Count */}
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
          {query ? `${showing}/${total}` : total} header{total !== 1 ? "s" : ""}
        </span>

        <ExportMenu headers={headers} />
      </div>

      {/* Category pills summary */}
      {!query && <CategorySummary headers={headers} />}

      {/* Column headers */}
      <div className="flex items-center gap-3 border-b bg-muted/30 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        <span className="w-14 shrink-0">Type</span>
        <span className="w-56 shrink-0">Name</span>
        <span className="flex-1">Value</span>
        <span className="w-6 shrink-0" />
      </div>

      {/* Rows */}
      <div className="overflow-auto" style={{ maxHeight }}>
        {noMatch ? (
          <div className="flex flex-col items-center justify-center gap-2 py-8 text-muted-foreground">
            <Search className="h-6 w-6 opacity-30" />
            <p className="text-xs">No headers match "{query}"</p>
          </div>
        ) : (
          filtered.map(([k, v]) => (
            <HeaderRow key={k} headerKey={k} value={v} query={query} />
          ))
        )}
      </div>
    </div>
  );
}
