"use client";

import { useMemo, useState } from "react";
import { Eye, EyeOff, Info, ShieldCheck, Key, User, Lock, Minus } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { AuthType } from "@/types";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AuthConfig {
  type: AuthType;
  // bearer
  token?: string;
  // basic
  username?: string;
  password?: string;
  // api_key
  header?: string;
  value?: string;
}

// ── Auth type meta ────────────────────────────────────────────────────────────

const AUTH_TYPES: { value: AuthType; label: string; icon: React.ElementType; description: string }[] = [
  { value: "none",    label: "None",         icon: Minus,       description: "No authentication" },
  { value: "bearer",  label: "Bearer Token", icon: ShieldCheck, description: "OAuth 2.0 / JWT token sent as Authorization header" },
  { value: "basic",   label: "Basic Auth",   icon: User,        description: "RFC 7617 — username:password Base64 encoded" },
  { value: "api_key", label: "API Key",       icon: Key,         description: "Custom key/value injected as a request header" },
];

// ── Preview computation ───────────────────────────────────────────────────────

function computePreview(auth: AuthConfig): { header: string; value: string } | null {
  if (auth.type === "none") return null;

  if (auth.type === "bearer") {
    const token = auth.token?.trim() || "{{env.TOKEN}}";
    return { header: "Authorization", value: `Bearer ${token}` };
  }

  if (auth.type === "basic") {
    const u = auth.username?.trim() || "";
    const p = auth.password?.trim() || "";
    if (!u && !p) return { header: "Authorization", value: "Basic <username:password>" };
    try {
      const encoded = btoa(`${u}:${p}`);
      return { header: "Authorization", value: `Basic ${encoded}` };
    } catch {
      return { header: "Authorization", value: "Basic <encoding error>" };
    }
  }

  if (auth.type === "api_key") {
    const hdr = auth.header?.trim() || "X-API-Key";
    const val = auth.value?.trim() || "{{env.API_KEY}}";
    return { header: hdr, value: val };
  }

  return null;
}

// ── Secret input with reveal toggle ──────────────────────────────────────────

function SecretInput({ label, value, onChange, placeholder, hint }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
}) {
  const [revealed, setRevealed] = useState(false);
  return (
    <div className="space-y-1.5">
      <Label className="text-xs font-medium">{label}</Label>
      <div className="relative">
        <Input
          type={revealed ? "text" : "password"}
          className="h-8 text-xs font-mono pr-9"
          placeholder={placeholder}
          value={value}
          onChange={e => onChange(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
        <button
          type="button"
          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
          onClick={() => setRevealed(r => !r)}
          tabIndex={-1}
          title={revealed ? "Hide" : "Show"}
        >
          {revealed ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
        </button>
      </div>
      {hint && (
        <p className="text-[11px] text-muted-foreground flex items-center gap-1">
          <Info className="h-3 w-3 shrink-0" />
          {hint}
        </p>
      )}
    </div>
  );
}

// ── Auth type selector ────────────────────────────────────────────────────────

function TypeSelector({ selected, onChange }: {
  selected: AuthType;
  onChange: (t: AuthType) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {AUTH_TYPES.map(t => {
        const Icon  = t.icon;
        const active = selected === t.value;
        return (
          <button
            key={t.value}
            type="button"
            className={`flex flex-col items-center gap-1.5 rounded-lg border p-3 text-xs transition-all ${
              active
                ? "border-primary bg-primary/5 text-primary shadow-sm"
                : "border-border bg-card text-muted-foreground hover:border-muted-foreground/40 hover:text-foreground"
            }`}
            onClick={() => onChange(t.value)}
          >
            <Icon className={`h-4 w-4 ${active ? "text-primary" : ""}`} />
            <span className="font-medium whitespace-nowrap">{t.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// ── Config forms per auth type ────────────────────────────────────────────────

function BearerForm({ config, onChange }: {
  config: AuthConfig;
  onChange: (patch: Partial<AuthConfig>) => void;
}) {
  return (
    <SecretInput
      label="Token"
      value={config.token ?? ""}
      onChange={token => onChange({ token })}
      placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9… or {{env.TOKEN}}"
      hint="Use {{env.TOKEN}} to reference an environment variable"
    />
  );
}

function BasicForm({ config, onChange }: {
  config: AuthConfig;
  onChange: (patch: Partial<AuthConfig>) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="space-y-1.5">
        <Label className="text-xs font-medium">Username</Label>
        <Input
          className="h-8 text-xs"
          placeholder="admin or {{env.USERNAME}}"
          value={config.username ?? ""}
          onChange={e => onChange({ username: e.target.value })}
          autoComplete="off"
        />
      </div>
      <SecretInput
        label="Password"
        value={config.password ?? ""}
        onChange={password => onChange({ password })}
        placeholder="password or {{env.PASSWORD}}"
        hint="Use {{env.PASSWORD}} to keep credentials out of the request"
      />
    </div>
  );
}

function ApiKeyForm({ config, onChange }: {
  config: AuthConfig;
  onChange: (patch: Partial<AuthConfig>) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="space-y-1.5">
        <Label className="text-xs font-medium">Header name</Label>
        <Input
          className="h-8 text-xs font-mono"
          placeholder="X-API-Key"
          value={config.header ?? ""}
          onChange={e => onChange({ header: e.target.value })}
          autoComplete="off"
          spellCheck={false}
        />
        <p className="text-[11px] text-muted-foreground">
          Common: X-API-Key, Api-Key, X-Auth-Token
        </p>
      </div>
      <SecretInput
        label="Value"
        value={config.value ?? ""}
        onChange={value => onChange({ value })}
        placeholder="sk-… or {{env.API_KEY}}"
        hint="Use {{env.API_KEY}} to reference an environment variable"
      />
    </div>
  );
}

// ── Request preview card ──────────────────────────────────────────────────────

function RequestPreview({ auth }: { auth: AuthConfig }) {
  const preview = computePreview(auth);
  if (!preview) return null;

  const isTemplate = preview.value.includes("{{");

  return (
    <div className="rounded-lg border bg-muted/30 overflow-hidden">
      <div className="flex items-center gap-2 border-b px-3 py-2 bg-muted/40">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Generated request header
        </span>
        {isTemplate && (
          <span className="ml-auto text-[10px] text-amber-600 bg-amber-500/10 rounded px-1.5 py-0.5 font-medium">
            Contains template variable
          </span>
        )}
      </div>
      <div className="px-3 py-2.5 font-mono text-xs">
        <span className="text-blue-500">{preview.header}</span>
        <span className="text-muted-foreground">: </span>
        <span className={isTemplate ? "text-amber-600" : "text-emerald-600"}>
          {preview.value}
        </span>
      </div>
      {auth.type === "basic" && auth.username && auth.password && (
        <div className="px-3 pb-2 text-[11px] text-muted-foreground border-t bg-muted/20 pt-2">
          Decoded: <span className="font-mono">{auth.username}:{auth.password.replace(/./g, "•")}</span>
        </div>
      )}
    </div>
  );
}

// ── Validation hints ──────────────────────────────────────────────────────────

function ValidationHints({ auth }: { auth: AuthConfig }) {
  const issues: string[] = [];

  if (auth.type === "bearer" && !auth.token?.trim())
    issues.push("Token is empty — add a token or use {{env.TOKEN}}");

  if (auth.type === "basic") {
    if (!auth.username?.trim()) issues.push("Username is required");
    if (!auth.password?.trim()) issues.push("Password is empty");
  }

  if (auth.type === "api_key") {
    if (!auth.header?.trim()) issues.push("Header name is required (e.g. X-API-Key)");
    if (!auth.value?.trim())  issues.push("Value is empty — add a value or use {{env.API_KEY}}");
  }

  if (!issues.length) return null;

  return (
    <ul className="space-y-1">
      {issues.map((issue, i) => (
        <li key={i} className="flex items-center gap-1.5 text-[11px] text-amber-600">
          <span className="h-1 w-1 rounded-full bg-amber-500 shrink-0" />
          {issue}
        </li>
      ))}
    </ul>
  );
}

// ── Description strip ─────────────────────────────────────────────────────────

function TypeDescription({ type }: { type: AuthType }) {
  const meta = AUTH_TYPES.find(t => t.value === type);
  if (!meta || type === "none") return null;
  return (
    <p className="text-xs text-muted-foreground flex items-center gap-1.5">
      <Info className="h-3.5 w-3.5 shrink-0" />
      {meta.description}
    </p>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface AuthEditorProps {
  config: AuthConfig;
  onChange: (config: AuthConfig) => void;
}

export function AuthEditor({ config, onChange }: AuthEditorProps) {
  const handleTypeChange = (type: AuthType) => {
    // Preserve existing values when switching types; reset only on switch to none
    onChange({ ...config, type });
  };

  const handlePatch = (patch: Partial<AuthConfig>) => {
    onChange({ ...config, ...patch });
  };

  return (
    <div className="space-y-5">
      {/* Type selector */}
      <div className="space-y-2">
        <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Auth type</Label>
        <TypeSelector selected={config.type} onChange={handleTypeChange} />
      </div>

      {/* Description */}
      <TypeDescription type={config.type} />

      {/* None state */}
      {config.type === "none" && (
        <div className="flex flex-col items-center gap-2 py-6 text-center rounded-lg border border-dashed">
          <Lock className="h-7 w-7 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">No authentication</p>
          <p className="text-xs text-muted-foreground max-w-xs">
            Select an auth type above to add credentials to your requests.
            Credentials are interpolated at execution time — they are never
            stored in plain text in responses.
          </p>
        </div>
      )}

      {/* Config form */}
      {config.type === "bearer"  && <BearerForm  config={config} onChange={handlePatch} />}
      {config.type === "basic"   && <BasicForm   config={config} onChange={handlePatch} />}
      {config.type === "api_key" && <ApiKeyForm  config={config} onChange={handlePatch} />}

      {/* Validation hints */}
      {config.type !== "none" && <ValidationHints auth={config} />}

      {/* Request preview */}
      {config.type !== "none" && <RequestPreview auth={config} />}

      {/* Env var tip */}
      {config.type !== "none" && (
        <div className="rounded-lg bg-muted/30 border px-3 py-2.5 text-[11px] text-muted-foreground space-y-1">
          <p className="font-medium text-xs">💡 Using environment variables</p>
          <p>
            Reference variables with <code className="bg-muted px-1 rounded font-mono">{"{{env.VAR_NAME}}"}</code>.
            Set them in the <strong>Environments</strong> tab — they are substituted
            at execution time, so credentials never appear in saved request data.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Utilities for callers ─────────────────────────────────────────────────────

export function authConfigToApiPayload(config: AuthConfig): {
  auth_type: AuthType;
  auth_config: Record<string, string>;
} {
  const auth_config: Record<string, string> = {};

  if (config.type === "bearer" && config.token)
    auth_config["token"] = config.token;

  if (config.type === "basic") {
    if (config.username) auth_config["username"] = config.username;
    if (config.password) auth_config["password"] = config.password;
  }

  if (config.type === "api_key") {
    if (config.header) auth_config["header"] = config.header;
    if (config.value)  auth_config["value"]  = config.value;
  }

  return { auth_type: config.type, auth_config };
}

export function apiPayloadToAuthConfig(
  auth_type: AuthType,
  auth_config: Record<string, string>,
): AuthConfig {
  return {
    type:     auth_type,
    token:    auth_config["token"],
    username: auth_config["username"],
    password: auth_config["password"],
    header:   auth_config["header"],
    value:    auth_config["value"],
  };
}
