"use client";

import { useEffect, useRef, useState } from "react";
import {
  Sparkles, RefreshCw, Copy, Check, ChevronDown, ChevronRight,
  AlertTriangle, ListChecks, Wrench, Loader2, Frown,
} from "lucide-react";
import { toast } from "sonner";
import { runnerService } from "@/lib/services/runner.service";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { AiAnalysis, ConfidenceLevel, DebuggingStep, LikelyFix, RootCause } from "@/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)  return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function modelName(model: string): string {
  return model.replace("gpt-", "GPT-").replace("-mini", " mini").replace("-4o", "-4o");
}

// ── Confidence badge ──────────────────────────────────────────────────────────

const CONF_STYLES: Record<ConfidenceLevel, { dot: string; text: string; badge: string }> = {
  high:   { dot: "bg-red-500",    text: "text-red-600",    badge: "bg-red-500/10 text-red-600 border-red-200" },
  medium: { dot: "bg-amber-500",  text: "text-amber-600",  badge: "bg-amber-500/10 text-amber-600 border-amber-200" },
  low:    { dot: "bg-zinc-400",   text: "text-zinc-500",   badge: "bg-zinc-500/10 text-zinc-500 border-zinc-200" },
};

function ConfidenceBadge({ level }: { level: ConfidenceLevel }) {
  const s = CONF_STYLES[level];
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${s.badge}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {level}
    </span>
  );
}

// ── Collapsible section ───────────────────────────────────────────────────────

function Section({
  icon: Icon, title, count, children, defaultOpen = true,
}: {
  icon: React.ElementType; title: string; count?: number;
  children: React.ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t first:border-t-0">
      <button
        className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-muted/30 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground flex-1">
          {title}
        </span>
        {count !== undefined && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
            {count}
          </span>
        )}
        {open
          ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

// ── Root causes ───────────────────────────────────────────────────────────────

function RootCauseItem({ cause, index }: { cause: RootCause; index: number }) {
  return (
    <div className="flex gap-3 py-2.5 border-b last:border-0">
      <ConfidenceBadge level={cause.confidence} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{cause.title}</p>
        <p className="mt-0.5 text-xs text-muted-foreground leading-relaxed">{cause.description}</p>
      </div>
    </div>
  );
}

// ── Debugging steps ───────────────────────────────────────────────────────────

function StepItem({ step }: { step: DebuggingStep }) {
  return (
    <div className="flex gap-3 py-2.5 border-b last:border-0">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-bold text-muted-foreground mt-0.5">
        {step.step}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-medium">{step.action}</p>
        <p className="mt-0.5 text-xs text-muted-foreground leading-relaxed">{step.detail}</p>
      </div>
    </div>
  );
}

// ── Likely fix ────────────────────────────────────────────────────────────────

function FixItem({ fix }: { fix: LikelyFix }) {
  const [copied, setCopied] = useState(false);

  const copyCode = async () => {
    if (!fix.code) return;
    await navigator.clipboard.writeText(fix.code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="py-2.5 border-b last:border-0 space-y-2">
      <div>
        <p className="text-sm font-medium">{fix.title}</p>
        <p className="mt-0.5 text-xs text-muted-foreground leading-relaxed">{fix.description}</p>
      </div>
      {fix.code && (
        <div className="relative group rounded-lg overflow-hidden bg-zinc-950 border border-zinc-800">
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-zinc-800">
            <span className="text-[10px] font-mono text-zinc-500">code</span>
            <button
              className="flex items-center gap-1 text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
              onClick={copyCode}
            >
              {copied
                ? <><Check className="h-3 w-3 text-emerald-400" /> Copied!</>
                : <><Copy className="h-3 w-3" /> Copy</>}
            </button>
          </div>
          <pre className="overflow-x-auto px-3 py-3 text-xs text-zinc-100 font-mono leading-relaxed whitespace-pre">
            {fix.code}
          </pre>
        </div>
      )}
    </div>
  );
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

function AnalysisSkeleton() {
  return (
    <div className="space-y-4 p-4">
      <div className="space-y-2">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-5/6" />
      </div>
      <div className="space-y-2 pt-2">
        <Skeleton className="h-3 w-1/3" />
        <div className="space-y-1.5">
          <Skeleton className="h-12 w-full rounded-lg" />
          <Skeleton className="h-12 w-full rounded-lg" />
        </div>
      </div>
      <div className="space-y-2 pt-1">
        <Skeleton className="h-3 w-1/3" />
        <Skeleton className="h-20 w-full rounded-lg" />
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface AIAnalysisPanelProps {
  resultId: string;
  resultStatus: string;
}

export function AIAnalysisPanel({ resultId, resultStatus }: AIAnalysisPanelProps) {
  const [analysis, setAnalysis] = useState<AiAnalysis | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error" | "done">("idle");
  const [copying, setCopying] = useState(false);
  const fetchedRef = useRef(false);

  const canAnalyze = resultStatus === "failed" || resultStatus === "error";

  // Try to load existing analysis on mount
  useEffect(() => {
    if (!canAnalyze || fetchedRef.current) return;
    fetchedRef.current = true;
    setState("loading");
    runnerService.getAnalysis(resultId)
      .then(r => { setAnalysis(r.data); setState("done"); })
      .catch(err => {
        // 404 = no analysis yet, stay idle
        if (err?.response?.status === 404) setState("idle");
        else setState("error");
      });
  }, [resultId, canAnalyze]);

  const generate = async (force = false) => {
    setState("loading");
    try {
      const r = await runnerService.analyzeResult(resultId, force);
      setAnalysis(r.data);
      setState("done");
    } catch (err: any) {
      const msg = err?.response?.data?.detail ?? "AI analysis failed";
      toast.error(msg);
      setState("error");
    }
  };

  const copyAll = async () => {
    if (!analysis) return;
    setCopying(true);
    const text = [
      `## AI Analysis`,
      ``,
      `**Summary:** ${analysis.summary}`,
      ``,
      `### Root Causes`,
      ...analysis.root_causes.map(c => `- [${c.confidence.toUpperCase()}] **${c.title}**: ${c.description}`),
      ``,
      `### Debugging Steps`,
      ...analysis.debugging_steps.map(s => `${s.step}. **${s.action}**: ${s.detail}`),
      ``,
      `### Likely Fixes`,
      ...analysis.likely_fixes.map(f => `- **${f.title}**: ${f.description}${f.code ? `\n\`\`\`\n${f.code}\n\`\`\`` : ""}`),
    ].join("\n");

    await navigator.clipboard.writeText(text);
    toast.success("Analysis copied to clipboard");
    setTimeout(() => setCopying(false), 2000);
  };

  // Not a failed/error result
  if (!canAnalyze) {
    return (
      <div className="flex flex-col items-center justify-center py-8 gap-2 text-muted-foreground">
        <Sparkles className="h-7 w-7 opacity-30" />
        <p className="text-xs">AI analysis is only available for failed or errored requests.</p>
      </div>
    );
  }

  // Idle — no analysis generated yet
  if (state === "idle") {
    return (
      <div className="flex flex-col items-center justify-center py-10 gap-4 text-center px-6">
        <div className="rounded-full bg-violet-500/10 p-4">
          <Sparkles className="h-7 w-7 text-violet-500" />
        </div>
        <div>
          <p className="font-semibold text-sm">AI Failure Analysis</p>
          <p className="text-xs text-muted-foreground mt-1 max-w-xs leading-relaxed">
            GPT-4o-mini will analyse the request, response, and assertion failures
            to give you probable causes, debugging steps, and likely fixes.
          </p>
        </div>
        <Button size="sm" className="gap-2" onClick={() => generate()}>
          <Sparkles className="h-3.5 w-3.5" />
          Analyse failure
        </Button>
      </div>
    );
  }

  // Loading
  if (state === "loading") {
    return (
      <div>
        <div className="flex items-center gap-2 px-4 py-3 border-b">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-500" />
          <span className="text-xs text-muted-foreground">GPT-4o-mini is analysing the failure…</span>
        </div>
        <AnalysisSkeleton />
      </div>
    );
  }

  // Error
  if (state === "error") {
    return (
      <div className="flex flex-col items-center justify-center py-10 gap-4 text-center px-6">
        <div className="rounded-full bg-red-500/10 p-4">
          <Frown className="h-7 w-7 text-red-500" />
        </div>
        <div>
          <p className="font-semibold text-sm">Analysis failed</p>
          <p className="text-xs text-muted-foreground mt-1">
            Could not complete the AI analysis. Check that OPENAI_API_KEY is set.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => generate()}>Retry</Button>
      </div>
    );
  }

  // Done — show analysis
  return (
    <div className="rounded-lg border overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-violet-500/5 border-b">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-violet-500" />
          <span className="text-sm font-semibold">AI Analysis</span>
          <span className="text-xs text-muted-foreground">
            {modelName(analysis!.model)} · {analysis!.prompt_tokens + analysis!.completion_tokens} tokens · {timeAgo(analysis!.created_at)}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Button variant="ghost" size="sm" className="h-7 gap-1.5 text-xs" onClick={copyAll}>
            {copying ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
            {copying ? "Copied" : "Copy"}
          </Button>
          <Button variant="ghost" size="sm" className="h-7 gap-1.5 text-xs" onClick={() => generate(true)}>
            <RefreshCw className="h-3.5 w-3.5" />
            Regenerate
          </Button>
        </div>
      </div>

      {/* Summary */}
      <div className="px-4 py-4 border-b bg-muted/10">
        <div className="flex items-start gap-2.5">
          <div className="mt-0.5 rounded-full bg-violet-500/10 p-1.5">
            <Sparkles className="h-3 w-3 text-violet-500" />
          </div>
          <p className="text-sm leading-relaxed">{analysis!.summary}</p>
        </div>
      </div>

      {/* Root causes */}
      {analysis!.root_causes.length > 0 && (
        <Section icon={AlertTriangle} title="Probable Causes" count={analysis!.root_causes.length}>
          <div className="divide-y divide-border/50">
            {analysis!.root_causes.map((c, i) => <RootCauseItem key={i} cause={c} index={i} />)}
          </div>
        </Section>
      )}

      {/* Debugging steps */}
      {analysis!.debugging_steps.length > 0 && (
        <Section icon={ListChecks} title="Debugging Steps" count={analysis!.debugging_steps.length}>
          <div className="divide-y divide-border/50">
            {analysis!.debugging_steps.map((s, i) => <StepItem key={i} step={s} />)}
          </div>
        </Section>
      )}

      {/* Likely fixes */}
      {analysis!.likely_fixes.length > 0 && (
        <Section icon={Wrench} title="Suggested Fixes" count={analysis!.likely_fixes.length}>
          <div className="divide-y divide-border/50">
            {analysis!.likely_fixes.map((f, i) => <FixItem key={i} fix={f} />)}
          </div>
        </Section>
      )}
    </div>
  );
}
