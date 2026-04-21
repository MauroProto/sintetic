import { formatEta, formatNumber } from "@/lib/utils";
import type { JobRecord } from "@/lib/types";

interface StatProps {
  label: string;
  value: string;
  hint?: string;
}

function Stat({ label, value, hint }: StatProps) {
  return (
    <div className="flex flex-col gap-2 rounded-lg bg-card p-5 shadow-card">
      <span className="font-geist-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
        {label}
      </span>
      <span className="font-geist text-2xl font-semibold tracking-tight tabular-nums">{value}</span>
      {hint ? <span className="font-geist-mono text-[11px] text-muted-foreground">{hint}</span> : null}
    </div>
  );
}

export function JobStatsGrid({ job }: { job: JobRecord }) {
  const stats = job.stats ?? {};
  const pages = Number(stats.pages_processed ?? 0);
  const totalPages = Number(stats.total_pages ?? 0);
  const currentBatch = Number(stats.current_batch ?? 0);
  const totalBatches = Number(stats.total_batches ?? 0);
  const requests = Number(stats.requests_completed ?? stats.requests ?? 0);
  const accepted = Object.values((stats.accepted as Record<string, number> | undefined) ?? {}).reduce(
    (acc, value) => acc + Number(value ?? 0),
    0,
  );
  const rejected = Object.values((stats.rejected as Record<string, number> | undefined) ?? {}).reduce(
    (acc, value) => acc + Number(value ?? 0),
    0,
  );
  const eta = Number(stats.eta_seconds ?? 0);

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <Stat label="Páginas" value={formatNumber(pages)} hint={totalPages ? `de ${formatNumber(totalPages)}` : undefined} />
      <Stat label="Lotes" value={totalBatches ? `${currentBatch}/${totalBatches}` : `${currentBatch}`} />
      <Stat label="Requests" value={formatNumber(requests)} />
      <Stat label="Aceptados" value={formatNumber(accepted)} />
      <Stat label="Rechazados" value={formatNumber(rejected)} />
      <Stat label="ETA" value={formatEta(eta)} />
    </div>
  );
}
