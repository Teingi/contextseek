// ContextPet — pure logic: real-time vitals from `overview`, growth folding from
// the `contextseek/pet` ledger, streak/achievement rules, and animation/mood
// derivation. Everything here is side-effect free so it can be unit tested and
// reused by the panel. UI copy lives in PET_COPY (i18n-ready, see design §15).

import type { ContextItem, Overview } from "./types";

// ---- constants ----

export const PET_SCOPE = "contextseek/pet";
export const PET_SCHEMA_VERSION = 1;
export const PET_SOURCE = "contextpet";
export const PET_TAG = "pet_event";
export const XP_CAP = 100_000;
/** Folding stays O(n); past this many events a snapshot/backend fold is needed (design §11.3). */
export const LEDGER_SNAPSHOT_THRESHOLD = 500;
/** Max chars accepted for a single feed (design §14). */
export const MAX_FEED_CHARS = 2000;
export const TIMELINE_LIMIT = 5;

// ---- skins / themes (frontend-only, design §6.2 V3 皮肤) ----

export type PetThemeId = "cyber" | "glass" | "burrow" | "pixel";

export interface PetThemeMeta {
  id: PetThemeId;
  label: string;
  hint: string;
}

export const PET_THEMES: PetThemeMeta[] = [
  { id: "cyber", label: "赛博地穴", hint: "霓虹暗色数据地穴" },
  { id: "glass", label: "光感琉璃", hint: "明亮柔光玻璃" },
  { id: "burrow", label: "暖土矿洞", hint: "暖土地层与矿灯" },
  { id: "pixel", label: "像素掌机", hint: "复古绿色 LCD" },
];

export const DEFAULT_PET_THEME: PetThemeId = "cyber";

export function isPetThemeId(value: unknown): value is PetThemeId {
  return PET_THEMES.some((t) => t.id === value);
}

export type PetAction = "feed" | "walk" | "bath" | "sleep";

export const XP_DELTA: Record<PetAction, number> = {
  feed: 10,
  walk: 3,
  bath: 15,
  sleep: 20,
};

// ---- event model (design §11.1) ----

export interface PetEvent {
  type: "pet_event";
  schema_version: number;
  event_id: string;
  action: PetAction;
  xp_delta: number;
  target_scope: string;
  result?: Record<string, unknown> | null;
  client_timestamp: string;
  server_timestamp?: string | null;
}

const PET_ACTIONS: ReadonlySet<string> = new Set<PetAction>(["feed", "walk", "bath", "sleep"]);

function clamp(x: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, x));
}

// ---- real-time vitals (design §8.2) ----

export interface Vitals {
  energy: number;
  health: number;
  wisdom: number;
  mood: number;
}

/** Derive `knowledge_count` from stage_distribution (overview omits it, design §8.2). */
export function knowledgeCount(dist: Record<string, number> | undefined | null): number {
  if (!dist) return 0;
  return (dist.knowledge ?? 0) + (dist.skill ?? 0);
}

export function computeVitals(overview: Overview): Vitals {
  const energy = clamp(100 - overview.pending_extraction * 3, 10, 100);
  const health = clamp(100 - overview.pending_convergence * 4, 10, 100);
  const known = knowledgeCount(overview.stage_distribution);
  const knowledgeRatio = known / Math.max(overview.total_items, 1);
  const wisdom = clamp(20 + overview.distill_candidates * 6 + knowledgeRatio * 40, 0, 100);
  const mood = clamp(energy * 0.4 + health * 0.4 + wisdom * 0.2, 0, 100);
  return {
    energy: Math.round(energy),
    health: Math.round(health),
    wisdom: Math.round(wisdom),
    mood: Math.round(mood),
  };
}

// ---- ledger parsing + folding (design §8.3, §11.2) ----

/**
 * Extract a valid PetEvent from a stored item's `content`. Returns null when the
 * shape is unrecognized or the schema_version is unknown (warns, design §11.1).
 */
export function parseEventContent(content: unknown): PetEvent | null {
  if (!content || typeof content !== "object") return null;
  const c = content as Record<string, unknown>;
  if (c.type !== "pet_event") return null;
  if (c.schema_version !== PET_SCHEMA_VERSION) {
    if (typeof console !== "undefined") {
      console.warn(`[contextpet] skipping pet_event with unknown schema_version`, c.schema_version);
    }
    return null;
  }
  if (typeof c.action !== "string" || !PET_ACTIONS.has(c.action)) return null;
  if (typeof c.event_id !== "string" || !c.event_id) return null;
  return {
    type: "pet_event",
    schema_version: PET_SCHEMA_VERSION,
    event_id: c.event_id,
    action: c.action as PetAction,
    xp_delta: typeof c.xp_delta === "number" ? c.xp_delta : 0,
    target_scope: typeof c.target_scope === "string" ? c.target_scope : "",
    result: (c.result as Record<string, unknown> | null | undefined) ?? null,
    client_timestamp: typeof c.client_timestamp === "string" ? c.client_timestamp : "",
    server_timestamp: typeof c.server_timestamp === "string" ? c.server_timestamp : null,
  };
}

/** Parse + dedup (by event_id) the raw items returned from POST /items. */
export function parseLedger(items: ContextItem[]): PetEvent[] {
  const seen = new Set<string>();
  const events: PetEvent[] = [];
  for (const item of items) {
    const ev = parseEventContent(item.content);
    if (!ev) continue;
    if (seen.has(ev.event_id)) continue;
    seen.add(ev.event_id);
    events.push(ev);
  }
  return events;
}

export interface Growth {
  xp: number;
  level: number;
  xpIntoLevel: number;
  xpForLevel: number;
  feedCount: number;
  walkCount: number;
  bathCount: number;
  sleepCount: number;
  streak: number;
  totalEvents: number;
  achievements: Achievement[];
}

/** xp -> level: floor(sqrt(xp/10)) + 1 (design §8.3). */
export function levelForXp(xp: number): number {
  return Math.floor(Math.sqrt(xp / 10)) + 1;
}

/** Cumulative XP required to reach the start of a given level. */
export function xpAtLevelStart(level: number): number {
  return 10 * (level - 1) ** 2;
}

/** Local natural-day key (YYYY-MM-DD) in the browser timezone (design §11.1). */
export function localDayKey(iso: string, tzOffsetMinutes?: number): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  // tzOffsetMinutes lets tests pin a timezone; default = environment local time.
  const offset = tzOffsetMinutes ?? d.getTimezoneOffset();
  const local = new Date(d.getTime() - offset * 60_000);
  return local.toISOString().slice(0, 10);
}

/**
 * Longest run of consecutive natural days ending at (or, with one grace day,
 * the day before) `today`. If neither today nor yesterday is active, streak = 0.
 */
export function computeStreak(dayKeys: Set<string>, today: Date, tzOffsetMinutes?: number): number {
  if (dayKeys.size === 0) return 0;
  const offset = tzOffsetMinutes ?? today.getTimezoneOffset();
  const keyOf = (ms: number) => new Date(ms - offset * 60_000).toISOString().slice(0, 10);
  const DAY = 86_400_000;
  const todayMs = today.getTime();
  let anchor: number;
  if (dayKeys.has(keyOf(todayMs))) anchor = todayMs;
  else if (dayKeys.has(keyOf(todayMs - DAY))) anchor = todayMs - DAY;
  else return 0;
  let streak = 0;
  for (let ms = anchor; dayKeys.has(keyOf(ms)); ms -= DAY) streak += 1;
  return streak;
}

export function foldLedger(events: PetEvent[], today: Date = new Date()): Growth {
  let rawXp = 0;
  const counts: Record<PetAction, number> = { feed: 0, walk: 0, bath: 0, sleep: 0 };
  const dayKeys = new Set<string>();
  for (const ev of events) {
    rawXp += ev.xp_delta;
    counts[ev.action] += 1;
    const ts = ev.server_timestamp || ev.client_timestamp;
    if (ts) {
      const key = localDayKey(ts);
      if (key) dayKeys.add(key);
    }
  }
  const xp = clamp(rawXp, 0, XP_CAP);
  const level = levelForXp(xp);
  const start = xpAtLevelStart(level);
  const next = xpAtLevelStart(level + 1);
  const growth: Growth = {
    xp,
    level,
    xpIntoLevel: xp - start,
    xpForLevel: next - start,
    feedCount: counts.feed,
    walkCount: counts.walk,
    bathCount: counts.bath,
    sleepCount: counts.sleep,
    streak: computeStreak(dayKeys, today),
    totalEvents: events.length,
    achievements: [],
  };
  growth.achievements = computeAchievements(growth);
  return growth;
}

// ---- achievements (design §8.3) ----

export interface Achievement {
  id: string;
  label: string;
  hint: string;
  unlocked: boolean;
}

interface AchievementRule {
  id: string;
  label: string;
  hint: string;
  test: (g: Growth) => boolean;
}

const ACHIEVEMENT_RULES: AchievementRule[] = [
  { id: "first_feed", label: "初次投喂", hint: "完成第一次投喂", test: (g) => g.feedCount >= 1 },
  { id: "first_walk", label: "初次散步", hint: "完成第一次散步", test: (g) => g.walkCount >= 1 },
  { id: "first_bath", label: "初次洗澡", hint: "完成第一次洗澡", test: (g) => g.bathCount >= 1 },
  { id: "first_sleep", label: "初次做梦", hint: "完成第一次睡觉", test: (g) => g.sleepCount >= 1 },
  { id: "feeder_10", label: "投喂达人", hint: "累计投喂 10 次", test: (g) => g.feedCount >= 10 },
  { id: "dreamer_10", label: "梦境收藏家", hint: "累计睡觉 10 次", test: (g) => g.sleepCount >= 10 },
  { id: "streak_3", label: "连续 3 天", hint: "连续活跃 3 天", test: (g) => g.streak >= 3 },
  { id: "streak_7", label: "连续一周", hint: "连续活跃 7 天", test: (g) => g.streak >= 7 },
  { id: "level_5", label: "成长之星", hint: "等级达到 5", test: (g) => g.level >= 5 },
];

export function computeAchievements(growth: Growth): Achievement[] {
  return ACHIEVEMENT_RULES.map((rule) => ({
    id: rule.id,
    label: rule.label,
    hint: rule.hint,
    unlocked: rule.test(growth),
  }));
}

// ---- animation / mood derivation (design §7.1) ----

export type AnimationState =
  | "idle"
  | "booting"
  | "refreshing"
  | "loading_ledger"
  | "feeding"
  | "walking"
  | "bathing"
  | "sleeping"
  | "level_up"
  | "error";

export type PetFace = "happy" | "relaxed" | "stable" | "tired" | "down";

export interface Expression {
  face: PetFace;
  sleepy: boolean;
  dirty: boolean;
  inspired: boolean;
}

/** Map vitals to the pet's facial state + priority modifiers (design §7.1 状态表情). */
export function deriveExpression(vitals: Vitals): Expression {
  const { mood, energy, health, wisdom } = vitals;
  let face: PetFace;
  if (mood >= 81) face = "happy";
  else if (mood >= 61) face = "relaxed";
  else if (mood >= 41) face = "stable";
  else if (mood >= 21) face = "tired";
  else face = "down";
  return {
    face,
    sleepy: energy < 30,
    dirty: health < 30,
    inspired: wisdom > 80,
  };
}

/** The action's running animation state (design §7.1 动画状态机). */
export function actionAnimationState(action: PetAction): AnimationState {
  switch (action) {
    case "feed":
      return "feeding";
    case "walk":
      return "walking";
    case "bath":
      return "bathing";
    case "sleep":
      return "sleeping";
  }
}

// ---- UI copy (i18n-ready, design §15) ----

export const MOOD_COPY: { max: number; text: string }[] = [
  { max: 20, text: "有点低落" },
  { max: 40, text: "状态一般" },
  { max: 60, text: "情绪稳定" },
  { max: 80, text: "心情不错" },
  { max: 100, text: "超开心" },
];

export function moodText(mood: number): string {
  return (MOOD_COPY.find((m) => mood <= m.max) ?? MOOD_COPY[MOOD_COPY.length - 1]).text;
}

export const PET_COPY = {
  vitals: { energy: "活力", health: "健康", wisdom: "智慧", mood: "心情" },
  actions: {
    feed: { label: "投喂", running: "上下文块正在送入洞里…" },
    walk: { label: "散步", running: "陪它在地道里走一走…" },
    bath: { label: "洗澡", running: "泡泡正在冲掉泥土…" },
    sleep: { label: "睡觉", running: "它缩回洞里做梦中…" },
  } as Record<PetAction, { label: string; running: string }>,
  loading: {
    booting: "正在闻一闻这片上下文…",
    refreshing: "正在检查上下文状态…",
    loading_ledger: "正在翻成长记录…",
    error: "它有点困惑，出了点状况",
  },
  empty: "还没有记忆，投喂第一条内容开始养成",
  idleBubble: (face: PetFace) => {
    switch (face) {
      case "happy":
        return "今天上下文很清爽！";
      case "relaxed":
        return "状态不错，要不要喂点什么？";
      case "stable":
        return "稳稳的，随时待命";
      case "tired":
        return "有点累了，想整理一点上下文";
      case "down":
        return "需要洗澡或睡觉整理一下啦";
    }
  },
} as const;

/** Honest per-action result copy tied to real data (design §8.3.1). */
export function describeActionResult(
  action: PetAction,
  result: Record<string, unknown> | null | undefined,
): string {
  const xp = XP_DELTA[action];
  switch (action) {
    case "feed":
      return `投喂成功，XP +${xp}。喂进去的内容还没消化（待提取 +1），活力可能暂降，洗澡/睡觉整理后会恢复。`;
    case "walk":
      return `陪它走了走，XP +${xp}（散步不影响记忆健康度）。`;
    case "bath": {
      const merged = numFrom(result, "merged");
      const archived = numFrom(result, "archived");
      const evolved = numFrom(result, "evolved");
      return `洗澡完成，XP +${xp}。整理结果：合并 ${merged}、归档 ${archived}、演化 ${evolved}，健康度随待收敛下降而回升。`;
    }
    case "sleep": {
      const total = numFrom(result, "total_dream_items");
      return `做了个梦，XP +${xp}。梦到 ${total} 条灵感，智慧随蒸馏候选/知识增加而上升。`;
    }
  }
}

function numFrom(obj: Record<string, unknown> | null | undefined, key: string): number {
  const v = obj?.[key];
  return typeof v === "number" ? v : 0;
}

/** Build a fresh pet_event for the `contextseek/pet` ledger. */
export function buildPetEvent(args: {
  action: PetAction;
  targetScope: string;
  result?: Record<string, unknown> | null;
  eventId: string;
  clientTimestamp: string;
}): PetEvent {
  return {
    type: "pet_event",
    schema_version: PET_SCHEMA_VERSION,
    event_id: args.eventId,
    action: args.action,
    xp_delta: XP_DELTA[args.action],
    target_scope: args.targetScope,
    result: args.result ?? null,
    client_timestamp: args.clientTimestamp,
  };
}

export const EMPTY_GROWTH: Growth = {
  xp: 0,
  level: 1,
  xpIntoLevel: 0,
  xpForLevel: 10,
  feedCount: 0,
  walkCount: 0,
  bathCount: 0,
  sleepCount: 0,
  streak: 0,
  totalEvents: 0,
  achievements: computeAchievements({
    xp: 0,
    level: 1,
    xpIntoLevel: 0,
    xpForLevel: 10,
    feedCount: 0,
    walkCount: 0,
    bathCount: 0,
    sleepCount: 0,
    streak: 0,
    totalEvents: 0,
    achievements: [],
  }),
};
