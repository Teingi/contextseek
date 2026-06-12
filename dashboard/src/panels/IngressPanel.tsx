import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";

import { AsyncButton } from "@/components/common/AsyncButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ctx } from "@/lib/ctxClient";
import type {
  ConnectorCheckpoint,
  ConnectorConfig,
  ConnectorKind,
  ConnectorMode,
  DeadLetterRecord,
} from "@/lib/types";

const KINDS: ConnectorKind[] = [
  "notes",
  "url",
  "wiki",
  "codex",
  "claude_code",
  "confluence",
  "notion",
  "github",
];
const MODES: ConnectorMode[] = ["synced", "direct", "hybrid"];

function ts(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

function metric(value: number | undefined): string {
  if (value == null) return "0";
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function splitList(raw: string): string[] {
  return raw
    .split(/[\n,]/)
    .map((v) => v.trim())
    .filter(Boolean);
}

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function IngressPanel() {
  const [connectors, setConnectors] = useState<ConnectorConfig[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [checkpoints, setCheckpoints] = useState<ConnectorCheckpoint[]>([]);
  const [events, setEvents] = useState<Record<string, unknown>[]>([]);
  const [deadLetters, setDeadLetters] = useState<DeadLetterRecord[]>([]);

  const [connectorId, setConnectorId] = useState("url-main");
  const [kind, setKind] = useState<ConnectorKind>("notes");
  const [mode, setMode] = useState<ConnectorMode>("synced");
  const [owner, setOwner] = useState("dashboard");
  const [enabled, setEnabled] = useState(true);
  const [configJson, setConfigJson] = useState("{}");
  const [quickMaxPages, setQuickMaxPages] = useState("12");
  const [quickRenderJs, setQuickRenderJs] = useState(true);
  const [quickCrawl, setQuickCrawl] = useState(true);
  const [removeAfterReplay, setRemoveAfterReplay] = useState(false);
  const [notesRoot, setNotesRoot] = useState(".");
  const [aclText, setAclText] = useState("");
  const [urlListText, setUrlListText] = useState("");
  const [wikiFeedPath, setWikiFeedPath] = useState("");
  const [wikiSpaces, setWikiSpaces] = useState("space:default");
  const [wikiDefaultSpace, setWikiDefaultSpace] = useState("space:default");
  const [transcriptPath, setTranscriptPath] = useState("");
  const [sessionsText, setSessionsText] = useState("");

  const [loadingList, setLoadingList] = useState(false);
  const [creating, setCreating] = useState(false);
  const [runningActionFor, setRunningActionFor] = useState<string>("");
  const [detailBusy, setDetailBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const selected = useMemo(
    () => connectors.find((c) => c.connector_id === selectedId) ?? null,
    [connectors, selectedId],
  );

  const loadConnectors = useCallback(async () => {
    setLoadingList(true);
    try {
      const r = await ctx.connectors();
      setConnectors(r.connectors);
      if (!selectedId && r.connectors.length > 0) {
        setSelectedId(r.connectors[0].connector_id);
      } else if (
        selectedId &&
        !r.connectors.some((c) => c.connector_id === selectedId)
      ) {
        setSelectedId(r.connectors[0]?.connector_id ?? "");
      }
    } catch {
      setError("Failed to load connectors. Ensure the local backend is running.");
    } finally {
      setLoadingList(false);
    }
  }, [selectedId]);

  const loadDetails = useCallback(async (id: string) => {
    if (!id) {
      setCheckpoints([]);
      setEvents([]);
      setDeadLetters([]);
      return;
    }
    setDetailBusy(true);
    try {
      const [cp, ev, dl] = await Promise.all([
        ctx.connectorCheckpoints(id),
        ctx.connectorEvents(id),
        ctx.connectorDeadLetters(id),
      ]);
      setCheckpoints(cp.checkpoints);
      setEvents(ev.events);
      setDeadLetters(dl.dead_letters);
    } catch {
      setError(`Failed to load connector details: ${id}`);
    } finally {
      setDetailBusy(false);
    }
  }, []);

  useEffect(() => {
    loadConnectors();
  }, [loadConnectors]);

  useEffect(() => {
    if (selectedId) loadDetails(selectedId);
  }, [selectedId, loadDetails]);

  const buildStructuredConfig = useCallback((): Record<string, unknown> => {
    const acl = splitList(aclText);
    if (kind === "notes") {
      const roots = splitList(notesRoot);
      if (roots.length > 1) {
        return {
          roots,
          acl_principals: acl,
        };
      }
      return {
        root: roots[0] ?? ".",
        acl_principals: acl,
      };
    }
    if (kind === "url") {
      const urls = splitList(urlListText);
      if (urls.length > 1) {
        return {
          urls,
          acl_principals: acl,
          crawl: true,
          max_pages: 12,
          same_host_only: true,
          restrict_to_seed_path: true,
          render_js: true,
        };
      }
      return {
        url: urls[0] ?? "",
        acl_principals: acl,
        crawl: true,
        max_pages: 12,
        same_host_only: true,
        restrict_to_seed_path: true,
        render_js: true,
      };
    }
    if (kind === "wiki") {
      return {
        feed_path: wikiFeedPath.trim(),
        spaces: splitList(wikiSpaces),
        default_space: wikiDefaultSpace.trim() || "space:default",
        acl_principals: acl,
      };
    }
    if (kind === "codex" || kind === "claude_code") {
      const sessions = splitList(sessionsText);
      if (sessions.length > 1) {
        return {
          transcript_path: transcriptPath.trim(),
          sessions,
          acl_principals: acl,
        };
      }
      return {
        transcript_path: transcriptPath.trim(),
        session: sessions[0] ?? "",
        acl_principals: acl,
      };
    }
    return {};
  }, [
    aclText,
    kind,
    notesRoot,
    sessionsText,
    transcriptPath,
    urlListText,
    wikiDefaultSpace,
    wikiFeedPath,
    wikiSpaces,
  ]);

  const applyStructuredConfig = () => {
    const config = buildStructuredConfig();
    setConfigJson(prettyJson(config));
    setNotice("Generated config JSON from the structured form.");
    setError("");
  };

  const handleCreateConnector = async () => {
    setError("");
    setNotice("");
    let parsed: Record<string, unknown> = {};
    try {
      parsed = configJson.trim() ? (JSON.parse(configJson) as Record<string, unknown>) : {};
    } catch {
      setError("Config must be valid JSON.");
      return;
    }
    // UX fallback: when JSON is still empty, use structured form values directly.
    if (Object.keys(parsed).length === 0) {
      const structured = buildStructuredConfig();
      if (Object.keys(structured).length > 0) {
        parsed = structured;
        setConfigJson(prettyJson(structured));
      }
    }
    setCreating(true);
    try {
      const trimmedId = connectorId.trim();
      await ctx.createConnector({
        connector_id: trimmedId,
        kind,
        mode,
        owner: owner.trim() || "dashboard",
        enabled,
        config: parsed,
      });
      let createdNotice = `Connector created: ${trimmedId}`;
      if (kind === "url" && enabled) {
        const syncResult = await ctx.syncConnector(trimmedId);
        createdNotice = `${createdNotice}; initial sync scheduled steps: ${syncResult.scheduled_steps}`;
      }
      setNotice(createdNotice);
      await loadConnectors();
      setSelectedId(trimmedId);
      await loadDetails(trimmedId);
    } catch {
      setError("Failed to create connector (duplicate connector_id or invalid params).");
    } finally {
      setCreating(false);
    }
  };

  const handleQuickUrlImport = async () => {
    setError("");
    setNotice("");
    const url = urlListText.trim();
    if (!url) {
      setError("Please enter a URL first.");
      return;
    }
    if (!/^https?:\/\//i.test(url)) {
      setError("URL must start with http:// or https://.");
      return;
    }
    const trimmedId = connectorId.trim();
    if (!trimmedId) {
      setError("Please provide a connector_id in advanced settings.");
      return;
    }
    const parsedMaxPages = Number.parseInt(quickMaxPages, 10);
    const maxPages =
      Number.isFinite(parsedMaxPages) && parsedMaxPages > 0 ? parsedMaxPages : 12;
    setCreating(true);
    try {
      await ctx.createConnector({
        connector_id: trimmedId,
        kind: "url",
        mode: "synced",
        owner: owner.trim() || "dashboard",
        enabled: true,
        config: {
          url,
          acl_principals: splitList(aclText),
          crawl: quickCrawl,
          max_pages: maxPages,
          same_host_only: true,
          restrict_to_seed_path: true,
          render_js: quickRenderJs,
        },
      });
      const syncResult = await ctx.syncConnector(trimmedId);
      setNotice(`URL imported via ${trimmedId}; scheduled steps: ${syncResult.scheduled_steps}`);
      await loadConnectors();
      setSelectedId(trimmedId);
      await loadDetails(trimmedId);
    } catch {
      setError("Failed to import URL (duplicate connector_id or invalid params).");
    } finally {
      setCreating(false);
    }
  };

  const runConnectorAction = async (
    action: "sync" | "pause" | "resume",
    id: string,
  ) => {
    setError("");
    setNotice("");
    setRunningActionFor(`${action}:${id}`);
    try {
      if (action === "sync") {
        const r = await ctx.syncConnector(id);
        setNotice(`Sync triggered for ${id}, scheduled steps: ${r.scheduled_steps}`);
      } else if (action === "pause") {
        await ctx.pauseConnector(id);
        setNotice(`Connector paused: ${id}`);
      } else {
        await ctx.resumeConnector(id);
        setNotice(`Connector resumed: ${id}`);
      }
      await loadConnectors();
      if (selectedId === id) await loadDetails(id);
    } catch {
      setError(`Action failed: ${action} ${id}`);
    } finally {
      setRunningActionFor("");
    }
  };

  const replayDeadLetter = async (recordId: string) => {
    if (!selectedId) return;
    setRunningActionFor(`replay:${recordId}`);
    setError("");
    try {
      const r = await ctx.replayDeadLetter(selectedId, recordId);
      setNotice(`Dead-letter replayed: ${recordId}, scheduled steps: ${r.scheduled_steps}`);
      await loadDetails(selectedId);
      await loadConnectors();
    } catch {
      setError(`Failed to replay dead-letter: ${recordId}`);
    } finally {
      setRunningActionFor("");
    }
  };

  const replayAllDeadLetters = async () => {
    if (!selectedId) return;
    setRunningActionFor("replay-all");
    setError("");
    try {
      const r = await ctx.replayAllDeadLetters(selectedId, removeAfterReplay);
      setNotice(`Replay-all completed: ${r.replayed_count} records, scheduled steps: ${r.scheduled_steps}`);
      await loadDetails(selectedId);
      await loadConnectors();
    } catch {
      setError("Failed to replay all dead-letters.");
    } finally {
      setRunningActionFor("");
    }
  };

  const deleteDeadLetter = async (recordId: string) => {
    if (!selectedId) return;
    setRunningActionFor(`delete:${recordId}`);
    setError("");
    try {
      await ctx.deleteDeadLetter(selectedId, recordId);
      setNotice(`Dead-letter deleted: ${recordId}`);
      await loadDetails(selectedId);
    } catch {
      setError(`Failed to delete dead-letter: ${recordId}`);
    } finally {
      setRunningActionFor("");
    }
  };

  return (
    <div className="space-y-4 p-6">
      {error && (
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </p>
      )}
      {notice && (
        <p className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-300">
          {notice}
        </p>
      )}

      <Card>
        <CardHeader className="p-4 pb-2">
          <CardTitle className="text-sm">URL Quick Import</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 p-4 pt-0">
          <div>
            <p className="mb-1 text-xs text-muted-foreground">URL</p>
            <Input
              value={urlListText}
              onChange={(e) => setUrlListText(e.target.value)}
              placeholder="https://www.oceanbase.com/docs/obdiag-cn"
            />
          </div>

          <details className="rounded-md border bg-muted/20 p-3">
            <summary className="cursor-pointer text-xs font-medium">Advanced settings</summary>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <div>
                <p className="mb-1 text-xs text-muted-foreground">connector_id</p>
                <Input value={connectorId} onChange={(e) => setConnectorId(e.target.value)} />
              </div>
              <div>
                <p className="mb-1 text-xs text-muted-foreground">owner</p>
                <Input value={owner} onChange={(e) => setOwner(e.target.value)} />
              </div>
              <div>
                <p className="mb-1 text-xs text-muted-foreground">
                  acl_principals (optional, comma/newline)
                </p>
                <Input
                  value={aclText}
                  onChange={(e) => setAclText(e.target.value)}
                  placeholder="user:alice,group:eng"
                />
              </div>
              <div>
                <p className="mb-1 text-xs text-muted-foreground">max_pages</p>
                <Input
                  value={quickMaxPages}
                  onChange={(e) => setQuickMaxPages(e.target.value)}
                  placeholder="12"
                />
              </div>
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-primary"
                  checked={quickCrawl}
                  onChange={(e) => setQuickCrawl(e.target.checked)}
                />
                Crawl same-site linked docs
              </label>
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-primary"
                  checked={quickRenderJs}
                  onChange={(e) => setQuickRenderJs(e.target.checked)}
                />
                Render JavaScript pages
              </label>
            </div>
          </details>

          <div className="flex items-center justify-end gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={loadConnectors}
              disabled={loadingList}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loadingList ? "animate-spin" : ""}`} />
              Refresh list
            </Button>
            <AsyncButton
              size="sm"
              loading={creating}
              onClick={handleQuickUrlImport}
              disabled={!urlListText.trim()}
            >
              Import URL
            </AsyncButton>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="p-4 pb-2">
            <CardTitle className="text-sm">Connectors</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 p-4 pt-0">
            {connectors.length === 0 ? (
              <p className="text-xs text-muted-foreground">No connectors yet.</p>
            ) : (
              connectors.map((c) => (
                <div
                  key={c.connector_id}
                  className={`rounded-md border p-3 ${
                    selectedId === c.connector_id ? "border-primary bg-muted/30" : ""
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => setSelectedId(c.connector_id)}
                      className="text-left"
                    >
                      <p className="text-sm font-medium">{c.connector_id}</p>
                      <p className="text-xs text-muted-foreground">
                        {c.kind} · {c.mode} · owner:{c.owner}
                      </p>
                    </button>
                    <div className="flex items-center gap-2">
                      <Badge variant={c.enabled ? "secondary" : "outline"}>
                        {c.enabled ? "enabled" : "paused"}
                      </Badge>
                      <Badge variant="outline">{c.last_status}</Badge>
                    </div>
                  </div>

                  <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground md:grid-cols-4">
                    <span>written: {metric(c.runtime_metrics.events_written)}</span>
                    <span>failed: {metric(c.runtime_metrics.failed_total)}</span>
                    <span>retry: {metric(c.retry_count)}</span>
                    <span>tpm: {metric(c.runtime_metrics.throughput_per_min)}</span>
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    Last success: {ts(c.last_success_at)}
                  </div>

                  <div className="mt-3 flex flex-wrap gap-2">
                    <AsyncButton
                      size="sm"
                      variant="outline"
                      loading={runningActionFor === `sync:${c.connector_id}`}
                      onClick={() => runConnectorAction("sync", c.connector_id)}
                    >
                      Sync now
                    </AsyncButton>
                    {c.enabled ? (
                      <AsyncButton
                        size="sm"
                        variant="outline"
                        loading={runningActionFor === `pause:${c.connector_id}`}
                        onClick={() => runConnectorAction("pause", c.connector_id)}
                      >
                        Pause
                      </AsyncButton>
                    ) : (
                      <AsyncButton
                        size="sm"
                        variant="outline"
                        loading={runningActionFor === `resume:${c.connector_id}`}
                        onClick={() => runConnectorAction("resume", c.connector_id)}
                      >
                        Resume
                      </AsyncButton>
                    )}
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="p-4 pb-2">
            <CardTitle className="text-sm">Selected Connector</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 p-4 pt-0 text-xs">
            {selected ? (
              <>
                <p>
                  <span className="text-muted-foreground">ID: </span>
                  {selected.connector_id}
                </p>
                <p>
                  <span className="text-muted-foreground">Kind: </span>
                  {selected.kind}
                </p>
                <p>
                  <span className="text-muted-foreground">Mode: </span>
                  {selected.mode}
                </p>
                <p>
                  <span className="text-muted-foreground">Checkpoint count: </span>
                  {selected.checkpoint_count}
                </p>
                <p>
                  <span className="text-muted-foreground">Last status: </span>
                  {selected.last_status}
                </p>
              </>
            ) : (
              <p className="text-muted-foreground">Select a connector first.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader className="p-4 pb-2">
            <CardTitle className="text-sm">Checkpoints</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 p-4 pt-0 text-xs">
            {detailBusy ? (
              <p className="text-muted-foreground">Loading...</p>
            ) : checkpoints.length === 0 ? (
              <p className="text-muted-foreground">No checkpoints yet.</p>
            ) : (
              checkpoints.slice(0, 8).map((cp) => (
                <div key={`${cp.connector_id}-${cp.partition}`} className="rounded-md border p-2">
                  <p className="font-medium">{cp.partition}</p>
                  <p className="text-muted-foreground">status: {cp.status}</p>
                  <p className="truncate text-muted-foreground">cursor: {cp.cursor || "—"}</p>
                  <p className="text-muted-foreground">retry: {cp.retry_count}</p>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="p-4 pb-2">
            <CardTitle className="text-sm">Events</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 p-4 pt-0 text-xs">
            {detailBusy ? (
              <p className="text-muted-foreground">Loading...</p>
            ) : events.length === 0 ? (
              <p className="text-muted-foreground">No events yet.</p>
            ) : (
              events.slice(-8).reverse().map((e, idx) => (
                <pre key={idx} className="overflow-x-auto rounded-md border bg-muted/30 p-2 text-[11px]">
                  {JSON.stringify(e, null, 2)}
                </pre>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="p-4 pb-2">
            <CardTitle className="text-sm">Dead Letters</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 p-4 pt-0 text-xs">
            <div className="flex items-center justify-between gap-2 rounded-md border p-2">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-primary"
                  checked={removeAfterReplay}
                  onChange={(e) => setRemoveAfterReplay(e.target.checked)}
                />
                Remove after replay
              </label>
              <AsyncButton
                size="sm"
                variant="outline"
                loading={runningActionFor === "replay-all"}
                onClick={replayAllDeadLetters}
                disabled={!selectedId || deadLetters.length === 0}
              >
                Replay all
              </AsyncButton>
            </div>
            {detailBusy ? (
              <p className="text-muted-foreground">Loading...</p>
            ) : deadLetters.length === 0 ? (
              <p className="text-muted-foreground">No dead-letters.</p>
            ) : (
              deadLetters.slice(0, 8).map((d) => (
                <div key={d.id} className="space-y-1 rounded-md border p-2">
                  <p className="truncate font-medium">{d.id}</p>
                  <p className="text-muted-foreground">
                    {d.partition} · {d.stage}
                  </p>
                  <p className="truncate text-muted-foreground">{d.error_type}: {d.error_message}</p>
                  <p className="text-muted-foreground">{ts(d.created_at)}</p>
                  <div className="flex gap-2">
                    <AsyncButton
                      size="sm"
                      variant="outline"
                      loading={runningActionFor === `replay:${d.id}`}
                      onClick={() => replayDeadLetter(d.id)}
                    >
                      Replay
                    </AsyncButton>
                    <AsyncButton
                      size="sm"
                      variant="outline"
                      loading={runningActionFor === `delete:${d.id}`}
                      onClick={() => deleteDeadLetter(d.id)}
                    >
                      Delete
                    </AsyncButton>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
