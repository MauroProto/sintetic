import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, Square } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import type { JobRecord } from "@/lib/types";

export function JobControls({ job }: { job: JobRecord }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const mutation = useMutation({
    mutationFn: async (action: "pause" | "resume" | "cancel") => {
      await api.controlJob(job.job_id, action);
      return action;
    },
    onSuccess: (action) => {
      toast({
        variant: "success",
        title:
          action === "pause"
            ? "Pausando corrida"
            : action === "resume"
              ? "Reanudando corrida"
              : "Cancelando corrida",
      });
      queryClient.invalidateQueries({ queryKey: ["jobs", job.job_id] });
    },
    onError: (error) => {
      toast({
        variant: "error",
        title: "Error ejecutando acción",
        description: (error as Error).message,
      });
    },
  });

  const isTerminal = ["completed", "failed", "cancelled"].includes(job.status);
  if (isTerminal) return null;

  const canPause = ["running", "resuming", "queued"].includes(job.status);
  const canResume = ["paused", "pausing"].includes(job.status);

  return (
    <div className="flex items-center gap-1">
      {canPause && (
        <Button variant="ghost" size="sm" disabled={mutation.isPending} onClick={() => mutation.mutate("pause")}>
          <Pause className="h-3.5 w-3.5" /> Pausar
        </Button>
      )}
      {canResume && (
        <Button variant="ghost" size="sm" disabled={mutation.isPending} onClick={() => mutation.mutate("resume")}>
          <Play className="h-3.5 w-3.5" /> Reanudar
        </Button>
      )}
      <Button variant="ghost" size="sm" disabled={mutation.isPending} onClick={() => mutation.mutate("cancel")}>
        <Square className="h-3.5 w-3.5" /> Cancelar
      </Button>
    </div>
  );
}
