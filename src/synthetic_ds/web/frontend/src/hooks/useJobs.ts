import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useJobs(limit = 20) {
  return useQuery({
    queryKey: ["jobs", { limit }],
    queryFn: () => api.getJobs(limit),
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  });
}
