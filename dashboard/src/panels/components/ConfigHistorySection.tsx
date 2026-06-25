import { useCallback, useEffect, useState } from "react";
import { History, RotateCcw, GitBranch, AlertTriangle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ctx } from "@/lib/ctxClient";
import { useI18n } from "@/lib/i18n";
import { errorMessage } from "@/lib/utils";
import type { ConfigHistoryEntry, ConfigStatus } from "@/lib/types";

/**
 * Inline config version-history section: fetches `/config/history` +
 * `/config/status`, shows the version chain, a drift badge, an agentseek
 * ingest button, expandable diff placeholder, and a per-row rollback button.
 */
export function ConfigHistorySection() {
  const { t } = useI18n();
  const [history, setHistory] = useState<ConfigHistoryEntry[]>([]);
  const [status, setStatus] = useState<ConfigStatus | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");

  const refresh = useCallback(async () => {
    const [h, s] = await Promise.all([ctx.getConfigHistory(20), ctx.getConfigStatus()]);
    setHistory(h);
    setStatus(s);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onRollback = useCallback(
    async (version: string) => {
      setBusy(`rollback:${version}`);
      setMsg("");
      try {
        await ctx.rollbackConfig(version, "dashboard rollback");
        await refresh();
        setMsg(t("config.rollback") + " ✓");
      } catch (err) {
        setMsg(errorMessage(err));
      } finally {
        setBusy("");
      }
    },
    [refresh, t],
  );

  const onIngestAgentseek = useCallback(async () => {
    setBusy("ingest");
    setMsg("");
    try {
      await ctx.ingestAgentseek();
      await refresh();
      setMsg(t("config.ingestAgentseek") + " ✓");
    } catch (err) {
      setMsg(errorMessage(err));
    } finally {
      setBusy("");
    }
  }, [refresh, t]);

  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <History className="h-4 w-4" />
            <span className="font-medium">{t("config.history")}</span>
            {status?.current_version && (
              <Badge variant="secondary">
                <GitBranch className="mr-1 h-3 w-3" />
                {status.current_version}
              </Badge>
            )}
            {status?.drift?.env && (
              <Badge variant="destructive">
                <AlertTriangle className="mr-1 h-3 w-3" />
                drift
              </Badge>
            )}
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={busy === "ingest"}
            onClick={() => void onIngestAgentseek()}
          >
            {t("config.ingestAgentseek")}
          </Button>
        </div>
        {msg && <p className="text-xs text-muted-foreground">{msg}</p>}
        <ul className="space-y-1 text-sm">
          {history.map((v) => (
            <li key={v.version_id} className="rounded border p-2">
              <div className="flex items-center justify-between">
                <span className="truncate">
                  <code>{v.version_id}</code> · {v.origin} · {v.author} · {v.reason}
                </span>
                <div className="flex shrink-0 gap-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      setExpanded(expanded === v.version_id ? null : v.version_id)
                    }
                  >
                    diff
                  </Button>
                  {v.version_id !== status?.current_version && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy === `rollback:${v.version_id}`}
                      onClick={() => void onRollback(v.version_id)}
                    >
                      <RotateCcw className="mr-1 h-3 w-3" />
                      {t("config.rollback")}
                    </Button>
                  )}
                </div>
              </div>
              {expanded === v.version_id && (
                <pre className="mt-2 max-h-40 overflow-auto rounded bg-muted p-2 text-xs text-muted-foreground">
                  {t("config.history")} · {v.version_id}
                  {"\n"}
                  parent: {v.parent_version_id ?? "—"}
                  {"\n"}
                  created_at: {v.created_at}
                  {"\n"}
                  origin: {v.origin} · author: {v.author}
                </pre>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
