import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Download } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useJob } from "@/hooks/useJob";
import { useArtifacts } from "@/hooks/useArtifacts";
import { JobStatusPill } from "@/components/jobs/JobStatusPill";
import { JobStatsGrid } from "@/components/jobs/JobStatsGrid";
import { JobControls } from "@/components/jobs/JobControls";
import { EventsTimeline } from "@/components/jobs/EventsTimeline";
import { ExampleViewer } from "@/components/examples/ExampleViewer";
import { MetricsOverview } from "@/components/metrics/MetricsOverview";
import { api } from "@/lib/api";
import { formatDate, formatNumber, formatPercent, truncate } from "@/lib/utils";

export function RunDetailPage() {
  const { jobId = "" } = useParams();
  const { data: job, isLoading } = useJob(jobId);

  if (isLoading || !job) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-32 rounded-lg" />
        <Skeleton className="h-96 rounded-lg" />
      </div>
    );
  }

  const percent = Math.round((job.percent ?? 0) * 100);
  const name = job.source_dir.split("/").filter(Boolean).pop() ?? job.source_dir;

  return (
    <div className="space-y-10">
      <Link
        to="/"
        className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Overview
      </Link>

      <header className="space-y-4">
        <div className="flex items-center gap-3">
          <Badge>Corrida</Badge>
          <span className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
            {job.job_id}
          </span>
        </div>
        <h1 className="text-[clamp(32px,4vw,48px)] font-semibold leading-[1.05] tracking-tightest">
          {truncate(name, 60)}
        </h1>
        <p className="font-geist-mono text-[12px] text-muted-foreground">{truncate(job.source_dir, 100)}</p>
      </header>

      <section className="rounded-lg bg-card p-6 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-6">
            <JobStatusPill status={job.status} />
            <div className="flex items-baseline gap-2">
              <span className="font-geist text-3xl font-semibold tabular-nums tracking-tight">
                {formatPercent(job.percent)}
              </span>
              <span className="font-geist-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                {job.stage}
              </span>
            </div>
          </div>
          <JobControls job={job} />
        </div>

        <div className="mt-6 h-[3px] w-full overflow-hidden rounded-pill bg-secondary">
          <div
            className="h-full bg-foreground transition-all duration-700 ease-out"
            style={{ width: `${percent}%` }}
          />
        </div>

        {job.message ? (
          <p className="mt-4 text-[13px] text-muted-foreground">{job.message}</p>
        ) : null}
      </section>

      <Tabs defaultValue="live" className="space-y-8">
        <TabsList>
          <TabsTrigger value="live">Progreso</TabsTrigger>
          <TabsTrigger value="metrics">Métricas</TabsTrigger>
          <TabsTrigger value="examples">Ejemplos</TabsTrigger>
          <TabsTrigger value="artifacts">Artefactos</TabsTrigger>
        </TabsList>

        <TabsContent value="live" className="space-y-10">
          <JobStatsGrid job={job} />
          <section className="space-y-5">
            <div className="flex items-baseline gap-4">
              <span className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
                Eventos
              </span>
              <h2 className="text-lg font-semibold tracking-tight">Timeline</h2>
            </div>
            <div className="rounded-lg bg-card p-6 shadow-card">
              <EventsTimeline events={job.events} />
            </div>
          </section>
        </TabsContent>

        <TabsContent value="metrics">
          <MetricsOverview jobId={jobId} />
        </TabsContent>

        <TabsContent value="examples">
          <ExampleViewer jobId={jobId} />
        </TabsContent>

        <TabsContent value="artifacts">
          <ArtifactsList jobId={jobId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function ArtifactsList({ jobId }: { jobId: string }) {
  const { data, isLoading } = useArtifacts(jobId);
  if (isLoading) return <Skeleton className="h-64 rounded-lg" />;
  if (!data) return null;
  if (data.items.length === 0) {
    return (
      <div className="rounded-lg bg-card p-12 text-center shadow-card">
        <p className="text-sm text-muted-foreground">
          Sin artefactos todavía. Aparecerán aquí cuando avance la corrida.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <p className="font-geist-mono text-[11px] text-muted-foreground">{data.root}</p>
      <div className="overflow-hidden rounded-lg bg-card shadow-card">
        <div className="divide-y divide-border">
          {data.items.map((item) => (
            <div key={item.path} className="flex items-center justify-between gap-4 px-5 py-3">
              <div className="flex min-w-0 flex-col">
                <span className="truncate font-geist-mono text-[13px]">{item.path}</span>
                <span className="font-geist-mono text-[11px] text-muted-foreground">
                  {formatNumber(item.size)} bytes · {formatDate(item.modified_at)}
                </span>
              </div>
              <Button asChild size="sm" variant="outline">
                <a href={api.artifactDownloadUrl(jobId, item.path)} download>
                  <Download className="h-3.5 w-3.5" />
                  Descargar
                </a>
              </Button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
