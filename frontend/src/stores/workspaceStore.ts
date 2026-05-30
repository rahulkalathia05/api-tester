import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Workspace, Environment } from "@/types";

interface WorkspaceState {
  activeWorkspace: Workspace | null;
  activeEnvironment: Environment | null;

  setActiveWorkspace: (workspace: Workspace | null) => void;
  setActiveEnvironment: (environment: Environment | null) => void;
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({
      activeWorkspace: null,
      activeEnvironment: null,

      setActiveWorkspace: (activeWorkspace) =>
        set({ activeWorkspace, activeEnvironment: null }),

      setActiveEnvironment: (activeEnvironment) =>
        set({ activeEnvironment }),
    }),
    { name: "api-tester-workspace" }
  )
);
