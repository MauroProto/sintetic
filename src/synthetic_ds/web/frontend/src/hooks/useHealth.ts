import { useQuery } from "@tanstack/react-query";

interface HealthResponse {
  ok: boolean;
  dependencies: {
    tesseract?: { found: boolean; path?: string | null };
    docling?: { found: boolean };
    tiktoken?: { found: boolean };
    langdetect?: { found: boolean };
  };
  pool?: {
    max_concurrent_jobs: number;
    running: string[];
    queued: string[];
  };
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: async (): Promise<HealthResponse> => {
      const res = await fetch("/api/health");
      if (!res.ok) throw new Error(`health ${res.status}`);
      return res.json();
    },
    refetchInterval: 8000,
    refetchIntervalInBackground: false,
    staleTime: 5000,
  });
}
