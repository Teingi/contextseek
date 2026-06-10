// ContextPet — "Cyber Burrow" neon-wireframe marmot. Strokes use currentColor so
// petAnimations.css can theme the whole creature by face (cyan/amber/red...) via a
// single `color`. State is driven by data-* attributes; CSS owns all motion + glow.

import type { AnimationState, Expression } from "@/lib/pet";

export function PetAvatar({
  anim,
  expression,
}: {
  anim: AnimationState;
  expression: Expression;
}) {
  const { face, sleepy, dirty, inspired } = expression;
  const eyesClosed = anim === "sleeping" || (sleepy && anim === "idle");
  const loading = anim === "booting" || anim === "refreshing" || anim === "loading_ledger";
  const happyEyes = face === "happy" && !eyesClosed;

  return (
    <svg
      className="pet-avatar"
      data-anim={anim}
      data-face={face}
      data-dirty={dirty || undefined}
      data-inspired={inspired || undefined}
      viewBox="0 0 200 200"
      role="img"
      aria-label={`ContextPet 赛博土拨鼠，表情：${face}`}
    >
      {/* burrow ring / data well */}
      <ellipse className="cp-line-thin" cx="100" cy="178" rx="74" ry="13" opacity="0.5" />

      {/* loading: a context-block orbiting the well */}
      {loading && <rect className="pet-context-block cp-data" x="93" y="22" width="14" height="14" rx="3" />}

      <g className="pet-body-group">
        {/* tail */}
        <path className="pet-tail cp-line" d="M150 142 q26 -8 22 -34" />

        {/* body */}
        <path className="cp-fill-dark" d="M58 132 q0 -52 42 -52 q42 0 42 52 q0 34 -42 34 q-42 0 -42 -34 Z" />
        <path className="cp-line" d="M58 132 q0 -52 42 -52 q42 0 42 52 q0 34 -42 34 q-42 0 -42 -34 Z" />
        {/* belly scanline */}
        <path className="cp-line-thin" d="M80 150 q20 12 40 0" />

        {/* ears */}
        <path className="cp-line" d="M70 84 q-8 -18 4 -24 q10 4 8 22" />
        <path className="cp-line" d="M130 84 q8 -18 -4 -24 q-10 4 -8 22" />

        {/* head */}
        <path className="cp-fill-dark" d="M64 92 q0 -34 36 -34 q36 0 36 34 q0 30 -36 30 q-36 0 -36 -30 Z" />
        <path className="cp-line" d="M64 92 q0 -34 36 -34 q36 0 36 34 q0 30 -36 30 q-36 0 -36 -30 Z" />

        {/* blush cheeks */}
        <circle className="cp-dot" cx="72" cy="101" r="4.5" opacity="0.35" />
        <circle className="cp-dot" cx="128" cy="101" r="4.5" opacity="0.35" />

        {/* eyes — happy faces get cheerful upward "‿" smile-eyes */}
        <g className="pet-eye pet-eye-1" data-closed={eyesClosed || undefined}>
          {happyEyes ? (
            <path className="cp-line" d="M77 90 q9 9 18 0" />
          ) : (
            <circle className="cp-dot" cx="86" cy="89" r="5.4" />
          )}
        </g>
        <g className="pet-eye pet-eye-2" data-closed={eyesClosed || undefined}>
          {happyEyes ? (
            <path className="cp-line" d="M105 90 q9 9 18 0" />
          ) : (
            <circle className="cp-dot" cx="114" cy="89" r="5.4" />
          )}
        </g>

        {/* snout + smile — big happy grin for positive moods */}
        <circle className="cp-dot" cx="100" cy="104" r="3.2" />
        {face === "down" ? (
          <path className="cp-line-thin" d="M90 117 q10 -7 20 0" />
        ) : face === "tired" ? (
          <path className="cp-line-thin" d="M91 114 q9 5 18 0" />
        ) : face === "happy" ? (
          <path className="cp-line" d="M79 107 q21 23 42 0" />
        ) : (
          <path className="cp-line" d="M86 110 q14 15 28 0" />
        )}

        {/* whiskers */}
        <path className="cp-line-thin" d="M104 104 h20 M104 108 h17" opacity="0.6" />
        <path className="cp-line-thin" d="M96 104 h-20 M96 108 h-17" opacity="0.6" />

        {/* front paws */}
        <path className="cp-line" d="M80 166 q2 8 -8 9" />
        <path className="cp-line" d="M120 166 q-2 8 8 9" />

        {/* health-low: red corruption shards */}
        <g className="pet-dirt">
          <path className="cp-shard" d="M76 138 l5 -7 l3 8 Z" />
          <path className="cp-shard" d="M118 150 l5 -6 l2 7 Z" />
          <path className="cp-shard" d="M100 158 l4 -7 l4 7 Z" />
        </g>
      </g>

      {/* wisdom-high: inspiration ore floating above */}
      <g className="pet-lightbulb pet-inspire-pulse">
        <path className="cp-ore" d="M100 30 l9 7 l-3 12 l-12 0 l-3 -12 Z" />
      </g>

      {/* happy: cheerful twinkles beside the face */}
      {happyEyes && (anim === "idle" || anim === "feeding" || anim === "walking") && (
        <>
          <path className="cp-data" d="M54 64 l1.6 4 l4 1.6 l-4 1.6 l-1.6 4 l-1.6 -4 l-4 -1.6 l4 -1.6 Z" />
          <path className="cp-data" d="M148 56 l1.4 3.4 l3.4 1.4 l-3.4 1.4 l-1.4 3.4 l-1.4 -3.4 l-3.4 -1.4 l3.4 -1.4 Z" />
        </>
      )}

      {/* sleep bubbles */}
      {anim === "sleeping" && (
        <text className="pet-bubble-zzz cp-dot" x="138" y="58" fontSize="16" fontFamily="JetBrains Mono, monospace">
          z
        </text>
      )}

      {/* bath: data droplets */}
      {anim === "bathing" && (
        <>
          <circle className="pet-droplet cp-drop" cx="72" cy="70" r="3.6" />
          <circle className="pet-droplet cp-drop" cx="128" cy="64" r="3.6" style={{ animationDelay: "0.3s" }} />
          <circle className="pet-droplet cp-drop" cx="100" cy="56" r="3" style={{ animationDelay: "0.6s" }} />
        </>
      )}

      {/* feeding: context block flying in */}
      {anim === "feeding" && <rect className="pet-context-block cp-data" x="93" y="30" width="13" height="13" rx="3" />}

      {/* level-up sparks */}
      {anim === "level_up" && (
        <>
          <circle className="pet-spark cp-data" cx="60" cy="60" r="5" />
          <circle className="pet-spark cp-ore" cx="140" cy="50" r="5" style={{ animationDelay: "0.15s" }} />
          <circle className="pet-spark cp-dot" cx="100" cy="34" r="4" style={{ animationDelay: "0.3s" }} />
        </>
      )}
    </svg>
  );
}
