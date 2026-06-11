import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useScope } from "@/context/ScopeContext";
import { ctx } from "@/lib/ctxClient";
import { useI18n } from "@/lib/i18n";
import type { ContextItem } from "@/lib/types";

function triggerDownload(filename: string, content: string, mimeType = "application/json") {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function SectionCard({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-sm">{title}</CardTitle>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardHeader>
      <CardContent className="p-4 pt-0">{children}</CardContent>
    </Card>
  );
}

function SkeletonBlock({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-muted ${className ?? "h-32"}`} />;
}

function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <button
      onClick={handleCopy}
      className={`text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-0.5 rounded hover:bg-muted ${className ?? ""}`}
    >
      {copied ? "✓ 已复制" : "复制"}
    </button>
  );
}

function ContentBlock({
  label,
  text,
  mono = false,
}: {
  label: string;
  text: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          {label}
        </span>
        <CopyButton text={text} />
      </div>
      <div className={`rounded-md bg-muted px-3 py-2.5 text-sm leading-relaxed ${mono ? "font-mono text-xs" : ""}`}>
        <p className="whitespace-pre-wrap break-words">{text}</p>
      </div>
    </div>
  );
}

function SkillDetailDialog({
  item,
  onClose,
}: {
  item: ContextItem | null;
  onClose: () => void;
}) {
  const { t } = useI18n();
  if (!item) return null;

  // Handle both string-content and dict-content skills
  const isStringContent = typeof item.content === "string";
  const dictContent =
    item.content && typeof item.content === "object"
      ? (item.content as Record<string, unknown>)
      : null;

  const name = (dictContent?.name as string) || item.summary || item.id;
  const description = dictContent?.description as string | undefined;
  // For string-content skills, the body IS the raw content string
  const body = isStringContent
    ? (item.content as string)
    : (dictContent?.body as string | undefined);
  const parameters = dictContent?.parameters as Record<string, unknown> | undefined;
  const inputSchema = dictContent?.inputSchema as Record<string, unknown> | undefined;
  const version = dictContent?.version as string | undefined;
  const contentTags = dictContent?.tags as string[] | undefined;
  // Show item.tags but exclude generic stage/type tags already visible as Badge
  const displayTags = [
    ...(contentTags ?? []),
    ...(item.tags ?? []).filter(
      (t) => !["prompt_skill", "tool_skill", "mcp_skill", "prompt", "tool", "mcp"].includes(t),
    ),
  ].filter((v, i, a) => a.indexOf(v) === i);

  const confidence = Math.round(item.provenance.confidence * 100);
  const confidenceColor =
    confidence >= 80 ? "text-green-500" : confidence >= 60 ? "text-yellow-500" : "text-red-500";

  return (
    <Dialog open={!!item} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col p-0 gap-0 overflow-hidden">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b shrink-0">
          <DialogHeader>
            <DialogTitle className="leading-snug pr-6">
              {name}
            </DialogTitle>
          </DialogHeader>
          {description && !isStringContent && (
            <p className="mt-2 text-sm text-muted-foreground leading-relaxed">{description}</p>
          )}
          {version && (
            <p className="mt-1 text-xs text-muted-foreground">v{version}</p>
          )}
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          {body && (
            <ContentBlock
              label={t("skills.detail.body")}
              text={body}
              mono={false}
            />
          )}

          {parameters && (
            <ContentBlock
              label={t("skills.detail.parameters")}
              text={JSON.stringify(parameters, null, 2)}
              mono
            />
          )}

          {inputSchema && (
            <ContentBlock
              label={t("skills.detail.inputSchema")}
              text={JSON.stringify(inputSchema, null, 2)}
              mono
            />
          )}

          {displayTags.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1.5">
                Tags
              </p>
              <div className="flex flex-wrap gap-1.5">
                {displayTags.map((tag) => (
                  <Badge key={tag} variant="outline" className="text-xs font-normal">
                    {tag}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Metadata footer */}
        <div className="px-6 py-3 border-t bg-muted/40 shrink-0">
          <div className="grid grid-cols-3 gap-4 text-xs text-muted-foreground">
            <div>
              <p className="font-medium mb-0.5">{t("skills.detail.confidence")}</p>
              <p className={`font-semibold ${confidenceColor}`}>{confidence}%</p>
            </div>
            <div>
              <p className="font-medium mb-0.5">{t("skills.detail.source")}</p>
              <p className="truncate">{item.provenance.source_type}</p>
            </div>
            <div>
              <p className="font-medium mb-0.5">{t("skills.detail.createdAt")}</p>
              <p>{new Date(item.created_at).toLocaleDateString()}</p>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function getSkillName(item: ContextItem): string {
  if (item.content && typeof item.content === "object") {
    return (item.content as Record<string, unknown>).name as string || item.summary || item.id.slice(0, 8);
  }
  return item.summary || item.id.slice(0, 8);
}

function getSkillBody(item: ContextItem): string {
  if (typeof item.content === "string") return item.content;
  if (item.content && typeof item.content === "object") {
    return (item.content as Record<string, unknown>).body as string || "";
  }
  return "";
}

function buildSystemPrompt(items: ContextItem[]): string {
  if (!items.length) return "";
  const blocks = items.map((item) => {
    const name = getSkillName(item);
    const body = getSkillBody(item);
    return [`### ${name}`, body].filter(Boolean).join("\n\n");
  });
  return `<available_skills>\n${blocks.join("\n\n---\n\n")}\n</available_skills>`;
}

function SystemPromptCard({ items }: { items: ContextItem[] }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fullPrompt = buildSystemPrompt(items);

  function handleCopyAll() {
    if (!fullPrompt) return;
    navigator.clipboard.writeText(fullPrompt).then(() => {
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <SectionCard
      title={`${t("skills.systemPrompt")}${items.length > 0 ? ` (${items.length})` : ""}`}
      hint={t("skills.systemPrompt.hint")}
    >
      {items.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t("skills.systemPrompt.empty")}</p>
      ) : (
        <div className="space-y-3">
          {/* Formatted preview (read-only, truncated) */}
          <div className="relative rounded-md bg-muted overflow-hidden">
            <pre className="px-3 py-2.5 text-xs font-mono text-muted-foreground whitespace-pre-wrap leading-relaxed max-h-32 overflow-hidden">
              {fullPrompt}
            </pre>
            {/* fade-out overlay at the bottom to indicate truncation */}
            <div className="absolute bottom-0 inset-x-0 h-8 bg-gradient-to-t from-muted to-transparent pointer-events-none" />
          </div>

          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{items.length} 个技能 · 复制后粘贴进 LLM system prompt 即可生效</span>
            <Button
              size="sm"
              variant="secondary"
              onClick={handleCopyAll}
              className="h-7 text-xs shrink-0"
            >
              {copied ? t("skills.systemPrompt.copied") : t("skills.systemPrompt.copy")}
            </Button>
          </div>
        </div>
      )}
    </SectionCard>
  );
}

export function SkillsPanel() {
  const { t } = useI18n();
  const { scope } = useScope();
  const [items, setItems] = useState<ContextItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedItem, setSelectedItem] = useState<ContextItem | null>(null);
  const [downloadingMd, setDownloadingMd] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    ctx
      .items({ scope, stage: "skill" })
      .then((res) => {
        if (!cancelled) {
          setItems(res.items);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [scope]);

  async function handleDownloadSkillMd() {
    setDownloadingMd(true);
    try {
      const res = await ctx.skillMd({ scope });
      const combined = res.skills
        .map((s) => `# ${s.name}\n\n${s.content}`)
        .join("\n\n---\n\n");
      triggerDownload("skills.md", combined, "text/markdown");
    } finally {
      setDownloadingMd(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-4 p-6">
        <div className="grid gap-4 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <SkeletonBlock key={i} className="h-52" />
          ))}
        </div>
        <SkeletonBlock className="h-40" />
      </div>
    );
  }

  const recent = [...items].reverse().slice(0, 8);
  const hasSkills = items.length > 0;

  return (
    <div className="space-y-4 p-6">
      <SkillDetailDialog item={selectedItem} onClose={() => setSelectedItem(null)} />

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Skills list */}
        <div className="space-y-4 lg:col-span-2">
          <SectionCard title={t("skills.distilled")}>
            {recent.length > 0 ? (
              <div className="space-y-1">
                {recent.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => setSelectedItem(item)}
                    className="w-full flex items-center rounded px-2 py-1.5 text-left text-xs hover:bg-muted transition-colors cursor-pointer"
                  >
                    <span className="truncate flex-1">
                      {item.summary ?? item.id}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                {t("overview.noData") || "No distilled skills yet"}
              </p>
            )}
          </SectionCard>
        </div>

        {/* SKILL.md export */}
        <div className="space-y-4">
          <SectionCard title="SKILL.md">
            <div className="flex flex-col gap-3">
              <p className="text-xs text-muted-foreground">
                复制后粘贴进 LLM system prompt 即可生效
              </p>
              <Button
                size="sm"
                variant="outline"
                disabled={!hasSkills || downloadingMd}
                onClick={handleDownloadSkillMd}
                className="w-full text-xs"
              >
                {t("skills.export.download")}
              </Button>
            </div>
          </SectionCard>
        </div>
      </div>

      {/* Full-width System Prompt Preview */}
      <SystemPromptCard items={items} />
    </div>
  );
}
