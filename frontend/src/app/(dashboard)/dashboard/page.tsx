"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Plus, FolderOpen, ArrowRight } from "lucide-react";
import { toast } from "sonner";
import { workspaceService } from "@/lib/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import type { Workspace } from "@/types";

export default function DashboardPage() {
  const router = useRouter();
  const { setActiveWorkspace } = useWorkspaceStore();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", description: "" });
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    workspaceService
      .list()
      .then((r) => setWorkspaces(r.data))
      .catch(() => toast.error("Failed to load workspaces"))
      .finally(() => setLoading(false));
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    try {
      const { data } = await workspaceService.create(form);
      setWorkspaces((prev) => [...prev, data]);
      setOpen(false);
      setForm({ name: "", description: "" });
      toast.success("Workspace created");
    } catch {
      toast.error("Failed to create workspace");
    } finally {
      setCreating(false);
    }
  };

  const openWorkspace = (ws: Workspace) => {
    setActiveWorkspace(ws);
    router.push(`/workspaces/${ws.id}`);
  };

  return (
    <>
      <Header
        title="Dashboard"
        description="Select or create a workspace to get started"
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors">
              <Plus className="h-4 w-4" />
              New workspace
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create workspace</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleCreate} className="space-y-4 pt-2">
                <div className="space-y-1.5">
                  <Label htmlFor="ws-name">Name</Label>
                  <Input
                    id="ws-name"
                    placeholder="My API Project"
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                    required
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ws-desc">Description (optional)</Label>
                  <Input
                    id="ws-desc"
                    placeholder="What are you testing?"
                    value={form.description}
                    onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  />
                </div>
                <Button type="submit" className="w-full" disabled={creating}>
                  {creating ? "Creating…" : "Create workspace"}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        }
      />

      <div className="flex-1 overflow-auto p-6">
        {loading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[...Array(3)].map((_, i) => (
              <Skeleton key={i} className="h-28 rounded-lg" />
            ))}
          </div>
        ) : workspaces.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center gap-4 text-center">
            <FolderOpen className="h-12 w-12 text-muted-foreground/40" />
            <div>
              <p className="font-medium">No workspaces yet</p>
              <p className="text-sm text-muted-foreground">
                Create one to start organizing your API tests.
              </p>
            </div>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {workspaces.map((ws) => (
              <Card
                key={ws.id}
                className="cursor-pointer transition-shadow hover:shadow-md"
                onClick={() => openWorkspace(ws)}
              >
                <CardHeader className="flex flex-row items-start justify-between pb-3">
                  <div>
                    <CardTitle className="text-base">{ws.name}</CardTitle>
                    {ws.description && (
                      <CardDescription className="mt-1 line-clamp-2 text-sm">
                        {ws.description}
                      </CardDescription>
                    )}
                  </div>
                  <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                </CardHeader>
              </Card>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
