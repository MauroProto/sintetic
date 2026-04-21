import { Outlet } from "react-router-dom";
import { TopBar } from "./TopBar";

export function AppShell() {
  return (
    <div className="flex min-h-screen w-full flex-col bg-background text-foreground">
      <TopBar />
      <main className="flex-1">
        <div className="mx-auto w-full max-w-[1200px] px-6 py-16 lg:px-10 lg:py-24">
          <Outlet />
        </div>
      </main>
      <footer className="border-t border-border">
        <div className="mx-auto flex w-full max-w-[1200px] items-center justify-between px-6 py-6 lg:px-10">
          <span className="font-geist text-[13px] text-muted-foreground">synthetic‑ds</span>
          <span className="font-geist-mono text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
            Local · Offline
          </span>
        </div>
      </footer>
    </div>
  );
}
