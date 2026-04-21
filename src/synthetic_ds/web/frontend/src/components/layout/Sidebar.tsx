import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/", label: "Overview", exact: true },
  { to: "/new", label: "New run" },
  { to: "/settings", label: "Settings" },
];

export function Sidebar() {
  return (
    <aside className="hidden w-56 shrink-0 flex-col border-r border-border bg-background lg:flex">
      <div className="flex h-16 items-center px-8">
        <span className="text-[13px] font-medium tracking-tight">synthetic·ds</span>
      </div>
      <nav className="flex flex-1 flex-col px-4 py-2">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.exact}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-4 py-2 text-sm transition-colors",
                isActive
                  ? "text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={cn(
                    "block h-[2px] w-4 transition-all",
                    isActive ? "bg-foreground" : "bg-transparent",
                  )}
                />
                {item.label}
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-border px-8 py-4 text-[11px] text-muted-foreground">
        <p>Local · offline</p>
      </div>
    </aside>
  );
}
