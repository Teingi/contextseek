import { useCallback, useEffect, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Bot, Braces, Database, Info, Plug, RefreshCw, SlidersHorizontal } from "lucide-react";

import { StatRows } from "@/components/charts/StatRows";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ctx } from "@/lib/ctxClient";
import { useI18n } from "@/lib/i18n";
import type { Config, Health } from "@/lib/types";

const HEALTH_POLL_MS = 15_000;

function SettingsGroup({
  icon: Icon,
  title,
  desc,
  children,
}: {
  icon: LucideIcon;
  title: string;
  desc: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>
      <p className="text-xs text-muted-foreground">{desc}</p>
      <Card>
        <CardContent className="p-4">{children}</CardContent>
      </Card>
    </section>
  );
}

export function SettingsPanel() {
  const { t } = useI18n();
  const [config, setConfig] = useState<Config | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const healthTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAll = useCallback(async () => {
    setError(false);
    const [cfgResult, healthResult] = await Promise.allSettled([
      ctx.config(),
      ctx.health(),
    ]);
    if (cfgResult.status === "fulfilled") setConfig(cfgResult.value);
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    if (cfgResult.status === "rejected" && healthResult.status === "rejected") {
      setError(true);
    }
  }, []);

  const pollHealth = useCallback(async () => {
    try {
      const h = await ctx.health();
      setHealth(h);
      setError(false);
    } catch {
      // keep last known value on transient errors
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchAll().then(() => {
      if (cancelled) return;
      healthTimerRef.current = setInterval(() => {
        if (!cancelled) pollHealth();
      }, HEALTH_POLL_MS);
    });
    return () => {
      cancelled = true;
      if (healthTimerRef.current !== null) {
        clearInterval(healthTimerRef.current);
        healthTimerRef.current = null;
      }
    };
  }, [fetchAll, pollHealth]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchAll();
    setRefreshing(false);
  };

  // ── 后端连接 ──────────────────────────────────────────────────────────────
  const addr =
    (import.meta.env.VITE_CTX_BASE as string | undefined) || "127.0.0.1:8000";

  const isOk = health?.status === "ok";
  const healthValue = (
    <span className="flex items-center gap-1.5 text-xs">
      <span
        className={`h-2 w-2 rounded-full ${
          health == null ? "bg-muted-foreground" : isOk ? "bg-emerald-500" : "bg-rose-500"
        }`}
      />
      {health == null ? "…" : isOk ? t("settings.sys.daemonValue") : health.status}
    </span>
  );

  const connection = [
    { label: t("settings.conn.addr"), value: addr },
    { label: t("settings.conn.health"), value: healthValue },
  ];

  // ── 系统控制 ──────────────────────────────────────────────────────────────
  const daemonStatus = health
    ? health.status === "ok"
      ? t("settings.sys.daemonValue")
      : health.status
    : "…";

  const autoSyncValue = config
    ? config.auto_sync
      ? t("settings.sys.autoSyncValue")
      : t("settings.sys.autoSyncOff")
    : "…";

  const system = [
    {
      label: t("settings.sys.daemon"),
      value: daemonStatus,
      variant: (health?.status === "ok" ? "default" : "destructive") as
        | "default"
        | "destructive"
        | "secondary",
    },
    {
      label: t("settings.sys.autoSync"),
      value: autoSyncValue,
      variant: (config === null
        ? "secondary"
        : config.auto_sync
          ? "default"
          : "secondary") as "default" | "destructive" | "secondary",
    },
  ];

  // ── 模型分组 ──────────────────────────────────────────────────────────────
  const val = (v: string | undefined) => (config ? v || "—" : "…");

  const llmRows = [{ label: t("settings.llm.model"), value: val(config?.llm_model) }];
  const embedderRows = [{ label: t("settings.embedder.model"), value: val(config?.embedding_model) }];
  const dbBackend = config?.storage_backend ?? "";
  const dbExtra = (() => {
    if (!config) return [];
    if (dbBackend === "oceanbase") {
      return [
        { label: t("settings.db.host"), value: val(config.ob_host) },
        { label: t("settings.db.port"), value: val(config.ob_port) },
        { label: t("settings.db.dbName"), value: val(config.ob_db_name) },
        { label: t("settings.db.tableName"), value: val(config.ob_table_name) },
      ];
    }
    if (dbBackend === "seekdb") {
      if (config.seekdb_mode === "server") {
        return [
          { label: t("settings.db.host"), value: val(config.seekdb_host) },
          { label: t("settings.db.port"), value: val(config.seekdb_port) },
          { label: t("settings.db.dbName"), value: val(config.seekdb_database) },
        ];
      }
      return [{ label: t("settings.db.path"), value: val(config.seekdb_path) }];
    }
    if (dbBackend === "sqlite") {
      return [{ label: t("settings.db.path"), value: val(config.sqlite_path) }];
    }
    if (dbBackend === "file") {
      return [{ label: t("settings.db.path"), value: val(config.storage_path) }];
    }
    return [];
  })();

  const dbRows = [
    { label: t("settings.db.backend"), value: val(config?.storage_backend) },
    ...dbExtra,
  ];
  const aboutRows = [{ label: t("settings.about.version"), value: val(config?.version) }];

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div className="flex items-center justify-end">
        <Button
          variant="ghost"
          size="sm"
          onClick={handleRefresh}
          disabled={refreshing}
          className="gap-1.5 text-xs text-muted-foreground"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
          {t("settings.refresh")}
        </Button>
      </div>

      {error && (
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-2 text-xs text-destructive">
          {t("settings.loadError")}
        </p>
      )}

      <SettingsGroup
        icon={Plug}
        title={t("settings.connection")}
        desc={t("settings.connection.desc")}
      >
        <StatRows highlightFirst rows={connection} />
      </SettingsGroup>

      <SettingsGroup icon={Bot} title={t("settings.llm")} desc={t("settings.llm.desc")}>
        <StatRows highlightFirst rows={llmRows} />
      </SettingsGroup>

      <SettingsGroup icon={Braces} title={t("settings.embedder")} desc={t("settings.embedder.desc")}>
        <StatRows highlightFirst rows={embedderRows} />
      </SettingsGroup>

      <SettingsGroup icon={Database} title={t("settings.db")} desc={t("settings.db.desc")}>
        <StatRows highlightFirst rows={dbRows} />
      </SettingsGroup>

      <SettingsGroup
        icon={SlidersHorizontal}
        title={t("settings.system")}
        desc={t("settings.system.desc")}
      >
        <StatRows
          rows={system.map((s) => ({
            label: s.label,
            value: <Badge variant={s.variant}>{s.value}</Badge>,
          }))}
        />
      </SettingsGroup>

      <SettingsGroup icon={Info} title={t("settings.about")} desc={t("settings.about.desc")}>
        <StatRows rows={aboutRows} />
      </SettingsGroup>
    </div>
  );
}
