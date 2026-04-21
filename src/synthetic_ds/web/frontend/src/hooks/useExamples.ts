import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface Params {
  split?: string;
  accepted?: boolean | null;
  kind?: string;
  score_min?: number;
  limit?: number;
  offset?: number;
}

export function useExamples(jobId: string | undefined, params: Params = {}) {
  return useQuery({
    queryKey: ["examples", jobId, params],
    queryFn: () => api.getExamples(jobId!, params),
    enabled: !!jobId,
  });
}
