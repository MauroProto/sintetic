import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function usePdfs(sourceDir: string) {
  return useQuery({
    queryKey: ["pdfs", sourceDir],
    queryFn: () => api.listPdfs(sourceDir.trim()),
    enabled: !!sourceDir.trim(),
    staleTime: 5000,
  });
}
