import { ArrowRight, Moon, Sparkles } from "lucide-react";
import { useState } from "react";

import { BarList } from "@/components/charts/BarList";
import { StageBadge } from "@/components/common/StageBadge";
import { AsyncButton } from "@/components/common/AsyncButton";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ctx } from "@/lib/ctxClient";
import { useI18n } from "@/lib/i18n";
import { useScope } from "@/context/ScopeContext";
import { cn, errorMessage } from "@/lib/utils";
import type {
  CompactResponse,
  ConversionStat,
  DreamResponse,
  EvolutionEventDict,
  Stage,
} from "@/lib/types";

export function EvolutionPanel() {
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <EvolutionCard />
    </div>
  );
}

function EvolutionCard() {
  const { t } = useI18n();
  const { scope } = useScope();
  const [dryRun, setDryRun] = useState(true);
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState<unknown>(null);
  const [compact, setCompact] = useState<CompactResponse | null>(null);
  const [dream, setDream] = useState<DreamResponse | null>(null);

  const runCompact = async () => {
    setBusy("compact");
    setError(null);
    try {
      setCompact(await ctx.compact({ scope, dry_run: dryRun }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy("");
    }
  };

  const runDream = async () => {
    setBusy("dream");
    setError(null);
    try {
      setDream(await ctx.dream({ scope, dry_run: dryRun }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy("");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("evolution.title")}</CardTitle>
        <CardDescription>{t("evolution.desc", { scope })}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
          {t("evolution.dryRun")}
        </label>
        <div className="flex flex-wrap gap-3">
          <AsyncButton variant="outline" loading={busy === "compact"} onClick={runCompact}>
            <Sparkles className="h-4 w-4" /> Compact
          </AsyncButton>
          <AsyncButton variant="outline" loading={busy === "dream"} onClick={runDream}>
            <Moon className="h-4 w-4" /> Dream
          </AsyncButton>
        </div>
        {error ? <p className="text-sm text-destructive">{errorMessage(error)}</p> : null}
        {compact && (
          <Stats
            title={t("evolution.compactResult")}
            entries={[
              ["merged", compact.merged],
              ["archived", compact.archived],
              ["evolved", compact.evolved],
            ]}
          />
        )}
        {compact && <EvolutionFunnel report={compact} />}
        {dream && (
          <Stats
            title={t("evolution.dreamResult")}
            entries={[
              ["total", dream.total_dream_items],
              ["consol. patterns", dream.consolidation_patterns],
              ["consol. items", dream.consolidation_items],
              ["divergence", dream.divergence_items],
            ]}
          />
        )}
      </CardContent>
    </Card>
  );
}

function Stats({ title, entries }: { title: string; entries: [string, number][] }) {
  return (
    <div className="rounded-md border bg-muted/40 p-3">
      <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <div className="flex flex-wrap gap-4">
        {entries.map(([label, value]) => (
          <div key={label} className="flex flex-col">
            <span className="font-mono text-lg tabular-nums">{value}</span>
            <span className="text-xs text-muted-foreground">{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const FUNNEL_STAGES: Stage[] = ["raw", "extracted", "knowledge", "skill"];
const FUNNEL_HOPS = ["raw->extracted", "extracted->knowledge", "knowledge->skill"] as const;

/**
 * Evolution funnel: per-stage inventory (滞留量) plus the conversion rate of
 * each hop, so a stalled boundary (rate 0 / heavy backlog) is visible at a
 * glance. Renders nothing for backends that predate module-5 observability.
 */
function EvolutionFunnel({ report }: { report: CompactResponse }) {
  const { t } = useI18n();
  const inventory = report.stage_distribution;
  const conversion = report.conversion;
  if (!inventory && !conversion) return null;

  const rejections = rejectionBreakdown(report.events ?? []);

  return (
    <div className="space-y-4 rounded-md border bg-muted/40 p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {t("evolution.funnel")}
        </span>
        {report.avg_quality_score != null && (
          <span className="text-xs text-muted-foreground">
            {t("evolution.avgQuality")}:{" "}
            <span className="font-mono tabular-nums text-foreground">
              {report.avg_quality_score.toFixed(2)}
            </span>
          </span>
        )}
      </div>

      <div className="flex items-stretch gap-1 overflow-x-auto">
        {FUNNEL_STAGES.map((stage, i) => (
          <div key={stage} className="flex items-stretch gap-1">
            <StageCell stage={stage} count={inventory?.[stage] ?? 0} />
            {i < FUNNEL_HOPS.length && (
              <HopConnector stat={conversion?.[FUNNEL_HOPS[i]]} label={t("evolution.rate")} />
            )}
          </div>
        ))}
      </div>

      {report.path_distribution && Object.keys(report.path_distribution).length > 0 && (
        <div>
          <div className="mb-1.5 text-xs text-muted-foreground">{t("evolution.paths")}</div>
          <BarList
            items={Object.entries(report.path_distribution)
              .sort((a, b) => b[1] - a[1])
              .map(([label, value]) => ({ label, value }))}
          />
        </div>
      )}

      {rejections.length > 0 && (
        <div>
          <div className="mb-1.5 text-xs text-muted-foreground">{t("evolution.rejections")}</div>
          <BarList
            items={rejections.map(([label, value]) => ({
              label,
              value,
              color: "var(--destructive)",
            }))}
          />
        </div>
      )}
    </div>
  );
}

function StageCell({ stage, count }: { stage: Stage; count: number }) {
  return (
    <div className="flex min-w-[88px] flex-col items-center justify-center gap-1 rounded-md border bg-background px-3 py-2">
      <span className="font-mono text-xl tabular-nums">{count}</span>
      <StageBadge stage={stage} />
    </div>
  );
}

function HopConnector({ stat, label }: { stat?: ConversionStat; label: string }) {
  const attempted = stat?.attempted ?? 0;
  const succeeded = stat?.succeeded ?? 0;
  const rate = attempted > 0 ? succeeded / attempted : 0;
  // A boundary that had candidates but converted none is the bottleneck (断点).
  const stalled = attempted > 0 && succeeded === 0;

  return (
    <div className="flex min-w-[72px] flex-col items-center justify-center px-1">
      <ArrowRight
        className={cn("h-4 w-4", stalled ? "text-destructive" : "text-muted-foreground")}
      />
      <span
        className={cn(
          "font-mono text-xs tabular-nums",
          stalled ? "text-destructive" : "text-foreground",
        )}
        title={label}
      >
        {attempted > 0 ? `${Math.round(rate * 100)}%` : "—"}
      </span>
      <span className="text-[10px] tabular-nums text-muted-foreground">
        {succeeded}/{attempted}
      </span>
    </div>
  );
}

function rejectionBreakdown(events: EvolutionEventDict[]): [string, number][] {
  const counts: Record<string, number> = {};
  for (const e of events) {
    if (e.event !== "promotion_rejected") continue;
    const reason = e.reject_reason || "unknown";
    counts[reason] = (counts[reason] ?? 0) + 1;
  }
  return Object.entries(counts).sort((a, b) => b[1] - a[1]);
}
