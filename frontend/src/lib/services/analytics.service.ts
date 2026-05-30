import api from "@/lib/api";
import type { WorkspaceAnalytics } from "@/types";

export const analyticsService = {
  getWorkspaceAnalytics: (workspaceId: string, days = 30) =>
    api.get<WorkspaceAnalytics>(`/workspaces/${workspaceId}/analytics`, {
      params: { days },
    }),
};
