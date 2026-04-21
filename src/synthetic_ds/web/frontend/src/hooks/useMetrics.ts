import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useMetrics(jobId: string | undefined) {
  return useQuery({
    queryKey: ["metrics", jobId],
    queryFn: () => api.getMetrics(jobId!),
    enabled: !!jobId,
  });
}
