import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { JobEvent, JobRecord } from "@/lib/types";
import { useEventSource } from "@/lib/sse";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

export function useJob(jobId: string | undefined) {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["jobs", jobId],
    queryFn: () => api.getJob(jobId!),
    enabled: !!jobId,
  });

  const terminal = query.data ? TERMINAL_STATUSES.has(query.data.status) : false;
  const streamUrl = jobId && !terminal ? `/api/jobs/${jobId}/events` : null;

  useEventSource(streamUrl, (raw) => {
    const event = raw as JobEvent & { stats?: Record<string, unknown> };
    queryClient.setQueryData<JobRecord>(["jobs", jobId], (prev) => {
      if (!prev) return prev;
      const events = prev.events ? [...prev.events, event] : [event];
      return {
        ...prev,
        stage: event.stage ?? prev.stage,
        status: event.status ?? prev.status,
        percent: event.percent ?? prev.percent,
        message: event.message ?? prev.message,
        current_file: event.current_file ?? prev.current_file,
        stats: event.stats ? { ...prev.stats, ...event.stats } : prev.stats,
        events,
      };
    });
    if (event.status && TERMINAL_STATUSES.has(event.status)) {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["metrics", jobId] });
      queryClient.invalidateQueries({ queryKey: ["artifacts", jobId] });
    }
  });

  useEffect(() => {
    if (terminal) {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    }
  }, [terminal, queryClient]);

  return query;
}
