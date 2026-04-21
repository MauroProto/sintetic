import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";

export function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
      <h1 className="text-6xl font-bold text-gradient">404</h1>
      <p className="text-sm text-muted-foreground">La ruta que buscas no existe.</p>
      <Button asChild variant="gradient">
        <Link to="/">Volver al dashboard</Link>
      </Button>
    </div>
  );
}
