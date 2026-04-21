import { Badge } from "@/components/ui/badge";
import { statusToTone } from "@/lib/utils";

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  paused: "Paused",
  pausing: "Pausing",
  resuming: "Resuming",
  completed: "Ready",
  failed: "Error",
  cancelled: "Cancelled",
};

export function JobStatusPill({ status }: { status: string }) {
  const tone = statusToTone(status);
  const label = STATUS_LABELS[status] ?? status;
  const variant =
    tone === "success"
      ? "success"
      : tone === "destructive"
        ? "destructive"
        : tone === "warning"
          ? "warning"
          : tone === "running"
            ? "default"
            : "muted";
  return (
    <Badge variant={variant} className="font-geist-mono text-[10px] uppercase tracking-[0.12em]">
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          tone === "success"
            ? "bg-success"
            : tone === "destructive"
              ? "bg-destructive"
              : tone === "warning"
                ? "bg-warning"
                : tone === "running"
                  ? "bg-badge-blue-fg animate-pulse"
                  : "bg-muted-foreground"
        }`}
      />
      {label}
    </Badge>
  );
}
