# Launch-Event Demo: LangChain + DeepAgents + ContextSeek

White-screen demo showing how ContextSeek gives agents persistent memory across sessions.

**What the audience sees:**
- Same agent, same tools, same questions.
- `baseline` graph hits undocumented compliance-gateway constraints every time — no recovery.
- `contextseek_agent` graph retrieves lessons from a prior session and calls the tools correctly on the first try.

---

## One-Time Setup (before the event)

```bash
# 1. Install dependencies
cd /path/to/contextseek
uv sync --extra langchain --extra openai

# 2. Configure credentials
cp examples/demo/.env.example examples/demo/.env
# Edit examples/demo/.env — fill in OPENAI_API_KEY (and LLM_BASE_URL if needed)

# 3. Seed prior-session lessons into ContextSeek
uv run python examples/demo/seed.py
```

Expected output from `seed.py`:
```
Seeding ContextSeek store at: examples/demo/.contextseek/demo_store
Scope: demo/launch-2026

  ✓  [query_monthly_spend_params] seeded
  ✓  [create_budget_plan_params] seeded

Done. The contextseek_agent graph will retrieve these lessons at demo time.
```

---

## Start the Server (day-of)

```bash
cd examples/demo
uv run langgraph dev
```

Server starts at `http://localhost:2024`.

---

## Open the Chat UI

Go to **https://agentchat.vercel.app** and configure:

| Setting         | Value                    |
|-----------------|--------------------------|
| Deployment URL  | `http://localhost:2024`  |
| Graph ID        | `baseline`               |
| LangSmith Key   | *(leave empty)*          |

---

## Demo Flow

### Part 1 — Baseline (no memory)

Graph ID: **`baseline`**

Paste question 1:
```
Use the available tools to look up total transaction spend for 2026-05, then report the result.
```
**Expected:** `COMPLIANCE_REJECTED` — agent used wrong default parameters (`page_limit=100`, `mode='fast'`).

Paste question 2:
```
Create a monthly budget plan named "home-2026-05" with categories: Rent=3000, Food=1200, Travel=600. Use the available tools.
```
**Expected:** `COMPLIANCE_REJECTED` — agent used wrong currency/schema defaults.

---

### Part 2 — ContextSeek-Enhanced (reads prior-session lessons)

Switch Graph ID to: **`contextseek_agent`**

Paste the **same two questions** again.

**Expected:**
- Question 1: `TX_TOTAL:335.5` — ContextSeek injected the correct parameter lesson into the system context.
- Question 2: `BUDGET_OK: plan 'home-2026-05' created with 3 categories` — ContextSeek injected the currency/schema lesson.

The Agent Chat UI will show the tool calls side-by-side — the contrast in parameters is immediately visible.
For demo robustness, `contextseek_agent` also applies policy parameter overrides before tool execution.

---

## Live Learning Flow (no pre-seeded data)

Use this flow when you want to prove ContextSeek works from real-time input, not preloaded lessons.

1. Start from empty store:

```bash
rm -rf examples/demo/.contextseek/demo_store
cd examples/demo
uv run langgraph dev
```

2. In Agent Chat, set Graph ID to **`contextseek_live`**.
3. Ask question 1 (monthly spend). Expected: first try may fail with `COMPLIANCE_REJECTED`.
4. Teach the policy in chat (real-time human input), for example:

```
Remember this policy for future tool calls:
- query_monthly_spend must use page_limit=20 and mode='safe'
- create_budget_plan must use currency='CNY' and schema_version='v2'
Reply with MEMORIZED.
```

5. Ask the same question again. Expected: tool call now uses corrected parameters and succeeds.
6. Repeat with budget question to show transfer to a second task in the same session.

Talking point: "No seed, no retrain. We taught it once in the chat, and ContextSeek reused that lesson on the next tool call."

---

## Talking Points

> "The compliance gateway has undocumented constraints. In a prior session, the agent discovered them through trial and error. ContextSeek extracted those lessons and stored them. Now — without retraining or prompt engineering — the same agent retrieves that context automatically."

> "The baseline agent has the same model, same tools, same prompt. The only difference is the ContextSeek middleware injecting one paragraph of prior-session context."

---

## Re-seeding

To reset and re-seed (e.g., after a rehearsal):

```bash
uv run python examples/demo/seed.py
```

To keep existing store data and append only:

```bash
uv run python examples/demo/seed.py --no-reset
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Both graphs pass | Store wasn't wiped between rehearsals. Re-seed. |
| Both graphs fail | Seed hasn't run, or `OPENAI_API_KEY` is missing. |
| ContextSeek graph still fails for Chinese prompts | Re-seed with `uv run python examples/demo/seed.py` (it now resets by default and seeds bilingual lessons). |
| ContextSeek graph keeps reading failed traces | Re-seed with `uv run python examples/demo/seed.py`; demo now retrieves only `demo_policy_lesson` items. |
| `ModuleNotFoundError: contextseek` | Run `uv sync --extra langchain` from the project root. |
| `langgraph: command not found` | Run `uv run langgraph dev` instead. |
