import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  id?: string;
}

export function FolderPickerField({ value, onChange, onBlur, id = "source_dir" }: Props) {
  const { toast } = useToast();

  async function handlePick() {
    try {
      const { path } = await api.pickFolder();
      if (path) {
        onChange(path);
        onBlur?.();
      }
    } catch (error) {
      toast({
        variant: "error",
        title: "No se pudo abrir el selector",
        description: (error as Error).message,
      });
    }
  }

  return (
    <div className="space-y-2">
      <label
        htmlFor={id}
        className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground"
      >
        Carpeta con PDFs
      </label>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          placeholder="/ruta/a/tus/pdfs"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onBlur}
          className="font-geist-mono text-[13px]"
        />
        <Button type="button" variant="outline" onClick={handlePick}>
          Elegir carpeta
        </Button>
      </div>
    </div>
  );
}
