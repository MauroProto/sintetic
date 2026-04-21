import { useEffect, useState } from "react";
import { Check, CheckCheck, Trash2, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { useExampleMutations } from "@/hooks/useDashboardExamples";
import type { DashboardExampleItem } from "@/lib/types";

interface Props {
  item: DashboardExampleItem | null;
  onClose: () => void;
}

const KIND_OPTIONS = [
  "extractive",
  "inferential",
  "unanswerable",
  "multi_chunk",
  "format_specific",
] as const;

const DIFFICULTY_OPTIONS = ["easy", "medium", "hard", "low", "high"] as const;

export function ExampleEditor({ item, onClose }: Props) {
  const { toast } = useToast();
  const { patch, accept, reject, remove } = useExampleMutations();

  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [evidenceText, setEvidenceText] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [questionType, setQuestionType] = useState("extractive");
  const [difficulty, setDifficulty] = useState("medium");
  const [isAnswerable, setIsAnswerable] = useState(true);

  useEffect(() => {
    if (!item) return;
    setQuestion(item.question ?? "");
    setAnswer(item.answer ?? "");
    setEvidenceText((item.evidence ?? []).join("\n\n"));
    setReasoning(item.reasoning ?? "");
    setQuestionType(item.question_type ?? "extractive");
    setDifficulty(item.difficulty ?? "medium");
    setIsAnswerable(!!item.is_answerable);
  }, [item]);

  if (!item) return null;

  const split = item.split;

  async function save() {
    if (!item) return;
    await patch.mutateAsync({
      jobId: item.job_id,
      exampleId: item.example_id,
      split,
      patch: {
        question,
        answer,
        evidence: evidenceText
          .split(/\n\n+/)
          .map((e) => e.trim())
          .filter(Boolean),
        reasoning: reasoning.trim() || null,
        question_type: questionType,
        difficulty,
        is_answerable: isAnswerable,
      },
    });
    toast({ variant: "success", title: "Cambios guardados" });
    onClose();
  }

  async function toggleStatus() {
    if (!item) return;
    if (item.accepted) {
      await reject.mutateAsync({ jobId: item.job_id, exampleId: item.example_id, split });
      toast({ variant: "info", title: "Ejemplo marcado como rechazado" });
    } else {
      await accept.mutateAsync({ jobId: item.job_id, exampleId: item.example_id, split });
      toast({ variant: "success", title: "Ejemplo aceptado" });
    }
    onClose();
  }

  async function handleDelete() {
    if (!item) return;
    await remove.mutateAsync({ jobId: item.job_id, exampleId: item.example_id, split });
    toast({ variant: "info", title: "Ejemplo eliminado" });
    onClose();
  }

  const pending = patch.isPending || accept.isPending || reject.isPending || remove.isPending;

  return (
    <Dialog open={!!item} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <Badge variant={item.accepted ? "success" : "destructive"}>
              {item.accepted ? "aceptado" : `rechazado · ${item.reason ?? ""}`}
            </Badge>
            <Badge variant="outline">{split}</Badge>
            <Badge variant="muted" className="font-mono text-[10px]">
              {item.example_id}
            </Badge>
          </div>
          <DialogTitle className="mt-2 text-base font-medium leading-snug">
            Editar ejemplo
          </DialogTitle>
          <DialogDescription className="font-mono text-xs">
            {item.source_doc} · pp. {item.page_range?.[0]}–{item.page_range?.[1]} · job {item.job_id}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 text-sm">
          <label className="flex flex-col gap-2">
            <span className="text-[11px] font-medium uppercase tracking-[0.15em] text-muted-foreground">
              Pregunta
            </span>
            <Textarea
              rows={2}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              className="resize-none"
            />
          </label>

          <label className="flex flex-col gap-2">
            <span className="text-[11px] font-medium uppercase tracking-[0.15em] text-muted-foreground">
              Respuesta
            </span>
            <Textarea
              rows={3}
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
            />
          </label>

          <label className="flex flex-col gap-2">
            <span className="text-[11px] font-medium uppercase tracking-[0.15em] text-muted-foreground">
              Evidencia (separá con doble salto de línea)
            </span>
            <Textarea
              rows={4}
              value={evidenceText}
              onChange={(event) => setEvidenceText(event.target.value)}
              className="font-mono text-[12px]"
            />
          </label>

          <label className="flex flex-col gap-2">
            <span className="text-[11px] font-medium uppercase tracking-[0.15em] text-muted-foreground">
              Razonamiento (opcional)
            </span>
            <Textarea
              rows={2}
              value={reasoning}
              onChange={(event) => setReasoning(event.target.value)}
            />
          </label>

          <div className="grid gap-4 md:grid-cols-3">
            <label className="flex flex-col gap-2">
              <span className="text-[11px] font-medium uppercase tracking-[0.15em] text-muted-foreground">
                Tipo
              </span>
              <Select value={questionType} onValueChange={setQuestionType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {KIND_OPTIONS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {value}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <label className="flex flex-col gap-2">
              <span className="text-[11px] font-medium uppercase tracking-[0.15em] text-muted-foreground">
                Dificultad
              </span>
              <Select value={difficulty} onValueChange={setDifficulty}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DIFFICULTY_OPTIONS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {value}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <label className="flex items-center justify-between gap-3 rounded-md bg-secondary px-3 shadow-border-light">
              <span className="text-[12px]">Responsable</span>
              <Switch checked={isAnswerable} onCheckedChange={setIsAnswerable} />
            </label>
          </div>

          {item.judge_score ? (
            <div className="rounded-md bg-secondary px-4 py-3 shadow-border-light">
              <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                Judge scores
              </p>
              <div className="mt-2 grid grid-cols-5 gap-3 font-mono text-[12px]">
                {(["relevance", "groundedness", "format", "difficulty", "overall"] as const).map((k) => (
                  <div key={k} className="flex flex-col">
                    <span className="text-[10px] text-muted-foreground">{k}</span>
                    <span>{(item.judge_score as any)[k]?.toFixed?.(2) ?? "-"}</span>
                  </div>
                ))}
              </div>
              {item.judge_score.rationale ? (
                <p className="mt-2 text-[11px] italic text-muted-foreground">
                  {item.judge_score.rationale}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="flex items-center justify-between border-t border-border pt-4">
          <Button
            variant="ghost"
            size="sm"
            disabled={pending}
            onClick={handleDelete}
            className="text-destructive hover:bg-destructive/10"
          >
            <Trash2 className="h-3.5 w-3.5" /> Eliminar
          </Button>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" disabled={pending} onClick={onClose}>
              <X className="h-3.5 w-3.5" /> Cancelar
            </Button>
            <Button variant="outline" size="sm" disabled={pending} onClick={toggleStatus}>
              <CheckCheck className="h-3.5 w-3.5" />
              {item.accepted ? "Mover a rechazados" : "Aceptar"}
            </Button>
            <Button size="sm" disabled={pending} onClick={save}>
              <Check className="h-3.5 w-3.5" />
              {pending ? "Guardando..." : "Guardar"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
