import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { CreateJobInput } from "@/lib/types";

const QUALITY_PRESETS = {
  strict: { label: "Strict (0.85)", threshold: 0.85 },
  balanced: { label: "Balanceado (0.70)", threshold: 0.7 },
  permissive: { label: "Permisivo (0.55)", threshold: 0.55 },
} as const;

interface Props {
  values: CreateJobInput;
  onChange: (partial: Partial<CreateJobInput>) => void;
}

export function AdvancedOptions({ values, onChange }: Props) {
  return (
    <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
      <Field label="Parser">
        <Select
          value={values.parser_mode}
          onValueChange={(value) => onChange({ parser_mode: value as CreateJobInput["parser_mode"] })}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="auto">Auto (Docling)</SelectItem>
            <SelectItem value="fast">Rápido (PyMuPDF)</SelectItem>
            <SelectItem value="ocr_safe">OCR‑safe</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      <Field label="Perfil">
        <Select
          value={values.resource_profile}
          onValueChange={(value) =>
            onChange({ resource_profile: value as CreateJobInput["resource_profile"] })
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="low">Bajo</SelectItem>
            <SelectItem value="balanced">Balanceado</SelectItem>
            <SelectItem value="throughput">Máximo</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      <Field label="Workers generación">
        <Input
          type="number"
          min={1}
          max={16}
          value={values.generation_workers}
          onChange={(event) => onChange({ generation_workers: Math.max(1, Number(event.target.value) || 1) })}
        />
      </Field>
      <Field label="Workers judge">
        <Input
          type="number"
          min={1}
          max={8}
          value={values.judge_workers}
          onChange={(event) => onChange({ judge_workers: Math.max(1, Number(event.target.value) || 1) })}
        />
      </Field>
      <Field label="Páginas por lote">
        <Input
          type="number"
          min={1}
          value={values.page_batch_size}
          onChange={(event) => onChange({ page_batch_size: Math.max(1, Number(event.target.value) || 1) })}
        />
      </Field>
      <Field label="Pausa (s)">
        <Input
          type="number"
          min={0}
          step="0.5"
          value={values.batch_pause_seconds}
          onChange={(event) => onChange({ batch_pause_seconds: Math.max(0, Number(event.target.value) || 0) })}
        />
      </Field>
      <Field label="Q&A por chunk">
        <Input
          type="number"
          min={1}
          max={20}
          value={values.targets_per_chunk}
          onChange={(event) => onChange({ targets_per_chunk: Math.max(1, Number(event.target.value) || 1) })}
        />
      </Field>
      <Field label="Máx. PDFs">
        <Input
          type="number"
          min={1}
          placeholder="Todos"
          value={values.max_pdfs ?? ""}
          onChange={(event) =>
            onChange({ max_pdfs: event.target.value ? Math.max(1, Number(event.target.value) || 1) : null })
          }
        />
      </Field>
      <Field label="Máx. páginas/chunk">
        <Input
          type="number"
          min={1}
          value={values.max_pages_per_chunk ?? 25}
          onChange={(event) => onChange({ max_pages_per_chunk: Math.max(1, Number(event.target.value) || 1) })}
        />
      </Field>
      <Field label="Calidad">
        <Select
          value={values.quality_preset ?? "balanced"}
          onValueChange={(value) =>
            onChange({
              quality_preset: value as CreateJobInput["quality_preset"],
              min_groundedness_score: null,
              min_overall_score: null,
            })
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(QUALITY_PRESETS).map(([value, preset]) => (
              <SelectItem key={value} value={value}>
                {preset.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label="Groundedness mínima">
        <Input
          type="number"
          min={0}
          max={1}
          step="0.05"
          value={values.min_groundedness_score ?? QUALITY_PRESETS[values.quality_preset ?? "balanced"].threshold}
          onChange={(event) => onChange({ min_groundedness_score: Number(event.target.value) || 0 })}
        />
      </Field>
      <Field label="Overall mínimo">
        <Input
          type="number"
          min={0}
          max={1}
          step="0.05"
          value={values.min_overall_score ?? QUALITY_PRESETS[values.quality_preset ?? "balanced"].threshold}
          onChange={(event) => onChange({ min_overall_score: Number(event.target.value) || 0 })}
        />
      </Field>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-2">
      <span className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}
