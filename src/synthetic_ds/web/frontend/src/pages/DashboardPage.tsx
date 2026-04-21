import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useJobs } from "@/hooks/useJobs";
import { JobCard } from "@/components/jobs/JobCard";
import { ApiKeyCard } from "@/components/provider/ApiKeyCard";

export function DashboardPage() {
  const { data: jobs, isLoading } = useJobs(12);

  return (
    <div className="space-y-24">
      {/* Hero */}
      <section className="space-y-10">
        <div className="flex items-center gap-3">
          <Badge>Dataset forge</Badge>
          <span className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
            v0.1 · Local
          </span>
        </div>

        <h1 className="text-[clamp(40px,6.4vw,68px)] font-semibold leading-[1.02] tracking-tightest">
          De PDF a JSONL.{" "}
          <span className="text-muted-foreground">
            Sin salir de tu máquina.
          </span>
        </h1>

        <p className="max-w-2xl text-[18px] leading-[1.6] text-muted-foreground">
          Apuntá a una carpeta con PDFs y obtené un dataset fine‑tune ready:
          ingest, generación, curación y export. Todo local, todo reproducible.
        </p>

        <div className="flex flex-wrap items-center gap-3">
          <Button asChild size="lg">
            <Link to="/new">
              Nueva corrida
              <ArrowRight className="h-4 w-4" />
            </Link>
          </Button>
          <Button asChild variant="outline" size="lg">
            <Link to="/dataset">Ver dataset completo</Link>
          </Button>
          <Button asChild variant="ghost" size="lg">
            <Link to="/settings">Configuración</Link>
          </Button>
        </div>
      </section>

      {/* Pipeline pills */}
      <section className="grid gap-4 sm:grid-cols-3">
        <PipelineStep tone="develop" number="01" title="Ingest" description="Parse PDFs, extrae texto, chunkifica." />
        <PipelineStep tone="preview" number="02" title="Generate" description="Q&A sintéticas con LLM OpenAI‑compatible." />
        <PipelineStep tone="ship" number="03" title="Ship" description="Judge + curate, exporta JSONL listo para fine‑tune." />
      </section>

      {/* Provider */}
      <section className="space-y-6">
        <SectionHeader eyebrow="02" title="Proveedor" link={{ to: "/settings", label: "Configurar" }} />
        <div className="rounded-lg bg-card p-6 shadow-card">
          <ApiKeyCard compact />
        </div>
      </section>

      {/* Jobs */}
      <section className="space-y-6">
        <SectionHeader eyebrow="03" title="Corridas recientes" link={{ to: "/new", label: "Crear nueva" }} />
        {isLoading ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 3 }).map((_, idx) => (
              <Skeleton key={idx} className="h-40 rounded-lg" />
            ))}
          </div>
        ) : jobs && jobs.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {jobs.map((job) => (
              <JobCard key={job.job_id} job={job} />
            ))}
          </div>
        ) : (
          <div className="rounded-lg bg-card p-12 text-center shadow-card">
            <p className="text-sm text-muted-foreground">Todavía no hay corridas.</p>
            <Button asChild className="mt-4">
              <Link to="/new">Iniciar primera corrida</Link>
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}

function SectionHeader({
  eyebrow,
  title,
  link,
}: {
  eyebrow: string;
  title: string;
  link?: { to: string; label: string };
}) {
  return (
    <div className="flex items-baseline justify-between">
      <div className="flex items-baseline gap-4">
        <span className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
          {eyebrow}
        </span>
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
      </div>
      {link ? (
        <Link
          to={link.to}
          className="text-[13px] text-muted-foreground transition-colors hover:text-foreground"
        >
          {link.label} →
        </Link>
      ) : null}
    </div>
  );
}

function PipelineStep({
  tone,
  number,
  title,
  description,
}: {
  tone: "develop" | "preview" | "ship";
  number: string;
  title: string;
  description: string;
}) {
  const colorClass =
    tone === "develop"
      ? "text-workflow-develop"
      : tone === "preview"
        ? "text-workflow-preview"
        : "text-workflow-ship";
  return (
    <div className="group rounded-lg bg-card p-6 shadow-card transition-shadow hover:shadow-card-hover">
      <div className="flex items-center gap-3">
        <span className={`font-geist-mono text-[11px] font-medium uppercase tracking-[0.15em] ${colorClass}`}>
          {number}
        </span>
        <span className="h-px flex-1 bg-border" />
      </div>
      <h3 className="mt-4 text-lg font-semibold tracking-tight">{title}</h3>
      <p className="mt-2 text-[13px] leading-[1.6] text-muted-foreground">{description}</p>
    </div>
  );
}
