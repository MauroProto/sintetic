import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import { JobStatusPill } from "./JobStatusPill";
import { formatPercent, formatRelative, truncate } from "@/lib/utils";
import type { JobRecord } from "@/lib/types";

export function JobCard({ job }: { job: JobRecord }) {
  const percent = Math.round((job.percent ?? 0) * 100);
  const name = job.source_dir.split("/").filter(Boolean).pop() ?? job.source_dir;
  return (
    <Link
      to={`/runs/${job.job_id}`}
      className="group block rounded-lg bg-card p-5 shadow-card transition-shadow hover:shadow-card-hover"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          <h3 className="truncate text-[15px] font-semibold tracking-tight">
            {truncate(name, 32)}
          </h3>
          <p className="truncate font-geist-mono text-[11px] text-muted-foreground">{job.job_id}</p>
        </div>
        <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-foreground" />
      </div>

      <div className="mt-6 space-y-3">
        <div className="flex items-baseline justify-between">
          <JobStatusPill status={job.status} />
          <span className="font-geist-mono text-[11px] text-muted-foreground">
            {formatRelative(job.updated_at)}
          </span>
        </div>

        <div className="h-[3px] w-full overflow-hidden rounded-pill bg-secondary">
          <div
            className="h-full bg-foreground transition-all duration-700 ease-out"
            style={{ width: `${percent}%` }}
          />
        </div>

        <div className="flex items-center justify-between">
          <span className="font-geist-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            {job.stage}
          </span>
          <span className="text-[13px] font-semibold tabular-nums">{formatPercent(job.percent)}</span>
        </div>
      </div>
    </Link>
  );
}
