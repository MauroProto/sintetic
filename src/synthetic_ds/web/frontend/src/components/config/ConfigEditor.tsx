import { lazy, Suspense, useEffect, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useConfig, useSaveConfig } from "@/hooks/useConfig";
import type { ProjectConfig } from "@/lib/types";

const MonacoEditor = lazy(() => import("@monaco-editor/react"));

export function ConfigEditor() {
  const { data, isLoading } = useConfig();
  const saveConfig = useSaveConfig();
  const { toast } = useToast();

  const [config, setConfig] = useState<ProjectConfig | null>(null);
  const [yamlText, setYamlText] = useState<string>("");

  useEffect(() => {
    if (data) {
      setConfig(data.config);
      setYamlText(data.yaml);
    }
  }, [data]);

  if (isLoading || !config) return <Skeleton className="h-96" />;

  function updateSection<K extends keyof ProjectConfig>(section: K, partial: Partial<ProjectConfig[K]>) {
    setConfig((prev) => (prev ? { ...prev, [section]: { ...prev[section], ...partial } } : prev));
  }

  function handleSaveForm() {
    if (!config) return;
    saveConfig.mutate(
      { config },
      {
        onSuccess: () => toast({ variant: "success", title: "Configuración guardada" }),
        onError: (error) => toast({ variant: "error", title: "Error", description: (error as Error).message }),
      },
    );
  }

  function handleSaveYaml() {
    saveConfig.mutate(
      { yaml: yamlText },
      {
        onSuccess: () => toast({ variant: "success", title: "YAML guardado" }),
        onError: (error) => toast({ variant: "error", title: "YAML inválido", description: (error as Error).message }),
      },
    );
  }

  return (
    <Tabs defaultValue="form">
      <TabsList>
        <TabsTrigger value="form">Formulario</TabsTrigger>
        <TabsTrigger value="raw">YAML crudo</TabsTrigger>
      </TabsList>

      <TabsContent value="form" className="space-y-12">
        <Section title="Parsing">
          <div className="grid gap-6 md:grid-cols-3">
            <Field label="Parser primario">
              <Select
                value={config.parsing.primary_parser}
                onValueChange={(value) => updateSection("parsing", { primary_parser: value })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="docling">docling</SelectItem>
                  <SelectItem value="pymupdf">pymupdf</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="Fallback">
              <Select
                value={config.parsing.fallback_parser}
                onValueChange={(value) => updateSection("parsing", { fallback_parser: value })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="pymupdf">pymupdf</SelectItem>
                  <SelectItem value="docling">docling</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="DPI página">
              <Input
                type="number"
                value={config.parsing.page_image_dpi}
                onChange={(event) => updateSection("parsing", { page_image_dpi: Number(event.target.value) || 0 })}
              />
            </Field>
          </div>
          <div className="grid gap-6 pt-2 md:grid-cols-3">
            <Toggle
              label="OCR habilitado"
              checked={config.parsing.enable_ocr}
              onChange={(enable_ocr) => updateSection("parsing", { enable_ocr })}
            />
            <Toggle
              label="Render imágenes"
              checked={config.parsing.render_page_images}
              onChange={(render_page_images) => updateSection("parsing", { render_page_images })}
            />
            <Field label="Multimodal páginas/chunk">
              <Input
                type="number"
                value={config.parsing.multimodal_max_pages_per_chunk}
                onChange={(event) => updateSection("parsing", { multimodal_max_pages_per_chunk: Number(event.target.value) || 0 })}
              />
            </Field>
          </div>
        </Section>

        <Section title="Chunking">
          <div className="grid gap-6 md:grid-cols-3">
            <Field label="Estrategia">
              <Select
                value={config.chunking.strategy}
                onValueChange={(value) => updateSection("chunking", { strategy: value })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="semantic">semantic</SelectItem>
                  <SelectItem value="headings_first">headings_first</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="Target tokens">
              <Input
                type="number"
                value={config.chunking.target_tokens}
                onChange={(event) => updateSection("chunking", { target_tokens: Number(event.target.value) || 0 })}
              />
            </Field>
            <Field label="Overlap">
              <Input
                type="number"
                value={config.chunking.overlap}
                onChange={(event) => updateSection("chunking", { overlap: Number(event.target.value) || 0 })}
              />
            </Field>
          </div>
        </Section>

        <Section title="Generación">
          <div className="grid gap-6 md:grid-cols-3">
            <Field label="Perfil">
              <Select
                value={config.generation.resource_profile}
                onValueChange={(value) => updateSection("generation", { resource_profile: value })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="low">low</SelectItem>
                  <SelectItem value="balanced">balanced</SelectItem>
                  <SelectItem value="throughput">throughput</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="Workers generación">
              <Input
                type="number"
                value={config.generation.generation_workers ?? 2}
                onChange={(event) => updateSection("generation", { generation_workers: Math.max(1, Number(event.target.value) || 1) })}
              />
            </Field>
            <Field label="Workers judge">
              <Input
                type="number"
                value={config.generation.judge_workers ?? 1}
                onChange={(event) => updateSection("generation", { judge_workers: Math.max(1, Number(event.target.value) || 1) })}
              />
            </Field>
            <Field label="Page batch size">
              <Input
                type="number"
                value={config.generation.page_batch_size}
                onChange={(event) => updateSection("generation", { page_batch_size: Math.max(1, Number(event.target.value) || 1) })}
              />
            </Field>
            <Field label="Pausa (s)">
              <Input
                type="number"
                step="0.5"
                value={config.generation.batch_pause_seconds}
                onChange={(event) => updateSection("generation", { batch_pause_seconds: Math.max(0, Number(event.target.value) || 0) })}
              />
            </Field>
            <Field label="Retries">
              <Input
                type="number"
                value={config.generation.retries}
                onChange={(event) => updateSection("generation", { retries: Math.max(0, Number(event.target.value) || 0) })}
              />
            </Field>
          </div>
        </Section>

        <Section title="Filtros">
          <div className="grid gap-6 md:grid-cols-3">
            <Field label="Preset">
              <Select
                value={config.filters.preset}
                onValueChange={(value) => updateSection("filters", { preset: value })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="strict">Strict (0.85)</SelectItem>
                  <SelectItem value="balanced">Balanced (0.70)</SelectItem>
                  <SelectItem value="permissive">Permissive (0.55)</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="Groundedness threshold">
              <Input
                type="number"
                step="0.05"
                min={0}
                max={1}
                value={config.filters.groundedness_threshold}
                onChange={(event) => updateSection("filters", { groundedness_threshold: Number(event.target.value) || 0 })}
              />
            </Field>
            <Field label="Overall threshold">
              <Input
                type="number"
                step="0.05"
                min={0}
                max={1}
                value={config.filters.overall_threshold}
                onChange={(event) => updateSection("filters", { overall_threshold: Number(event.target.value) || 0 })}
              />
            </Field>
          </div>
        </Section>

        <div className="flex justify-end">
          <Button onClick={handleSaveForm} disabled={saveConfig.isPending}>
            {saveConfig.isPending ? "Guardando..." : "Guardar cambios"}
          </Button>
        </div>
      </TabsContent>

      <TabsContent value="raw" className="space-y-6">
        <div className="overflow-hidden rounded-md border border-border">
          <Suspense fallback={<Skeleton className="h-[520px] w-full" />}>
            <MonacoEditor
              height="520px"
              defaultLanguage="yaml"
              theme="vs-dark"
              value={yamlText}
              onChange={(value) => setYamlText(value ?? "")}
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                scrollBeyondLastLine: false,
                wordWrap: "on",
                fontFamily: "JetBrains Mono Variable, monospace",
              }}
            />
          </Suspense>
        </div>
        <div className="flex justify-end">
          <Button onClick={handleSaveYaml} disabled={saveConfig.isPending}>
            {saveConfig.isPending ? "Guardando..." : "Guardar YAML"}
          </Button>
        </div>
      </TabsContent>
    </Tabs>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-6 border-t border-border pt-8">
      <p className="text-[11px] uppercase tracking-[0.3em] text-muted-foreground">{title}</p>
      {children}
    </section>
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

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (next: boolean) => void }) {
  return (
    <div className="flex items-center justify-between">
      <Label className="normal-case tracking-normal text-[13px] text-foreground">{label}</Label>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  );
}
