import api from "@/lib/api";
import type { Environment, EnvironmentDetail, EnvVariable, PreviewResponse } from "@/types";

export interface BulkVariable {
  key: string;
  value: string;
  is_secret: boolean;
}

export const environmentService = {
  // ── Environments ───────────────────────────────────────────────────────────
  list: (workspaceId: string) =>
    api.get<Environment[]>(`/workspaces/${workspaceId}/environments`),

  create: (workspaceId: string, name: string) =>
    api.post<Environment>(`/workspaces/${workspaceId}/environments`, { name }),

  get: (envId: string) =>
    api.get<EnvironmentDetail>(`/environments/${envId}`),

  update: (envId: string, name: string) =>
    api.patch<Environment>(`/environments/${envId}`, { name }),

  delete: (envId: string) =>
    api.delete(`/environments/${envId}`),

  activate: (envId: string) =>
    api.post<Environment>(`/environments/${envId}/activate`),

  deactivate: (envId: string) =>
    api.post<Environment>(`/environments/${envId}/deactivate`),

  // ── Variables ──────────────────────────────────────────────────────────────
  listVariables: (envId: string) =>
    api.get<EnvVariable[]>(`/environments/${envId}/variables`),

  createVariable: (envId: string, key: string, value: string, is_secret = false) =>
    api.post<EnvVariable>(`/environments/${envId}/variables`, { key, value, is_secret }),

  bulkUpsert: (envId: string, variables: BulkVariable[]) =>
    api.put<EnvVariable[]>(`/environments/${envId}/variables`, { variables }),

  updateVariable: (varId: string, data: Partial<EnvVariable>) =>
    api.patch<EnvVariable>(`/variables/${varId}`, data),

  deleteVariable: (varId: string) =>
    api.delete(`/variables/${varId}`),

  // ── Preview ────────────────────────────────────────────────────────────────
  preview: (envId: string, template: string) =>
    api.post<PreviewResponse>(`/environments/${envId}/preview`, { template }),
};
