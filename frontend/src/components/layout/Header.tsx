"use client";

import { useWorkspaceStore } from "@/stores/workspaceStore";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { useEnvironments } from "@/hooks/useEnvironments";

interface HeaderProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}

export function Header({ title, description, actions }: HeaderProps) {
  const { activeWorkspace, activeEnvironment, setActiveEnvironment } =
    useWorkspaceStore();
  const { environments } = useEnvironments(activeWorkspace?.id);

  return (
    <header className="flex h-14 items-center justify-between border-b px-6">
      <div>
        <h1 className="text-base font-semibold">{title}</h1>
        {description && (
          <p className="text-xs text-muted-foreground">{description}</p>
        )}
      </div>

      <div className="flex items-center gap-3">
        {/* Environment selector */}
        {environments.length > 0 && (
          <Select
            value={activeEnvironment?.id ?? "none"}
            onValueChange={(val) => {
              const env = environments.find((e) => e.id === val) ?? null;
              setActiveEnvironment(env);
            }}
          >
            <SelectTrigger className="h-8 w-40 text-xs">
              <SelectValue placeholder="No environment" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No environment</SelectItem>
              {environments.map((env) => (
                <SelectItem key={env.id} value={env.id}>
                  <span className="flex items-center gap-2">
                    {env.name}
                    {env.is_active && (
                      <Badge variant="secondary" className="text-[10px] px-1 py-0">
                        active
                      </Badge>
                    )}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        {actions}
      </div>
    </header>
  );
}
