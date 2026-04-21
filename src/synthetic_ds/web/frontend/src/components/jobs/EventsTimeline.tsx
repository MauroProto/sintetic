import { ScrollArea } from "@/components/ui/scroll-area";
import { cn, formatDate, formatPercent, statusToTone } from "@/lib/utils";
import type { JobEvent } from "@/lib/types";

const DOT_CLASS: Record<ReturnType<typeof statusToTone>, string> = {
  neutral: "bg-muted-foreground",
  running: "bg-badge-blue-fg",
  success: "bg-success",
  warning: "bg-warning",
  destructive: "bg-destructive",
};

export function EventsTimeline({ events }: { events: JobEvent[] | undefined }) {
  if (!events || events.length === 0) {
    return <p className="text-sm text-muted-foreground">Todavía no hay eventos registrados.</p>;
  }
  const reversed = [...events].reverse();
  return (
    <ScrollArea className="h-[420px]">
      <ul className="divide-y divide-border">
        {reversed.map((event) => {
          const tone = statusToTone(event.status);
          return (
            <li key={event.event_id} className="grid grid-cols-[auto_1fr_auto] items-start gap-4 py-3.5">
              <span className={cn("mt-1.5 h-1.5 w-1.5 rounded-full", DOT_CLASS[tone])} />
              <div className="min-w-0 space-y-1">
                <div className="flex items-baseline gap-3">
                  <span className="text-[13px] font-medium">{event.stage}</span>
                  <span className="font-geist-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                    {event.status}
                  </span>
                </div>
                {event.message ? (
                  <p className="text-[12px] text-muted-foreground">{event.message}</p>
                ) : null}
              </div>
              <span className="font-geist-mono text-[11px] tabular-nums text-muted-foreground">
                {formatPercent(event.percent)} · {formatDate(event.created_at)}
              </span>
            </li>
          );
        })}
      </ul>
    </ScrollArea>
  );
}
