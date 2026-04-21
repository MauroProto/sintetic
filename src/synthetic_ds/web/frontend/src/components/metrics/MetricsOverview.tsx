import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Skeleton } from "@/components/ui/skeleton";
import { useMetrics } from "@/hooks/useMetrics";

const MONOCHROME = ["#0a0a0a", "#404040", "#737373", "#a3a3a3", "#d4d4d4", "#e5e5e5"];
const MONOCHROME_DARK = ["#fafafa", "#d4d4d4", "#a3a3a3", "#737373", "#525252", "#404040"];

function bucketize(values: number[], bins = 10): { bucket: string; count: number }[] {
  if (!values.length) return [];
  const buckets = new Array(bins).fill(0);
  for (const v of values) {
    const clamped = Math.max(0, Math.min(0.999, v));
    const index = Math.floor(clamped * bins);
    buckets[index] += 1;
  }
  return buckets.map((count, idx) => ({
    bucket: `${(idx / bins).toFixed(1)}`,
    count,
  }));
}

export function MetricsOverview({ jobId }: { jobId: string }) {
  const { data, isLoading } = useMetrics(jobId);

  if (isLoading) {
    return (
      <div className="grid gap-12 border-t border-border pt-8 md:grid-cols-2">
        <Skeleton className="h-64" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (!data) return null;

  const isDark = typeof document !== "undefined" && document.documentElement.classList.contains("dark");
  const palette = isDark ? MONOCHROME_DARK : MONOCHROME;
  const stroke = isDark ? "#a3a3a3" : "#737373";

  const acceptance = [
    { name: "train", accepted: data.acceptance.train.accepted, rejected: data.acceptance.train.rejected },
    { name: "eval", accepted: data.acceptance.eval.accepted, rejected: data.acceptance.eval.rejected },
  ];

  const trainTypeEntries = Object.entries(data.type_distribution.train).map(([name, value]) => ({ name, value }));
  const evalTypeEntries = Object.entries(data.type_distribution.eval).map(([name, value]) => ({ name, value }));
  const trainOverall = bucketize(data.score_distribution.train.overall);
  const evalOverall = bucketize(data.score_distribution.eval.overall);

  return (
    <div className="space-y-16 border-t border-border pt-8">
      <Panel title="Aceptación por split">
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={acceptance}>
              <XAxis dataKey="name" stroke={stroke} fontSize={11} tickLine={false} axisLine={false} />
              <YAxis stroke={stroke} fontSize={11} tickLine={false} axisLine={false} />
              <ChartTooltip
                cursor={{ fill: "hsl(var(--muted) / 0.4)" }}
                contentStyle={{
                  background: "hsl(var(--popover))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 6,
                  fontSize: 12,
                }}
              />
              <Bar dataKey="accepted" fill={palette[0]} />
              <Bar dataKey="rejected" fill={palette[3]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <div className="grid gap-12 md:grid-cols-2">
        <Panel title="Distribución train">
          {trainTypeEntries.length === 0 ? (
            <Empty />
          ) : (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={trainTypeEntries} dataKey="value" nameKey="name" outerRadius={80} innerRadius={40}>
                    {trainTypeEntries.map((_, index) => (
                      <Cell key={index} fill={palette[index % palette.length]} />
                    ))}
                  </Pie>
                  <ChartTooltip
                    contentStyle={{
                      background: "hsl(var(--popover))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: 6,
                      fontSize: 12,
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>

        <Panel title="Distribución eval">
          {evalTypeEntries.length === 0 ? (
            <Empty />
          ) : (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={evalTypeEntries} dataKey="value" nameKey="name" outerRadius={80} innerRadius={40}>
                    {evalTypeEntries.map((_, index) => (
                      <Cell key={index} fill={palette[index % palette.length]} />
                    ))}
                  </Pie>
                  <ChartTooltip
                    contentStyle={{
                      background: "hsl(var(--popover))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: 6,
                      fontSize: 12,
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Score overall · train">
        {trainOverall.length === 0 ? (
          <Empty />
        ) : (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={trainOverall}>
                <XAxis dataKey="bucket" stroke={stroke} fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke={stroke} fontSize={11} tickLine={false} axisLine={false} />
                <ChartTooltip
                  cursor={{ fill: "hsl(var(--muted) / 0.4)" }}
                  contentStyle={{
                    background: "hsl(var(--popover))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="count" fill={palette[1]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </Panel>

      {evalOverall.length ? (
        <Panel title="Score overall · eval">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={evalOverall}>
                <XAxis dataKey="bucket" stroke={stroke} fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke={stroke} fontSize={11} tickLine={false} axisLine={false} />
                <ChartTooltip
                  cursor={{ fill: "hsl(var(--muted) / 0.4)" }}
                  contentStyle={{
                    background: "hsl(var(--popover))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="count" fill={palette[0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      ) : null}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <p className="text-[11px] uppercase tracking-[0.3em] text-muted-foreground">{title}</p>
      {children}
    </section>
  );
}

function Empty() {
  return (
    <div className="flex h-64 items-center justify-center border border-dashed border-border">
      <span className="text-[12px] text-muted-foreground">Sin datos todavía.</span>
    </div>
  );
}
