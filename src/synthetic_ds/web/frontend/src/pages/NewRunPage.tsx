import { Badge } from "@/components/ui/badge";
import { NewRunForm } from "@/components/newrun/NewRunForm";

export function NewRunPage() {
  return (
    <div className="space-y-14">
      <header className="space-y-6">
        <div className="flex items-center gap-3">
          <Badge>Nueva corrida</Badge>
          <span className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
            Paso 1 · Setup
          </span>
        </div>
        <h1 className="text-[clamp(36px,5vw,56px)] font-semibold leading-[1.05] tracking-tightest">
          Apuntá a una carpeta.
          <br />
          <span className="text-muted-foreground">El pipeline hace el resto.</span>
        </h1>
        <p className="max-w-xl text-[16px] leading-[1.6] text-muted-foreground">
          Los resultados quedan en{" "}
          <code className="rounded bg-secondary px-1.5 py-0.5 font-geist-mono text-[13px]">
            extraccion_dataset/
          </code>{" "}
          junto a la fuente.
        </p>
      </header>
      <NewRunForm />
    </div>
  );
}
