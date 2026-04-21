import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ProjectConfig } from "@/lib/types";

export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: () => api.getConfig(),
  });
}

export function useSaveConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { yaml?: string; config?: ProjectConfig }) => api.saveConfig(payload),
    onSuccess: (data) => {
      queryClient.setQueryData(["config"], data);
      queryClient.invalidateQueries({ queryKey: ["providers"] });
    },
  });
}

export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    queryFn: () => api.getProviders(),
  });
}
