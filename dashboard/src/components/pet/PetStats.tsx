// ContextPet readout (Cyber Burrow): vitals as neon gauges (real-time, from
// overview), growth as a terminal stat block (persistent, from the ledger),
// achievements as ore chips, and the timeline as a "dig log". Two layers stay
// visually distinct: "current mirror" vs "growth record" (design §8).

import type { CSSProperties } from "react";

import { Award, Flame } from "lucide-react";

import {
  PET_COPY,
  TIMELINE_LIMIT,
  type Growth,
  type PetEvent,
  type Vitals,
} from "@/lib/pet";

const VITAL_META: Record<keyof Vitals, { code: string; color: string }> = {
  energy: { code: "PWR", color: "var(--cp-amber)" },
  health: { code: "INTEG", color: "var(--cp-lime)" },
  wisdom: { code: "KNOW", color: "var(--cp-magenta)" },
  mood: { code: "SYNC", color: "var(--cp-cyan)" },
};

export function VitalsBars({ vitals, empty }: { vitals: Vitals; empty: boolean }) {
  return (
    <div>
      {(Object.keys(PET_COPY.vitals) as (keyof Vitals)[]).map((k) => {
        const meta = VITAL_META[k];
        return (
          <div key={k} className="cp-vital-row" style={{ "--cp-c": meta.color } as CSSProperties}>
            <div className="cp-vital-head">
              <span>
                <span className="cp-vital-name">{PET_COPY.vitals[k]}</span>
                <span className="cp-vital-code">{meta.code}</span>
              </span>
              <span className="cp-vital-val">{vitals[k]}</span>
            </div>
            <div className="cp-meter">
              <div className="cp-meter-fill" style={{ width: `${vitals[k]}%` }} />
            </div>
          </div>
        );
      })}
      {empty && <p className="cp-empty" style={{ marginTop: 10 }}>{PET_COPY.empty}</p>}
    </div>
  );
}

export function GrowthSummary({ growth }: { growth: Growth }) {
  const pct = growth.xpForLevel > 0 ? (growth.xpIntoLevel / growth.xpForLevel) * 100 : 0;
  return (
    <div>
      <div className="cp-growth-top">
        <span className="cp-xp">XP {growth.xp}</span>
        <span className="cp-streak">
          <Flame className="h-3.5 w-3.5" /> 连续 {growth.streak} 天
        </span>
      </div>
      <div className="cp-xpbar">
        <div className="cp-xpbar-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="cp-next">距下一级还需 {Math.max(0, growth.xpForLevel - growth.xpIntoLevel)} XP</div>
      <div className="cp-counters">
        <Counter label="投喂" value={growth.feedCount} />
        <Counter label="散步" value={growth.walkCount} />
        <Counter label="洗澡" value={growth.bathCount} />
        <Counter label="睡觉" value={growth.sleepCount} />
      </div>
    </div>
  );
}

function Counter({ label, value }: { label: string; value: number }) {
  return (
    <div className="cp-counter">
      <div className="cp-counter-val">{value}</div>
      <div className="cp-counter-label">{label}</div>
    </div>
  );
}

export function Achievements({ growth }: { growth: Growth }) {
  const unlocked = growth.achievements.filter((a) => a.unlocked);
  return (
    <div>
      <div className="cp-section-label">
        <Award className="h-3.5 w-3.5" /> 成就矿石 {unlocked.length}/{growth.achievements.length}
      </div>
      <div className="cp-ores">
        {growth.achievements.map((a) => (
          <span key={a.id} className="cp-ore" data-on={a.unlocked || undefined} title={a.hint}>
            {a.label}
          </span>
        ))}
      </div>
    </div>
  );
}

const ACTION_LABEL: Record<PetEvent["action"], string> = {
  feed: "投喂",
  walk: "散步",
  bath: "洗澡",
  sleep: "睡觉",
};

export function Timeline({ events }: { events: PetEvent[] }) {
  const recent = [...events].slice(-TIMELINE_LIMIT).reverse();
  return (
    <div>
      <div className="cp-section-label">挖掘日志 · DIG LOG</div>
      {recent.length === 0 ? (
        <p className="cp-empty">还没有照料记录，去写入 / 检索 / 整理触发一次吧。</p>
      ) : (
        <div className="cp-log">
          {recent.map((e) => (
            <div key={e.event_id} className="cp-log-row">
              <span className="flex items-center gap-2">
                <span className="cp-tag" data-action={e.action}>
                  {ACTION_LABEL[e.action]}
                </span>
                <span className="cp-log-xp">+{e.xp_delta}</span>
                {e.target_scope && <span className="cp-log-scope">@{e.target_scope}</span>}
              </span>
              <span className="cp-log-time">{formatTime(e.server_timestamp || e.client_timestamp)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
