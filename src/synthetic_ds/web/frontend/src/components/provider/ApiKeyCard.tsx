import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { useProviders } from "@/hooks/useConfig";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  compact?: boolean;
}

export function ApiKeyCard({ compact = false }: Props) {
  const { data: providers, isLoading } = useProviders();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [selected, setSelected] = useState<string | undefined>(undefined);
  const [apiKey, setApiKey] = useState("");

  const activeName = selected ?? providers?.active ?? "";
  const activeProfile = providers?.profiles[activeName];
  const keyPresent = providers?.keys_present[activeName] ?? false;

  const saveKeyMutation = useMutation({
    mutationFn: () => api.saveProviderKey(activeName, apiKey),
    onSuccess: () => {
      toast({ variant: "success", title: "API key guardada" });
      setApiKey("");
      queryClient.invalidateQueries({ queryKey: ["providers"] });
    },
    onError: (error) => {
      toast({ variant: "error", title: "Error", description: (error as Error).message });
    },
  });

  const setActiveMutation = useMutation({
    mutationFn: (provider: string) => api.setActiveProvider(provider),
    onSuccess: (data) => {
      toast({ variant: "info", title: `Proveedor activo: ${data.active}` });
      queryClient.invalidateQueries({ queryKey: ["providers"] });
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
    onError: (error) => {
      toast({ variant: "error", title: "No se pudo cambiar", description: (error as Error).message });
    },
  });

  return (
    <div className={cn("grid gap-8", !compact && "md:grid-cols-[1.5fr_1fr] md:items-start")}>
      <div className="space-y-5">
        <div className="space-y-2">
          <span className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
            Modelo activo
          </span>
          <p className="font-geist-mono text-sm text-foreground">{activeProfile?.model ?? "—"}</p>
        </div>

        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!apiKey.trim() || !activeName) return;
            saveKeyMutation.mutate();
          }}
        >
          <label
            htmlFor="api-key"
            className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground"
          >
            API key
          </label>
          <div className="flex items-center gap-2">
            <Input
              id="api-key"
              type="password"
              autoComplete="off"
              placeholder={activeProfile?.api_key_env ?? "sk-..."}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              className="max-w-md"
            />
            <Button type="submit" variant="outline" disabled={!apiKey.trim() || saveKeyMutation.isPending}>
              {saveKeyMutation.isPending ? "Guardando..." : "Guardar"}
            </Button>
          </div>
          <p className="text-[12px] text-muted-foreground">
            Se almacena en el keychain del sistema · env:{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-geist-mono text-[11px]">
              {activeProfile?.api_key_env ?? ""}
            </code>
          </p>
        </form>
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              isLoading ? "bg-muted-foreground" : keyPresent ? "bg-success" : "bg-warning",
            )}
          />
          <span className="font-geist-mono text-[11px] uppercase tracking-[0.1em] text-muted-foreground">
            {isLoading ? "Verificando" : keyPresent ? "Key configurada" : "Sin key"}
          </span>
        </div>
        <div>
          <span className="mb-2 block font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
            Proveedor
          </span>
          <Select
            value={activeName}
            onValueChange={(value) => {
              setSelected(value);
              if (providers && value !== providers.active) {
                setActiveMutation.mutate(value);
              }
            }}
          >
            <SelectTrigger>
              <SelectValue placeholder="Seleccionar" />
            </SelectTrigger>
            <SelectContent>
              {Object.keys(providers?.profiles ?? {}).map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  );
}
