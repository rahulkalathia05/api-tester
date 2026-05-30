"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Plus, FolderOpen, Trash2, ArrowRight, Upload } from "lucide-react";
import { toast } from "sonner";
import { useCollections } from "@/hooks/useCollections";
import { collectionService } from "@/lib/services/collection.service";
import { ImportDialog } from "@/components/collections/ImportDialog";
import { Header } from "@/components/layout/Header";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";

export default function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { activeWorkspace } = useWorkspaceStore();
  const { collections, loading, refetch, setCollections } = useCollections(id);

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", description: "" });
  const [creating, setCreating] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setCreating(true);
    try {
      await collectionService.create(id, {
        name: form.name.trim(),
        description: form.description.trim() || undefined,
      });
      setForm({ name: "", description: "" });
      setOpen(false);
      await refetch();
      toast.success("Collection created");
    } catch {
      toast.error("Failed to create collection");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, colId: string, colName: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm(`Delete "${colName}"? This will also delete all requests inside it.`)) return;
    try {
      await collectionService.delete(colId);
      setCollections((prev) => prev.filter((c) => c.id !== colId));
      toast.success("Collection deleted");
    } catch {
      toast.error("Failed to delete collection");
    }
  };

  return (
    <>
      <Header
        title={activeWorkspace?.name ?? "Workspace"}
        description="API collections"
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="gap-1.5"
              onClick={() => setImportOpen(true)}>
              <Upload className="h-4 w-4" />
              Import
            </Button>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors">
              <Plus className="h-4 w-4" />
              New collection
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create collection</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleCreate} className="space-y-4 pt-2">
                <div className="space-y-1.5">
                  <Label htmlFor="col-name">Name</Label>
                  <Input
                    id="col-name"
                    placeholder="e.g. User Service"
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                    required
                    autoFocus
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="col-desc">Description (optional)</Label>
                  <Input
                    id="col-desc"
                    placeholder="What APIs are in this collection?"
                    value={form.description}
                    onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  />
                </div>
                <Button type="submit" className="w-full" disabled={creating}>
                  {creating ? "Creating…" : "Create collection"}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
          </div>
        }
      />

      {/* Import dialog */}
      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        workspaceId={id}
        onSuccess={() => refetch()}
      />

      <div className="flex-1 overflow-auto p-6">
        {loading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[...Array(3)].map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-lg" />
            ))}
          </div>
        ) : collections.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center gap-4 text-center">
            <FolderOpen className="h-12 w-12 text-muted-foreground/30" />
            <div>
              <p className="font-medium">No collections yet</p>
              <p className="text-sm text-muted-foreground mt-1">
                Click <strong>New collection</strong> to get started.
              </p>
            </div>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {collections.map((col) => (
              <div
                key={col.id}
                className="group relative cursor-pointer"
                onClick={() => router.push(`/workspaces/${id}/collections/${col.id}`)}
              >
                <Card className="h-full transition-shadow hover:shadow-md">
                  <CardHeader className="pb-3">
                    <div className="flex items-start justify-between gap-2">
                      <CardTitle className="text-base leading-snug">{col.name}</CardTitle>
                      <div className="flex shrink-0 items-center gap-1">
                        <Badge variant="secondary" className="text-xs">
                          {(col as any).variable_count ?? (col as any).request_count ?? 0} requests
                        </Badge>
                        <button
                          className="hidden group-hover:flex items-center rounded p-1 text-muted-foreground hover:text-red-600 transition-colors"
                          onClick={(e) => handleDelete(e, col.id, col.name)}
                          title="Delete collection"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                    {col.description && (
                      <CardDescription className="line-clamp-2 text-xs mt-1">
                        {col.description}
                      </CardDescription>
                    )}
                  </CardHeader>
                </Card>
                <ArrowRight className="absolute right-3 bottom-3 h-3.5 w-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
