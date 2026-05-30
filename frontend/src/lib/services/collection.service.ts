import api from "@/lib/api";
import type { Collection, ApiRequest, Assertion } from "@/types";

export const collectionService = {
  // Collections
  list: (workspaceId: string) =>
    api.get<Collection[]>(`/workspaces/${workspaceId}/collections`),

  create: (workspaceId: string, data: { name: string; description?: string }) =>
    api.post<Collection>(`/workspaces/${workspaceId}/collections`, data),

  update: (id: string, data: Partial<Pick<Collection, "name" | "description">>) =>
    api.patch<Collection>(`/collections/${id}`, data),

  delete: (id: string) => api.delete(`/collections/${id}`),

  getWithRequests: (id: string) =>
    api.get<Collection>(`/collections/${id}`),

  // Requests
  createRequest: (collectionId: string, data: Partial<ApiRequest>) =>
    api.post<ApiRequest>(`/collections/${collectionId}/requests`, data),

  updateRequest: (id: string, data: Partial<ApiRequest>) =>
    api.patch<ApiRequest>(`/requests/${id}`, data),

  deleteRequest: (id: string) => api.delete(`/requests/${id}`),

  runSingle: (id: string, environmentId?: string) =>
    api.post(`/requests/${id}/run`, { environment_id: environmentId }),

  // Assertions
  createAssertion: (requestId: string, data: Partial<Assertion>) =>
    api.post<Assertion>(`/requests/${requestId}/assertions`, data),

  updateAssertion: (id: string, data: Partial<Assertion>) =>
    api.patch<Assertion>(`/assertions/${id}`, data),

  deleteAssertion: (id: string) => api.delete(`/assertions/${id}`),
};
