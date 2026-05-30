import api from "@/lib/api";
import type { Workspace, Environment, EnvVariable } from "@/types";

export const workspaceService = {
  list: () => api.get<Workspace[]>("/workspaces"),
  create: (data: { name: string; description?: string }) =>
    api.post<Workspace>("/workspaces", data),
  update: (id: string, data: Partial<Pick<Workspace, "name" | "description">>) =>
    api.patch<Workspace>(`/workspaces/${id}`, data),
  delete: (id: string) => api.delete(`/workspaces/${id}`),
};

export const environmentService = {
  list: (workspaceId: string) =>
    api.get<Environment[]>(`/workspaces/${workspaceId}/environments`),
  create: (workspaceId: string, data: { name: string }) =>
    api.post<Environment>(`/workspaces/${workspaceId}/environments`, data),
  update: (id: string, data: Partial<Pick<Environment, "name" | "is_active">>) =>
    api.patch<Environment>(`/environments/${id}`, data),
  delete: (id: string) => api.delete(`/environments/${id}`),

  listVariables: (envId: string) =>
    api.get<EnvVariable[]>(`/environments/${envId}/variables`),
  createVariable: (envId: string, data: Omit<EnvVariable, "id" | "environment_id">) =>
    api.post<EnvVariable>(`/environments/${envId}/variables`, data),
  updateVariable: (id: string, data: Partial<EnvVariable>) =>
    api.patch<EnvVariable>(`/variables/${id}`, data),
  deleteVariable: (id: string) => api.delete(`/variables/${id}`),
};
