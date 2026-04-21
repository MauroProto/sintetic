import { Badge } from "@/components/ui/badge";
import { ConfigEditor } from "@/components/config/ConfigEditor";
import { ApiKeyCard } from "@/components/provider/ApiKeyCard";

export function SettingsPage() {
  return (
    <div className="space-y-14">
      <header className="space-y-6">
        <Badge>Configuración</Badge>
        <h1 className="text-[clamp(36px,5vw,56px)] font-semibold leading-[1.05] tracking-tightest">
          Ajustes del proyecto.
        </h1>
      </header>

      <section className="space-y-6">
        <div className="flex items-baseline gap-4">
          <span className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
            Proveedor
          </span>
          <h2 className="text-xl font-semibold tracking-tight">LLM activo</h2>
        </div>
        <div className="rounded-lg bg-card p-6 shadow-card">
          <ApiKeyCard />
        </div>
      </section>

      <section className="space-y-6">
        <div className="flex items-baseline gap-4">
          <span className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
            synthetic‑ds.yaml
          </span>
          <h2 className="text-xl font-semibold tracking-tight">Pipeline</h2>
        </div>
        <div className="rounded-lg bg-card p-6 shadow-card">
          <ConfigEditor />
        </div>
      </section>
    </div>
  );
}
