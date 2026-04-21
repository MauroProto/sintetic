import { useMemo, useState } from "react";
import { CheckCheck, Filter, Pencil, Search, Trash2, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useToast } from "@/components/ui/toast";
import { useDashboardExamples, useExampleMutations } from "@/hooks/useDashboardExamples";
import { ExampleEditor } from "@/components/examples/ExampleEditor";
import type { DashboardExampleItem } from "@/lib/types";
import { cn, truncate } from "@/lib/utils";

const KIND_OPTIONS = [
  { value: "__all__", label: "Todos" },
  { value: "extractive", label: "Extractivo" },
  { value: "inferential", label: "Inferencial" },
  { value: "unanswerable", label: "No responsable" },
  { value: "multi_chunk", label: "Multi‑chunk" },
  { value: "format_specific", label: "Formato" },
];

export function DatasetDashboardPage() {
  const [accepted, setAccepted] = useState<"all" | "yes" | "no">("all");
  const [kind, setKind] = useState("__all__");
  const [scoreMin, setScoreMin] = useState(0);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<DashboardExampleItem | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sortBy, setSortBy] = useState<"score" | "job" | "type">("score");

  const { toast } = useToast();
  const { accept, reject, remove } = useExampleMutations();

  const query = useDashboardExamples({
    accepted: accepted === "all" ? null : accepted === "yes",
    kind: kind === "__all__" ? undefined : kind,
    score_min: scoreMin > 0 ? scoreMin : undefined,
    search: search.trim() || undefined,
    limit: 200,
  });

  const items = useMemo(() => {
    const base = query.data?.items ?? [];
    const copy = [...base];
    if (sortBy === "score") {
      copy.sort((a, b) => (b.judge_score?.overall ?? 0) - (a.judge_score?.overall ?? 0));
    } else if (sortBy === "job") {
      copy.sort((a, b) => a.job_id.localeCompare(b.job_id));
    } else if (sortBy === "type") {
      copy.sort((a, b) => (a.question_type ?? "").localeCompare(b.question_type ?? ""));
    }
    return copy;
  }, [query.data?.items, sortBy]);

  const aggregate = query.data?.aggregate;
  const avgScore = aggregate?.avg_score ?? 0;
  const types = aggregate?.types ?? {};
  const totalShown = items.length;

  function toggleSelection(key: string) {
    const next = new Set(selected);
    next.has(key) ? next.delete(key) : next.add(key);
    setSelected(next);
  }

  function clearSelection() {
    setSelected(new Set());
  }

  const selectedList = useMemo(() => {
    const map = new Map(items.map((item) => [`${item.job_id}:${item.example_id}:${item.split}`, item]));
    return [...selected].map((key) => map.get(key)).filter((v): v is DashboardExampleItem => !!v);
  }, [selected, items]);

  async function bulkAccept() {
    for (const item of selectedList) {
      if (!item.accepted) {
        await accept.mutateAsync({ jobId: item.job_id, exampleId: item.example_id, split: item.split });
      }
    }
    toast({ variant: "success", title: `Aceptados: ${selectedList.length}` });
    clearSelection();
  }
  async function bulkReject() {
    for (const item of selectedList) {
      if (item.accepted) {
        await reject.mutateAsync({ jobId: item.job_id, exampleId: item.example_id, split: item.split });
      }
    }
    toast({ variant: "info", title: `Rechazados: ${selectedList.length}` });
    clearSelection();
  }
  async function bulkDelete() {
    for (const item of selectedList) {
      await remove.mutateAsync({ jobId: item.job_id, exampleId: item.example_id, split: item.split });
    }
    toast({ variant: "info", title: `Eliminados: ${selectedList.length}` });
    clearSelection();
  }

  function exportSelected() {
    if (selectedList.length === 0) return;
    const jsonl = selectedList
      .map((item) =>
        JSON.stringify({
          example_id: item.example_id,
          job_id: item.job_id,
          split: item.split,
          accepted: item.accepted,
          question_type: item.question_type,
          difficulty: item.difficulty,
          is_answerable: item.is_answerable,
          question: item.question,
          answer: item.answer,
          evidence: item.evidence,
          judge_score: item.judge_score,
          source_doc: item.source_doc,
          page_range: item.page_range,
        }),
      )
      .join("\n");
    const blob = new Blob([jsonl], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `selection-${Date.now()}.jsonl`;
    a.click();
    URL.revokeObjectURL(url);
    toast({ variant: "info", title: `Descargados ${selectedList.length} ejemplos` });
  }

  return (
    <div className="space-y-10">
      <header className="space-y-4">
        <Badge>Dataset dashboard</Badge>
        <h1 className="text-[clamp(36px,5vw,52px)] font-semibold leading-[1.05] tracking-tightest">
          Todos los Q&A, en un solo lugar.
        </h1>
        <p className="max-w-2xl text-[15px] leading-[1.6] text-muted-foreground">
          Consolidado editable de todos los ejemplos generados. Buscá, filtrá,
          editá o cambiá el estado de cualquier Q&A y el <code className="mono rounded bg-secondary px-1 py-0.5 text-[12px]">train.jsonl</code> se
          regenera automáticamente.
        </p>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
        <StatCard label="Ejemplos" value={String(query.data?.total ?? 0)} />
        <StatCard label="Score promedio" value={avgScore.toFixed(2)} />
        <StatCard
          label="Tipos"
          value={String(Object.keys(types).length || 0)}
          hint={Object.entries(types)
            .map(([k, v]) => `${k}:${v}`)
            .slice(0, 3)
            .join(" · ")}
        />
        <StatCard
          label="Jobs con output"
          value={String(Object.keys(aggregate?.per_job ?? {}).length)}
        />
      </section>

      <section className="space-y-4">
        <div className="grid gap-3 md:grid-cols-[1.4fr_auto_auto_auto_auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Buscar en pregunta, respuesta o archivo..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="pl-9"
            />
          </div>
          <Select value={accepted} onValueChange={(value) => setAccepted(value as "all" | "yes" | "no")}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todos</SelectItem>
              <SelectItem value="yes">Aceptados</SelectItem>
              <SelectItem value="no">Rechazados</SelectItem>
            </SelectContent>
          </Select>
          <Select value={kind} onValueChange={setKind}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {KIND_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={sortBy} onValueChange={(v) => setSortBy(v as "score" | "job" | "type")}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="score">Ordenar por score</SelectItem>
              <SelectItem value="job">Ordenar por job</SelectItem>
              <SelectItem value="type">Ordenar por tipo</SelectItem>
            </SelectContent>
          </Select>
          <Input
            type="number"
            min={0}
            max={1}
            step="0.05"
            value={scoreMin}
            onChange={(event) => setScoreMin(Number(event.target.value) || 0)}
            className="w-24"
            title="Score mínimo"
          />
        </div>

        {selected.size > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-secondary px-4 py-2 shadow-border-light">
            <span className="text-[13px]">
              {selected.size} seleccionado{selected.size > 1 ? "s" : ""}
            </span>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={bulkAccept}>
                <CheckCheck className="h-3.5 w-3.5" /> Aceptar
              </Button>
              <Button size="sm" variant="outline" onClick={bulkReject}>
                <Filter className="h-3.5 w-3.5" /> Rechazar
              </Button>
              <Button size="sm" variant="outline" onClick={exportSelected}>
                Exportar JSONL
              </Button>
              <Button size="sm" variant="ghost" onClick={bulkDelete} className="text-destructive">
                <Trash2 className="h-3.5 w-3.5" /> Borrar
              </Button>
              <Button size="sm" variant="ghost" onClick={clearSelection}>
                <X className="h-3.5 w-3.5" /> Limpiar
              </Button>
            </div>
          </div>
        ) : null}

        <div className="rounded-lg bg-card shadow-card">
          {query.isLoading ? (
            <div className="space-y-3 p-6">
              {Array.from({ length: 5 }).map((_, idx) => (
                <Skeleton key={idx} className="h-16 rounded-md" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <p className="p-12 text-center text-sm text-muted-foreground">
              Sin ejemplos para estos filtros. Cambiá los criterios o creá una corrida nueva.
            </p>
          ) : (
            <ScrollArea className="max-h-[70vh]">
              <ul className="divide-y divide-border">
                {items.map((item) => {
                  const key = `${item.job_id}:${item.example_id}:${item.split}`;
                  const checked = selected.has(key);
                  const score = item.judge_score?.overall ?? 0;
                  return (
                    <li
                      key={key}
                      className={cn(
                        "grid grid-cols-[auto_auto_1fr_auto_auto] items-start gap-4 px-5 py-3.5 transition-colors hover:bg-muted/40",
                        checked && "bg-secondary",
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleSelection(key)}
                        className="mt-1 h-3.5 w-3.5 cursor-pointer accent-foreground"
                      />
                      <div className="flex flex-col items-start gap-1">
                        <span
                          className={cn(
                            "h-1.5 w-1.5 rounded-full",
                            item.accepted ? "bg-success" : "bg-destructive",
                          )}
                        />
                        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
                          {item.split}
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => setEditing(item)}
                        className="flex min-w-0 flex-col gap-1 text-left"
                      >
                        <p className="text-[14px] leading-snug">{item.question}</p>
                        <p className="text-[12px] text-muted-foreground">{truncate(item.answer, 180)}</p>
                        <div className="flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                          <span className="font-mono uppercase tracking-[0.1em]">{item.question_type}</span>
                          <span>·</span>
                          <span>{item.difficulty}</span>
                          <span>·</span>
                          <span className="font-mono">{truncate(item.source_doc, 26)}</span>
                          <span>·</span>
                          <span className="font-mono">{item.job_id.slice(0, 8)}</span>
                          {!item.accepted && item.reason ? (
                            <>
                              <span>·</span>
                              <span className="text-destructive">{item.reason}</span>
                            </>
                          ) : null}
                        </div>
                      </button>
                      <span className="mt-1 font-mono text-[13px] tabular-nums text-muted-foreground">
                        {score.toFixed(2)}
                      </span>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(item)}>
                        <Pencil className="h-3.5 w-3.5" /> Editar
                      </Button>
                    </li>
                  );
                })}
              </ul>
            </ScrollArea>
          )}
        </div>

        <p className="text-right font-mono text-[11px] text-muted-foreground">
          Mostrando {totalShown} · refresh cada 8s
        </p>
      </section>

      <ExampleEditor item={editing} onClose={() => setEditing(null)} />
    </div>
  );
}

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg bg-card p-5 shadow-card">
      <span className="font-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
        {label}
      </span>
      <span className="text-2xl font-semibold tabular-nums tracking-tight">{value}</span>
      {hint ? <span className="font-mono text-[11px] text-muted-foreground">{hint}</span> : null}
    </div>
  );
}
