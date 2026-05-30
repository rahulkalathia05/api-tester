import { useState, useEffect } from "react";
import { environmentService } from "@/lib/services/workspace.service";
import type { Environment } from "@/types";

export function useEnvironments(workspaceId: string | undefined) {
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!workspaceId) return;
    setLoading(true);
    environmentService
      .list(workspaceId)
      .then((r) => setEnvironments(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [workspaceId]);

  return { environments, loading, setEnvironments };
}
