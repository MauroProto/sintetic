import type { SourceModeResult } from "@/lib/types";
import { cn } from "@/lib/utils";

export function SourceModeHint({ result, loading }: { result: SourceModeResult | null; loading: boolean }) {
  if (loading) {
    return <p className="text-[12px] text-muted-foreground">Analizando carpeta...</p>;
  }
  if (!result) return null;

  const ok = result.ok;
  return (
    <div className="space-y-2 rounded-md bg-secondary px-3 py-2 text-[12px] shadow-border-light">
      <div className="flex items-center gap-2">
        <span className={cn("h-1.5 w-1.5 rounded-full", ok ? "bg-success" : "bg-destructive")} />
        <span className={cn("font-medium", !ok && "text-destructive")}>
          {ok
            ? `${result.label} · ${result.pdf_count} PDF${result.pdf_count === 1 ? "" : "s"}`
            : result.message}
        </span>
      </div>
      {ok && result.message ? <p className="text-muted-foreground">{result.message}</p> : null}
      {ok && result.note ? <p className="text-muted-foreground">{result.note}</p> : null}
    </div>
  );
}
