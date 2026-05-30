import { useState, useEffect, useCallback } from "react";
import { collectionService } from "@/lib/services/collection.service";
import type { Collection } from "@/types";

export function useCollections(workspaceId: string | undefined) {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await collectionService.list(workspaceId);
      // API returns a paginated envelope {items, total, ...} — extract the array
      const items = Array.isArray(data) ? data : (data as any).items ?? [];
      setCollections(items);
    } catch {
      setError("Failed to load collections");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => { load(); }, [load]);

  return { collections, loading, error, refetch: load, setCollections };
}
