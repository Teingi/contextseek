import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

import { PetAvatar } from "@/components/pet/PetAvatar";
import { Achievements, GrowthSummary, Timeline, VitalsBars } from "@/components/pet/PetStats";
import "@/components/pet/petAnimations.css";
import { useScope } from "@/context/ScopeContext";
import { ctx } from "@/lib/ctxClient";
import type { Overview } from "@/lib/types";
import {
  DEFAULT_PET_THEME,
  EMPTY_GROWTH,
  PET_COPY,
  PET_SCOPE,
  PET_SOURCE,
  PET_TAG,
  PET_THEMES,
  actionAnimationState,
  buildPetEvent,
  computeVitals,
  deriveExpression,
  foldLedger,
  isPetThemeId,
  moodText,
  parseLedger,
  type AnimationState,
  type Growth,
  type PetAction,
  type PetEvent,
  type PetThemeId,
  type Vitals,
} from "@/lib/pet";

const THEME_STORAGE_KEY = "ctx.petTheme";

function readStoredTheme(): PetThemeId {
  if (typeof window === "undefined") return DEFAULT_PET_THEME;
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  return isPetThemeId(stored) ? stored : DEFAULT_PET_THEME;
}

interface PetCompanionContextValue {
  notifyPetSuccess: (
    action: PetAction,
    result?: Record<string, unknown> | null,
    options?: { persist?: boolean },
  ) => Promise<void>;
  notifyPetError: (action: PetAction) => void;
}

const PetCompanionContext = createContext<PetCompanionContextValue | null>(null);

const SETTLE_MS = 1200;
const FLOATY_MS = 1200;

export function PetCompanionProvider({ children }: { children: React.ReactNode }) {
  const { scope } = useScope();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [events, setEvents] = useState<PetEvent[]>([]);
  const [growth, setGrowth] = useState<Growth>(EMPTY_GROWTH);
  const [anim, setAnim] = useState<AnimationState>("booting");
  const [bubble, setBubble] = useState<string>("正在闻一闻这片上下文...");
  const [floatingXp, setFloatingXp] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState<PetThemeId>(readStoredTheme);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    if (typeof window !== "undefined") window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  const vitals: Vitals | null = overview ? computeVitals(overview) : null;
  const displayVitals: Vitals = vitals ?? { energy: 100, health: 100, wisdom: 20, mood: 84 };
  const expression = deriveExpression(displayVitals);

  const schedule = useCallback((fn: () => void, ms: number) => {
    const id = window.setTimeout(fn, ms);
    timers.current.push(id);
  }, []);

  const refreshPetState = useCallback(async () => {
    const [overviewRes, ledgerRes] = await Promise.allSettled([
      ctx.overview(scope),
      ctx.items({ scope: PET_SCOPE }),
    ]);
    if (overviewRes.status === "fulfilled") setOverview(overviewRes.value);
    if (ledgerRes.status === "fulfilled") {
      const parsed = parseLedger(ledgerRes.value.items);
      setEvents(parsed);
      setGrowth(foldLedger(parsed));
    }
    return { overviewRes, ledgerRes };
  }, [scope]);

  useEffect(() => () => timers.current.forEach((id) => window.clearTimeout(id)), []);

  useEffect(() => {
    let cancelled = false;
    setAnim("booting");
    setBubble("正在检查这片上下文...");
    void refreshPetState().then(() => {
      if (cancelled) return;
      setAnim("idle");
      setBubble("");
    });
    return () => {
      cancelled = true;
    };
  }, [refreshPetState]);

  const settleToIdle = useCallback(() => {
    schedule(() => {
      setAnim("idle");
      setBubble("");
    }, SETTLE_MS);
  }, [schedule]);

  const notifyPetSuccess = useCallback(
    async (
      action: PetAction,
      result?: Record<string, unknown> | null,
      options?: { persist?: boolean },
    ) => {
      const persist = options?.persist ?? true;
      const event = buildPetEvent({
        action,
        targetScope: scope,
        result,
        eventId: randomId(),
        clientTimestamp: new Date().toISOString(),
      });

      setAnim(actionAnimationState(action));
      setBubble(successBubble(action));
      if (persist) {
        setFloatingXp(event.xp_delta);
        schedule(() => setFloatingXp(null), FLOATY_MS);
      }

      if (persist) {
        try {
          await ctx.add({ scope: PET_SCOPE, content: event, source: PET_SOURCE, tags: [PET_TAG] });
        } catch {
          setBubble("动作完成了，但成长记录没保存成功");
        }
      }

      const oldLevel = growth.level;
      const { ledgerRes } = await refreshPetState();
      const nextGrowth =
        ledgerRes.status === "fulfilled" ? foldLedger(parseLedger(ledgerRes.value.items)) : growth;
      if (persist && nextGrowth.level > oldLevel) {
        setAnim("level_up");
        setBubble("升级啦！");
      }
      settleToIdle();
    },
    [growth, refreshPetState, schedule, scope, settleToIdle],
  );

  const notifyPetError = useCallback(
    (action: PetAction) => {
      setAnim("error");
      setBubble(`${PET_COPY.actions[action].label}失败了，它有点困惑`);
      settleToIdle();
    },
    [settleToIdle],
  );

  return (
    <PetCompanionContext.Provider value={{ notifyPetSuccess, notifyPetError }}>
      {children}
      <GlobalContextPet
        anim={anim}
        bubble={bubble}
        events={events}
        expression={expression}
        floatingXp={floatingXp}
        growth={growth}
        open={open}
        setOpen={setOpen}
        vitals={vitals}
        displayVitals={displayVitals}
        theme={theme}
        setTheme={setTheme}
      />
    </PetCompanionContext.Provider>
  );
}

export function usePetCompanion() {
  const value = useContext(PetCompanionContext);
  if (!value) throw new Error("usePetCompanion must be used within PetCompanionProvider");
  return value;
}

function GlobalContextPet({
  anim,
  bubble,
  events,
  expression,
  floatingXp,
  growth,
  open,
  setOpen,
  vitals,
  displayVitals,
  theme,
  setTheme,
}: {
  anim: AnimationState;
  bubble: string;
  events: PetEvent[];
  expression: ReturnType<typeof deriveExpression>;
  floatingXp: number | null;
  growth: Growth;
  open: boolean;
  setOpen: (open: boolean) => void;
  vitals: Vitals | null;
  displayVitals: Vitals;
  theme: PetThemeId;
  setTheme: (theme: PetThemeId) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [paused, setPaused] = useState(false);
  const reduceMotion = usePrefersReducedMotion();

  // place top-right on mount, and keep inside the viewport on resize
  useEffect(() => {
    if (typeof window === "undefined") return;
    const reclamp = () =>
      setPos((p) => {
        const b = wanderBounds();
        return p
          ? { x: clampN(p.x, b.minX, b.maxX), y: clampN(p.y, b.minY, b.maxY) }
          : { x: b.maxX, y: b.minY };
      });
    reclamp();
    window.addEventListener("resize", reclamp);
    return () => window.removeEventListener("resize", reclamp);
  }, []);

  // roam: pick a new random target across the whole screen on an interval.
  // Paused while hovered/focused (so it can be clicked) or while the card is open.
  useEffect(() => {
    if (reduceMotion || paused || open || typeof window === "undefined") return;
    // gentle wander: drift a bounded distance from the current spot, not teleport
    // anywhere — keeps the motion calm and slow.
    const step = () => {
      setPos((prev) => {
        const b = wanderBounds();
        const base = prev ?? { x: b.maxX, y: b.minY };
        const rx = (b.maxX - b.minX) * 0.4;
        const ry = (b.maxY - b.minY) * 0.4;
        return {
          x: clampN(base.x + rand(-rx, rx), b.minX, b.maxX),
          y: clampN(base.y + rand(-ry, ry), b.minY, b.maxY),
        };
      });
    };
    const kick = window.setTimeout(step, 1800);
    const id = window.setInterval(step, 13000);
    return () => {
      window.clearTimeout(kick);
      window.clearInterval(id);
    };
  }, [reduceMotion, paused, open]);

  const freeze = useCallback(() => {
    const el = ref.current;
    if (el) {
      const r = el.getBoundingClientRect();
      setPos({ x: r.left, y: r.top });
    }
    setPaused(true);
  }, []);
  const unfreeze = useCallback(() => setPaused(false), []);

  const vw = typeof window !== "undefined" ? window.innerWidth : 1280;
  const side: "left" | "right" = pos && pos.x < vw / 2 ? "right" : "left";
  const wanderStyle = pos
    ? ({ left: pos.x, top: pos.y, right: "auto", bottom: "auto" } as CSSProperties)
    : undefined;
  const cardStyle = open && pos ? cardPosition(pos) : undefined;

  return (
    <>
      <div
        ref={ref}
        className="global-context-pet"
        data-anim={anim}
        data-cp-theme={theme}
        data-side={side}
        style={wanderStyle}
        onMouseEnter={freeze}
        onMouseLeave={unfreeze}
        onFocusCapture={freeze}
        onBlurCapture={unfreeze}
      >
        {bubble || vitals ? (
          <div className="global-context-pet-bubble">
            {bubble || `${moodText(displayVitals.mood)}，正在陪你整理上下文`}
          </div>
        ) : null}
        <button
          type="button"
          className="global-context-pet-button"
          aria-label="打开 ContextPet 状态"
          onClick={() => {
            freeze();
            setOpen(!open);
          }}
        >
          <span className="global-context-pet-aura" />
          <span className="global-context-pet-orbit" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span className="global-context-pet-ground" />
          <PetAvatar anim={anim} expression={expression} />
          {floatingXp != null && <span className="global-context-pet-xp">+{floatingXp} XP</span>}
        </button>
      </div>
      {open && (
        <div className="global-context-pet-card" data-cp-theme={theme} style={cardStyle}>
          <div className="global-context-pet-card-hero">
            <div>
              <div className="cp-wordmark">
                CONTEXT<span className="cp-slash">//</span>PET
              </div>
              <div className="cp-subtitle">跟随写入 · 检索 · 整理成长</div>
            </div>
            <div className="cp-hero-right">
              <div className="global-context-pet-level">{growth.level}</div>
              <button
                type="button"
                className="cp-close"
                aria-label="收起 ContextPet"
                onClick={() => setOpen(false)}
              >
                ×
              </button>
            </div>
          </div>
          <div className="cp-theme-switch" role="group" aria-label="切换 ContextPet 风格">
            {PET_THEMES.map((t) => (
              <button
                key={t.id}
                type="button"
                className="cp-theme-btn"
                data-on={t.id === theme || undefined}
                title={t.hint}
                onClick={() => setTheme(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="cp-stack">
            <VitalsBars vitals={displayVitals} empty={false} />
            <GrowthSummary growth={growth} />
            <Achievements growth={growth} />
            <Timeline events={events} />
          </div>
        </div>
      )}
    </>
  );
}

// ---- full-screen roaming helpers ----

const PET_SIZE = 138;
const WANDER_MARGIN = 16;
const CARD_W = 336;

function clampN(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}
function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}
function wanderBounds() {
  const w = typeof window !== "undefined" ? window.innerWidth : 1280;
  const h = typeof window !== "undefined" ? window.innerHeight : 800;
  const minX = WANDER_MARGIN;
  const minY = WANDER_MARGIN;
  return {
    minX,
    minY,
    maxX: Math.max(minX, w - PET_SIZE - WANDER_MARGIN),
    maxY: Math.max(minY, h - PET_SIZE - WANDER_MARGIN),
  };
}
function cardPosition(p: { x: number; y: number }): CSSProperties {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const estH = Math.min(600, vh * 0.74);
  let left = p.x + PET_SIZE / 2 - CARD_W / 2;
  left = clampN(left, 12, Math.max(12, vw - CARD_W - 12));
  let top = p.y + PET_SIZE + 10;
  if (top + estH > vh - 12) top = p.y - estH - 10;
  top = clampN(top, 12, Math.max(12, vh - estH - 12));
  return { left, top, right: "auto", bottom: "auto" };
}

function usePrefersReducedMotion(): boolean {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduce(mq.matches);
    update();
    mq.addEventListener?.("change", update);
    return () => mq.removeEventListener?.("change", update);
  }, []);
  return reduce;
}

function successBubble(action: PetAction): string {
  switch (action) {
    case "feed":
      return "吃到新的上下文了！";
    case "walk":
      return "刚刚陪你找了一圈线索";
    case "bath":
      return "上下文地洞清爽了一点";
    case "sleep":
      return "它做了个关于知识的梦";
  }
}

function randomId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `pet-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
