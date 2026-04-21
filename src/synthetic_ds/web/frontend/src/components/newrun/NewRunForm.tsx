import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import type { CreateJobInput, SourceModeResult } from "@/lib/types";
import { FolderPickerField } from "./FolderPickerField";
import { SourceModeHint } from "./SourceModeHint";
import { AdvancedOptions } from "./AdvancedOptions";
import { PdfSelector } from "./PdfSelector";

const DEFAULT_VALUES: CreateJobInput = {
  source_dir: "",
  generate_eval: true,
  parser_mode: "auto",
  resource_profile: "low",
  generation_workers: 2,
  judge_workers: 1,
  page_batch_size: 100,
  batch_pause_seconds: 2,
  targets_per_chunk: 3,
  included_files: null,
};

export function NewRunForm() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [values, setValues] = useState<CreateJobInput>(DEFAULT_VALUES);
  const [sourceMode, setSourceMode] = useState<SourceModeResult | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    if (!values.source_dir.trim()) {
      setSourceMode(null);
      return;
    }
    let cancelled = false;
    setSourceLoading(true);
    const handle = setTimeout(() => {
      api
        .getSourceMode(values.source_dir.trim())
        .then((result) => !cancelled && setSourceMode(result))
        .catch(() => {
          if (!cancelled)
            setSourceMode({
              ok: false,
              pdf_count: 0,
              dataset_mode: null,
              label: null,
              message: "No se pudo inspeccionar la carpeta.",
            });
        })
        .finally(() => !cancelled && setSourceLoading(false));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [values.source_dir]);

  const canSubmit = useMemo(() => {
    if (!values.source_dir.trim() || !sourceMode?.ok) return false;
    if (values.included_files !== null && values.included_files !== undefined && values.included_files.length === 0) {
      return false;
    }
    return true;
  }, [values.source_dir, values.included_files, sourceMode]);

  const mutation = useMutation({
    mutationFn: (input: CreateJobInput) => api.createJob(input),
    onSuccess: (data) => {
      toast({ variant: "success", title: "Corrida iniciada", description: data.note });
      navigate(`/runs/${data.job_id}`);
    },
    onError: (error) => {
      toast({ variant: "error", title: "No se pudo iniciar", description: (error as Error).message });
    },
  });

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    mutation.mutate({ ...values, source_dir: values.source_dir.trim() });
  }

  function update(partial: Partial<CreateJobInput>) {
    setValues((prev) => ({ ...prev, ...partial }));
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <section className="rounded-lg bg-card p-6 shadow-card">
        <div className="mb-6 flex items-baseline justify-between">
          <div className="flex items-baseline gap-4">
            <span className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
              01
            </span>
            <h2 className="text-lg font-semibold tracking-tight">Fuente</h2>
          </div>
        </div>
        <div className="space-y-4">
          <FolderPickerField value={values.source_dir} onChange={(source_dir) => update({ source_dir, included_files: null })} />
          <SourceModeHint result={sourceMode} loading={sourceLoading} />
          {sourceMode?.ok ? (
            <PdfSelector
              sourceDir={values.source_dir}
              selected={values.included_files ?? null}
              onChange={(included_files) => update({ included_files })}
            />
          ) : null}
        </div>
      </section>

      <section className="rounded-lg bg-card p-6 shadow-card">
        <div className="mb-6 flex items-baseline justify-between">
          <div className="flex items-baseline gap-4">
            <span className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
              02
            </span>
            <h2 className="text-lg font-semibold tracking-tight">Opciones</h2>
          </div>
        </div>

        <div className="flex items-start justify-between gap-6">
          <div>
            <p className="text-[14px] font-medium">Generar split eval</p>
            <p className="mt-1 max-w-sm text-[12px] text-muted-foreground">
              Solo aplica cuando hay múltiples documentos. En single‑document se ignora.
            </p>
          </div>
          <Switch
            checked={values.generate_eval}
            onCheckedChange={(generate_eval) => update({ generate_eval })}
          />
        </div>

        <div className="mt-6">
          <button
            type="button"
            onClick={() => setShowAdvanced((prev) => !prev)}
            className="text-[13px] text-muted-foreground transition-colors hover:text-foreground"
          >
            {showAdvanced ? "− Ocultar" : "+ Mostrar"} opciones avanzadas
          </button>

          {showAdvanced ? (
            <div className="mt-6 border-t border-border pt-6">
              <AdvancedOptions values={values} onChange={update} />
            </div>
          ) : null}
        </div>
      </section>

      <div className="flex items-center justify-between">
        <p className="font-geist-mono text-[11px] text-muted-foreground">
          Output: <code className="rounded bg-secondary px-1.5 py-0.5">extraccion_dataset/</code>
        </p>
        <Button type="submit" size="lg" disabled={!canSubmit || mutation.isPending}>
          {mutation.isPending ? "Iniciando..." : "Iniciar corrida"}
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </form>
  );
}
