import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ExamplePatch } from "@/lib/types";

interface Params {
  accepted?: boolean | null;
  kind?: string;
  score_min?: number;
  search?: string;
  limit?: number;
  offset?: number;
}

export function useDashboardExamples(params: Params = {}) {
  return useQuery({
    queryKey: ["dashboard-examples", params],
    queryFn: () => api.getDashboardExamples(params),
    refetchInterval: 8000,
    staleTime: 4000,
  });
}

export function useExampleMutations() {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["dashboard-examples"] });
    queryClient.invalidateQueries({ queryKey: ["examples"] });
    queryClient.invalidateQueries({ queryKey: ["metrics"] });
    queryClient.invalidateQueries({ queryKey: ["artifacts"] });
  };

  const patch = useMutation({
    mutationFn: ({
      jobId,
      exampleId,
      split,
      patch,
    }: {
      jobId: string;
      exampleId: string;
      split: string;
      patch: ExamplePatch;
    }) => api.patchExample(jobId, exampleId, split, patch),
    onSuccess: invalidate,
  });

  const accept = useMutation({
    mutationFn: ({ jobId, exampleId, split }: { jobId: string; exampleId: string; split: string }) =>
      api.acceptExample(jobId, exampleId, split),
    onSuccess: invalidate,
  });

  const reject = useMutation({
    mutationFn: ({
      jobId,
      exampleId,
      split,
      reason,
    }: {
      jobId: string;
      exampleId: string;
      split: string;
      reason?: string;
    }) => api.rejectExample(jobId, exampleId, split, reason),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: ({ jobId, exampleId, split }: { jobId: string; exampleId: string; split: string }) =>
      api.deleteExample(jobId, exampleId, split),
    onSuccess: invalidate,
  });

  return { patch, accept, reject, remove };
}
