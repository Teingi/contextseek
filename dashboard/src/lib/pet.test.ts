import { describe, expect, it, vi } from "vitest";

import type { ContextItem, Overview } from "./types";
import {
  computeAchievements,
  computeStreak,
  computeVitals,
  deriveExpression,
  describeActionResult,
  foldLedger,
  knowledgeCount,
  levelForXp,
  localDayKey,
  parseLedger,
  XP_CAP,
  XP_DELTA,
  type PetEvent,
} from "./pet";

const overview = (o: Partial<Overview>): Overview => ({
  total_items: 0,
  stage_distribution: {},
  pending_extraction: 0,
  pending_convergence: 0,
  distill_candidates: 0,
  ...o,
});

describe("computeVitals", () => {
  it("returns healthy defaults for an empty scope", () => {
    const v = computeVitals(overview({}));
    expect(v.energy).toBe(100);
    expect(v.health).toBe(100);
    expect(v.wisdom).toBe(20);
    expect(v.mood).toBe(84);
  });

  it("clamps energy/health to their floor of 10", () => {
    const v = computeVitals(overview({ pending_extraction: 100, pending_convergence: 100 }));
    expect(v.energy).toBe(10);
    expect(v.health).toBe(10);
  });

  it("applies the 3x / 4x penalties to energy/health", () => {
    const v = computeVitals(overview({ pending_extraction: 5, pending_convergence: 5 }));
    expect(v.energy).toBe(85); // 100 - 5*3
    expect(v.health).toBe(80); // 100 - 5*4
  });

  it("derives knowledge_count from stage_distribution for wisdom", () => {
    const v = computeVitals(
      overview({
        total_items: 10,
        stage_distribution: { knowledge: 3, skill: 2, raw: 5 },
        distill_candidates: 2,
      }),
    );
    // knowledge_ratio = 5/10 = 0.5 -> wisdom = 20 + 2*6 + 0.5*40 = 52
    expect(v.wisdom).toBe(52);
  });

  it("clamps wisdom to 100", () => {
    const v = computeVitals(
      overview({ total_items: 10, stage_distribution: { knowledge: 10 }, distill_candidates: 50 }),
    );
    expect(v.wisdom).toBe(100);
  });
});

describe("knowledgeCount", () => {
  it("sums knowledge + skill stages, tolerating missing keys", () => {
    expect(knowledgeCount({ knowledge: 3, skill: 2 })).toBe(5);
    expect(knowledgeCount({ raw: 9 })).toBe(0);
    expect(knowledgeCount(null)).toBe(0);
  });
});

describe("levelForXp", () => {
  it("maps xp to level via floor(sqrt(xp/10))+1", () => {
    expect(levelForXp(0)).toBe(1);
    expect(levelForXp(9)).toBe(1);
    expect(levelForXp(10)).toBe(2);
    expect(levelForXp(40)).toBe(3);
    expect(levelForXp(90)).toBe(4);
  });
});

const ev = (over: Partial<PetEvent>): PetEvent => ({
  type: "pet_event",
  schema_version: 1,
  event_id: Math.random().toString(36),
  action: "feed",
  xp_delta: XP_DELTA.feed,
  target_scope: "demo",
  result: null,
  client_timestamp: "2026-06-09T08:00:00.000Z",
  ...over,
});

describe("foldLedger", () => {
  it("returns the initial state for an empty ledger", () => {
    const g = foldLedger([]);
    expect(g.level).toBe(1);
    expect(g.xp).toBe(0);
    expect(g.feedCount).toBe(0);
    expect(g.achievements.every((a) => !a.unlocked)).toBe(true);
  });

  it("accumulates xp and per-action counts", () => {
    const g = foldLedger([
      ev({ action: "feed", xp_delta: 10 }),
      ev({ action: "feed", xp_delta: 10 }),
      ev({ action: "bath", xp_delta: 15 }),
      ev({ action: "sleep", xp_delta: 20 }),
    ]);
    expect(g.xp).toBe(55);
    expect(g.feedCount).toBe(2);
    expect(g.bathCount).toBe(1);
    expect(g.sleepCount).toBe(1);
    expect(g.level).toBe(levelForXp(55));
  });

  it("caps xp at XP_CAP", () => {
    const g = foldLedger([ev({ xp_delta: XP_CAP + 5000 })]);
    expect(g.xp).toBe(XP_CAP);
  });

  it("unlocks achievements exactly at threshold", () => {
    const feeds = Array.from({ length: 10 }, () => ev({ action: "feed" }));
    const g = foldLedger(feeds);
    const a = computeAchievements(g);
    expect(a.find((x) => x.id === "first_feed")?.unlocked).toBe(true);
    expect(a.find((x) => x.id === "feeder_10")?.unlocked).toBe(true);
    expect(a.find((x) => x.id === "first_bath")?.unlocked).toBe(false);
  });
});

describe("parseLedger", () => {
  const item = (content: unknown, id = "x"): ContextItem =>
    ({ id, content } as unknown as ContextItem);

  it("dedupes by event_id", () => {
    const events = parseLedger([
      item({ type: "pet_event", schema_version: 1, event_id: "a", action: "feed", xp_delta: 10 }),
      item({ type: "pet_event", schema_version: 1, event_id: "a", action: "feed", xp_delta: 10 }, "y"),
    ]);
    expect(events).toHaveLength(1);
  });

  it("skips unknown schema_version and non-pet content", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const events = parseLedger([
      item({ type: "pet_event", schema_version: 99, event_id: "a", action: "feed" }),
      item({ type: "other", event_id: "b" }),
      item("plain string"),
    ]);
    expect(events).toHaveLength(0);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe("computeStreak", () => {
  const today = new Date("2026-06-09T12:00:00.000Z");
  const keys = (...d: string[]) => new Set(d);

  it("counts consecutive days ending today", () => {
    expect(computeStreak(keys("2026-06-07", "2026-06-08", "2026-06-09"), today)).toBe(3);
  });

  it("breaks on a gap", () => {
    expect(computeStreak(keys("2026-06-06", "2026-06-08", "2026-06-09"), today)).toBe(2);
  });

  it("allows yesterday as a grace anchor when today is inactive", () => {
    expect(computeStreak(keys("2026-06-07", "2026-06-08"), today)).toBe(2);
  });

  it("returns 0 when neither today nor yesterday is active", () => {
    expect(computeStreak(keys("2026-06-01"), today)).toBe(0);
    expect(computeStreak(new Set(), today)).toBe(0);
  });
});

describe("localDayKey", () => {
  it("formats a natural-day key", () => {
    expect(localDayKey("2026-06-09T23:30:00.000Z", 0)).toBe("2026-06-09");
  });
  it("returns empty for invalid input", () => {
    expect(localDayKey("not-a-date")).toBe("");
  });
});

describe("deriveExpression", () => {
  it("maps mood bands to faces", () => {
    expect(deriveExpression({ mood: 90, energy: 80, health: 80, wisdom: 50 }).face).toBe("happy");
    expect(deriveExpression({ mood: 70, energy: 80, health: 80, wisdom: 50 }).face).toBe("relaxed");
    expect(deriveExpression({ mood: 50, energy: 80, health: 80, wisdom: 50 }).face).toBe("stable");
    expect(deriveExpression({ mood: 30, energy: 80, health: 80, wisdom: 50 }).face).toBe("tired");
    expect(deriveExpression({ mood: 10, energy: 80, health: 80, wisdom: 50 }).face).toBe("down");
  });

  it("flags sleepy / dirty / inspired modifiers", () => {
    const e = deriveExpression({ mood: 50, energy: 20, health: 20, wisdom: 90 });
    expect(e.sleepy).toBe(true);
    expect(e.dirty).toBe(true);
    expect(e.inspired).toBe(true);
  });
});

describe("describeActionResult", () => {
  it("references real compact/dream numbers", () => {
    expect(describeActionResult("bath", { merged: 3, archived: 1, evolved: 0 })).toContain("合并 3");
    expect(describeActionResult("sleep", { total_dream_items: 5 })).toContain("5 条灵感");
    expect(describeActionResult("walk", null)).toContain("不影响记忆健康度");
  });
});
