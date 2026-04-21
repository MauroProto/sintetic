import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useExamples } from "@/hooks/useExamples";
import type { ExampleWithMeta } from "@/lib/types";
import { cn, truncate } from "@/lib/utils";

const KIND_OPTIONS = [
  { value: "__all__", label: "Todos" },
  { value: "extractive", label: "Extractivo" },
  { value: "inferential", label: "Inferencial" },
  { value: "unanswerable", label: "No responsable" },
  { value: "multi_chunk", label: "Multi‑chunk" },
  { value: "format_specific", label: "Formato" },
];

export function ExampleViewer({ jobId }: { jobId: string }) {
  const [split, setSplit] = useState("train");
  const [accepted, setAccepted] = useState<"all" | "yes" | "no">("yes");
  const [kind, setKind] = useState<string>("__all__");
  const [scoreMin, setScoreMin] = useState<number>(0);
  const [selected, setSelected] = useState<ExampleWithMeta | null>(null);

  const { data, isLoading } = useExamples(jobId, {
    split,
    accepted: accepted === "all" ? null : accepted === "yes",
    kind: kind === "__all__" ? undefined : kind,
    score_min: scoreMin > 0 ? scoreMin : undefined,
    limit: 100,
  });

  const availableSplits = data?.available_splits ?? [];

  return (
    <div className="space-y-8">
      <div className="grid gap-6 border-t border-border pt-8 md:grid-cols-4">
        <Field label="Split">
          <Select value={split} onValueChange={setSplit}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {(availableSplits.length ? availableSplits : ["train", "eval"]).map((s) => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Estado">
          <Select value={accepted} onValueChange={(value) => setAccepted(value as "all" | "yes" | "no")}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todos</SelectItem>
              <SelectItem value="yes">Aceptados</SelectItem>
              <SelectItem value="no">Rechazados</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field label="Tipo">
          <Select value={kind} onValueChange={setKind}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {KIND_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Score mínimo">
          <Input
            type="number"
            min={0}
            max={1}
            step="0.05"
            value={scoreMin}
            onChange={(event) => setScoreMin(Number(event.target.value) || 0)}
          />
        </Field>
      </div>

      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-[0.25em] text-muted-foreground">
          {isLoading
            ? "Cargando"
            : `${data?.items.length ?? 0} de ${data?.total ?? 0}`}
        </span>
      </div>

      <ScrollArea className="max-h-[640px]">
        <ul className="divide-y divide-border">
          {data?.items.map((item) => (
            <li key={`${item.example_id}-${item.accepted}-${item.split}`}>
              <button
                onClick={() => setSelected(item)}
                className="grid w-full grid-cols-[auto_1fr] gap-6 py-6 text-left transition-colors hover:bg-muted/30 lg:grid-cols-[auto_1fr_auto] lg:gap-10"
              >
                <span
                  className={cn(
                    "mt-2 h-1.5 w-1.5 rounded-full",
                    item.accepted ? "bg-success" : "bg-destructive",
                  )}
                />
                <div className="min-w-0 space-y-2">
                  <p className="text-[15px] leading-snug">{item.question}</p>
                  <p className="text-[13px] text-muted-foreground">{truncate(item.answer, 200)}</p>
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                    <span className="uppercase tracking-[0.2em]">{item.question_type}</span>
                    <span>·</span>
                    <span>{item.difficulty}</span>
                    {!item.accepted && item.reason ? (
                      <>
                        <span>·</span>
                        <span className="text-destructive">{item.reason}</span>
                      </>
                    ) : null}
                  </div>
                </div>
                {item.judge_score ? (
                  <span className="mono text-lg tabular-nums text-muted-foreground lg:block">
                    {(item.judge_score.overall ?? 0).toFixed(2)}
                  </span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
        {!isLoading && data?.items.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted-foreground">
            Ningún ejemplo para este filtro.
          </p>
        ) : null}
      </ScrollArea>

      <Dialog open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-w-3xl">
          {selected ? (
            <>
              <DialogHeader>
                <DialogTitle className="hairline text-2xl">{selected.question}</DialogTitle>
                <DialogDescription className="mono">
                  {selected.source_doc} · pp. {selected.page_range[0]}–{selected.page_range[1]}
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-6 text-sm">
                <div className="flex flex-wrap gap-2">
                  <Badge variant={selected.accepted ? "success" : "destructive"}>
                    {selected.accepted ? "aceptado" : `rechazado · ${selected.reason ?? ""}`}
                  </Badge>
                  <Badge variant="outline">{selected.question_type}</Badge>
                  <Badge variant="outline">{selected.difficulty}</Badge>
                </div>
                <section>
                  <p className="text-[11px] uppercase tracking-[0.25em] text-muted-foreground">Respuesta</p>
                  <p className="mt-2 whitespace-pre-wrap leading-relaxed">{selected.answer}</p>
                </section>
                {selected.evidence.length ? (
                  <section>
                    <p className="text-[11px] uppercase tracking-[0.25em] text-muted-foreground">Evidencia</p>
                    <ul className="mt-2 space-y-2">
                      {selected.evidence.map((piece, index) => (
                        <li key={index} className="border-l-2 border-border pl-4 text-[13px] leading-relaxed text-muted-foreground">
                          {piece}
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}
                {selected.judge_score ? (
                  <section className="space-y-2">
                    <p className="text-[11px] uppercase tracking-[0.25em] text-muted-foreground">Scores</p>
                    <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
                      {(["relevance", "groundedness", "format", "difficulty", "overall"] as const).map((key) => (
                        <div key={key} className="flex flex-col gap-1">
                          <span className="text-[11px] text-muted-foreground">{key}</span>
                          <span className="mono text-lg tabular-nums">{selected.judge_score![key].toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                    {selected.judge_score.rationale ? (
                      <p className="mt-3 text-[13px] italic text-muted-foreground">{selected.judge_score.rationale}</p>
                    ) : null}
                  </section>
                ) : null}
              </div>
              <div className="flex justify-end">
                <Button variant="outline" onClick={() => setSelected(null)}>Cerrar</Button>
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-2">
      <span className="text-[11px] uppercase tracking-[0.25em] text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}
