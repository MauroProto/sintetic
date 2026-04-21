import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useArtifacts(jobId: string | undefined) {
  return useQuery({
    queryKey: ["artifacts", jobId],
    queryFn: () => api.getArtifacts(jobId!),
    enabled: !!jobId,
  });
}
