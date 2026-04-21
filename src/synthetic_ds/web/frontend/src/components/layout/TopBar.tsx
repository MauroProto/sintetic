import { Link, NavLink } from "react-router-dom";
import { Triangle } from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";
import { Button } from "@/components/ui/button";
import { useProviders } from "@/hooks/useConfig";
import { useHealth } from "@/hooks/useHealth";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/", label: "Overview", exact: true },
  { to: "/dataset", label: "Dataset" },
  { to: "/new", label: "New run" },
  { to: "/settings", label: "Settings" },
];

export function TopBar() {
  const { data: providers } = useProviders();
  const { data: health } = useHealth();
  const activeName = providers?.active;
  const activeProfile = activeName ? providers?.profiles[activeName] : undefined;
  const keyPresent = activeName ? providers?.keys_present[activeName] : false;
  const pool = health?.pool;
  const running = pool?.running.length ?? 0;
  const queued = pool?.queued.length ?? 0;
  const maxJobs = pool?.max_concurrent_jobs ?? 1;

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 w-full max-w-[1200px] items-center justify-between gap-4 px-6 lg:px-10">
        <div className="flex items-center gap-8">
          <Link to="/" className="flex items-center gap-2 font-geist">
            <Triangle className="h-5 w-5 fill-foreground text-foreground" strokeWidth={0} />
            <span className="text-[15px] font-semibold tracking-tight">synthetic‑ds</span>
          </Link>
          <span className="hidden h-5 w-px bg-border md:block" />
          <nav className="hidden items-center gap-1 md:flex">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.exact}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-2.5 py-1 text-[14px] transition-colors",
                    isActive ? "font-medium text-foreground" : "text-muted-foreground hover:text-foreground",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          {providers ? (
            <div className="hidden items-center gap-2 font-geist-mono text-[11px] uppercase tracking-[0.1em] text-muted-foreground md:flex">
              <span>{activeName}</span>
              <span className="text-border">·</span>
              <span
                className={cn("flex items-center gap-1.5", keyPresent ? "text-foreground" : "text-destructive")}
              >
                <span className={cn("h-1.5 w-1.5 rounded-full", keyPresent ? "bg-success" : "bg-destructive")} />
                {keyPresent ? "Ready" : "No key"}
              </span>
              {activeProfile?.model ? (
                <span className="hidden truncate text-foreground/70 lg:inline-block">· {activeProfile.model}</span>
              ) : null}
              {pool ? (
                <>
                  <span className="text-border">·</span>
                  <span title={`${running} corriendo / ${queued} en cola / cupo ${maxJobs}`}>
                    {running}/{maxJobs}
                    {queued > 0 ? ` +${queued}` : ""} jobs
                  </span>
                </>
              ) : null}
            </div>
          ) : null}
          <ThemeToggle />
          <Button asChild size="sm" className="hidden md:inline-flex">
            <Link to="/new">Start dataset</Link>
          </Button>
        </div>
      </div>

      <nav className="flex items-center gap-4 border-t border-border px-6 py-2 md:hidden">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.exact}
            className={({ isActive }) =>
              cn(
                "rounded-md px-2 py-1 text-[13px] transition-colors",
                isActive ? "font-medium text-foreground" : "text-muted-foreground",
              )
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}
