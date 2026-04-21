import { useEffect, useMemo, useState } from "react";
import { FileText, FolderOpen } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { usePdfs } from "@/hooks/usePdfs";
import { cn, formatDate, formatNumber } from "@/lib/utils";

interface Props {
  sourceDir: string;
  selected: string[] | null;
  onChange: (next: string[] | null) => void;
}

/**
 * selected === null  → "all" (no filtering, default)
 * selected === []    → none (blocks submit)
 * selected === [...] → subset
 */
export function PdfSelector({ sourceDir, selected, onChange }: Props) {
  const { data, isLoading, isError } = usePdfs(sourceDir);
  const [open, setOpen] = useState(false);

  const items = useMemo(() => data?.items ?? [], [data?.items]);
  const totalCount = items.length;

  const selectedSet = useMemo(() => {
    if (selected === null) return new Set(items.map((i) => i.path));
    return new Set(selected);
  }, [selected, items]);

  const selectedCount = selectedSet.size;
  const allSelected = selected === null || selectedCount === totalCount;
  const noneSelected = totalCount > 0 && selectedCount === 0;

  // Clean up selections when source changes
  useEffect(() => {
    if (!data?.ok) return;
    if (selected !== null) {
      const validPaths = new Set(items.map((i) => i.path));
      const filtered = selected.filter((p) => validPaths.has(p));
      if (filtered.length !== selected.length) {
        onChange(filtered.length === items.length ? null : filtered);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.ok, items.length]);

  if (!sourceDir.trim() || isError) return null;
  if (isLoading && !data) {
    return (
      <p className="font-geist-mono text-[11px] text-muted-foreground">Buscando PDFs...</p>
    );
  }
  if (!data?.ok || totalCount === 0) return null;

  function togglePath(path: string, next: boolean) {
    const current = selected === null ? items.map((i) => i.path) : selected;
    let updated: string[];
    if (next) {
      updated = Array.from(new Set([...current, path]));
    } else {
      updated = current.filter((p) => p !== path);
    }
    onChange(updated.length === totalCount ? null : updated);
  }

  function selectAll() {
    onChange(null);
  }
  function selectNone() {
    onChange([]);
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setOpen((prev) => !prev)}
            className="inline-flex items-center gap-2 font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground transition-colors hover:text-foreground"
          >
            <FolderOpen className="h-3.5 w-3.5" />
            Archivos detectados
            <span
              className={cn(
                "transition-transform",
                open ? "rotate-90" : "rotate-0",
              )}
            >
              ›
            </span>
          </button>
          <span className="text-[12px]">
            {allSelected ? (
              <span className="text-muted-foreground">
                {totalCount} PDF{totalCount === 1 ? "" : "s"} · todos incluidos
              </span>
            ) : noneSelected ? (
              <span className="text-destructive">Ninguno seleccionado</span>
            ) : (
              <span className="text-foreground">
                {selectedCount} de {totalCount} incluidos
              </span>
            )}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px]">
          <button
            type="button"
            onClick={selectAll}
            disabled={allSelected}
            className="text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
          >
            Seleccionar todos
          </button>
          <span className="text-border">·</span>
          <button
            type="button"
            onClick={selectNone}
            disabled={noneSelected}
            className="text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
          >
            Ninguno
          </button>
        </div>
      </div>

      {open ? (
        <div className="rounded-md bg-secondary/50 shadow-border-light">
          <ScrollArea className="max-h-64">
            <ul className="divide-y divide-border">
              {items.map((item) => {
                const checked = selectedSet.has(item.path);
                return (
                  <li key={item.path}>
                    <label
                      className={cn(
                        "flex cursor-pointer items-center gap-3 px-3 py-2 transition-colors hover:bg-background",
                        !checked && "opacity-60",
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(event) => togglePath(item.path, event.target.checked)}
                        className="h-3.5 w-3.5 shrink-0 cursor-pointer accent-foreground"
                      />
                      <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                        <span className="truncate font-geist-mono text-[12px]">{item.path}</span>
                        <span className="shrink-0 font-geist-mono text-[10px] text-muted-foreground">
                          {formatNumber(item.size)} B · {formatDate(item.modified_at)}
                        </span>
                      </div>
                    </label>
                  </li>
                );
              })}
            </ul>
          </ScrollArea>
        </div>
      ) : null}
    </div>
  );
}
