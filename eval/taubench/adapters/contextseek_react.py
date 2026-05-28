"""ContextSeek React adapter — tau-bench agent with context retrieval and feedback."""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from typing import Any

from eval.taubench import tau2_compat  # noqa: F401  # Python 3.13 compat
from eval.taubench.adapters.base import TaskResult
from eval.taubench.context import TauBenchContextSeekClient
from eval.taubench.prompts import (
    CONTEXTSEEK_CONTEXT_ADDON,
    TAUBENCH_SYSTEM_PROMPT_ADDON,
)


def _is_successful(reward: float) -> bool:
    return (1 - 1e-6) <= reward <= (1 + 1e-6)


def _message_get(message: Any, key: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(key, default)
    return getattr(message, key, default)


def _tool_call_get(tool_call: Any, key: str, default: Any = None) -> Any:
    if isinstance(tool_call, dict):
        return tool_call.get(key, default)
    return getattr(tool_call, key, default)


def _extract_tool_calls(messages: list[Any]) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for msg in messages:
        if _message_get(msg, "role") == "assistant" and _message_get(msg, "tool_calls"):
            for tc in _message_get(msg, "tool_calls", []):
                function = _tool_call_get(tc, "function", {}) or {}
                tool_calls.append({
                    "name": _tool_call_get(
                        tc,
                        "name",
                        _tool_call_get(function, "name", "unknown"),
                    ),
                    "arguments": _tool_call_get(
                        tc,
                        "arguments",
                        _tool_call_get(function, "arguments", ""),
                    ),
                })
    return tool_calls


def _count_agent_turns(messages: list[Any]) -> int:
    return sum(1 for msg in messages if _message_get(msg, "role") == "assistant")


def _get_task_user_id(task: Any) -> str:
    """Extract user_id from a tau2 Task's user scenario instructions."""
    try:
        instructions = task.user_scenario.instructions
        known = getattr(instructions, "known_info", "") or ""
        for line in known.split("\n"):
            line = line.strip()
            if "user id is" in line.lower():
                return line.split("is")[-1].strip().rstrip(".")
        return ""
    except Exception:
        return ""


def _get_task_instruction(task: Any) -> str:
    """Extract the combined instruction text from a tau2 Task."""
    try:
        instructions = task.user_scenario.instructions
        parts = []
        reason = getattr(instructions, "reason_for_call", "") or ""
        if reason:
            parts.append(reason)
        task_inst = getattr(instructions, "task_instructions", "") or ""
        if task_inst:
            parts.append(task_inst)
        return "\n".join(parts)
    except Exception:
        return ""


@dataclass
class ContextSeekReactAdapter:
    """Runs tau-bench tasks with ContextSeek retrieval and feedback.

    Three injection points:
    ① Task start  → retrieve_for_task(user_message) → augment system prompt
    ② Task end    → store_trajectory + feedback (+ compact if enabled)

    Uses tau2's build_orchestrator → inject context → run_simulation pipeline.
    """

    # ── tau-bench config ──
    domain: str = "airline"
    llm_agent: str = "gpt-4o"
    llm_args_agent: dict | None = None
    agent: str = "llm_agent"
    user: str = "user_simulator"
    llm_user: str = "gpt-4o"
    llm_args_user: dict | None = None
    max_steps: int = 100
    max_errors: int = 10
    seed: int = 42

    # ── ContextSeek config ──
    contextseek_client: TauBenchContextSeekClient | None = None
    store_only: bool = False
    auto_compact: bool = False
    initial_context_tokens: int = 1200
    error_context_limit: int = 3

    @property
    def adapter_name(self) -> str:
        if self.store_only:
            return "contextseek_store_only"
        return "contextseek_react"

    def run_task(self, task_id: int, trial: int = 0) -> TaskResult:
        # Fallback to baseline if no ContextSeek client
        sc = self.contextseek_client
        if sc is None:
            from eval.taubench.adapters.baseline import BaselineAdapter

            return BaselineAdapter(
                domain=self.domain,
                llm_agent=self.llm_agent,
                llm_args_agent=self.llm_args_agent,
                agent=self.agent,
                user=self.user,
                llm_user=self.llm_user,
                llm_args_user=self.llm_args_user,
                max_steps=self.max_steps,
                max_errors=self.max_errors,
                seed=self.seed,
            ).run_task(task_id, trial)

        context_mode = "store_only" if self.store_only else "contextseek"
        result = TaskResult(
            task_id=task_id,
            trial=trial,
            context_mode=context_mode,
        )
        retrieved_item_ids: list[str] = []
        started_at = time.time()

        try:
            from tau2.data_model.simulation import TextRunConfig
            from tau2.runner import build_orchestrator, get_tasks, run_simulation

            tasks = get_tasks(self.domain)
            if task_id < 0 or task_id >= len(tasks):
                result.error = (
                    f"task_id {task_id} out of range [0, {len(tasks)})"
                )
                result.duration_ms = int((time.time() - started_at) * 1000)
                return result

            task = tasks[task_id]
            task_user_id = _get_task_user_id(task)
            task_instruction = _get_task_instruction(task)
            sim_seed = self.seed + task_id + trial

            # ── Injection point ①: Retrieve context at task start ──
            context_background = ""
            if sc and not self.store_only:
                payload = sc.retrieve_for_task(
                    task_instruction or task.user_scenario.instructions.reason_for_call,
                    user_id=task_user_id,
                    max_tokens=self.initial_context_tokens,
                )
                context_background = payload.text
                retrieved_item_ids.extend(payload.item_ids)
                result.context_items_retrieved += payload.count

            # ── Build orchestrator ──
            config = TextRunConfig(
                domain=self.domain,
                agent=self.agent,
                user=self.user,
                llm_agent=self.llm_agent,
                llm_args_agent=self.llm_args_agent or {},
                llm_user=self.llm_user,
                llm_args_user=self.llm_args_user or {},
                max_steps=self.max_steps,
                max_errors=self.max_errors,
                seed=sim_seed,
            )
            orch = build_orchestrator(config, task, seed=sim_seed)

            # ── Augment system prompt with ContextSeek background ──
            if context_background:
                context_section = CONTEXTSEEK_CONTEXT_ADDON.format(
                    context_background=context_background,
                )
                # orch.agent.init_messages[0] is the system prompt
                if (
                    hasattr(orch, "agent")
                    and hasattr(orch.agent, "init_messages")
                    and orch.agent.init_messages
                ):
                    orch.agent.init_messages[0]["content"] += (
                        "\n\n" + context_section + TAUBENCH_SYSTEM_PROMPT_ADDON
                    )

            # ── Run simulation ──
            sim_run = run_simulation(orch)

            reward = sim_run.reward_info.reward if sim_run.reward_info else 0.0
            result.reward = reward
            result.success = _is_successful(reward)
            result.messages = sim_run.messages or []
            result.tool_calls = _extract_tool_calls(result.messages)
            result.num_steps = _count_agent_turns(result.messages)

            # ── Injection point ③: Store trajectory + feedback ──
            sc.store_trajectory(
                task_id=task_id,
                user_id=task_user_id,
                instruction=task_instruction or task.user_scenario.instructions.reason_for_call,
                messages=result.messages,
                tool_calls=result.tool_calls,
                success=result.success,
            )
            result.context_items_stored += 1
            if result.success and retrieved_item_ids:
                result.feedback_applied = sc.apply_success_feedback(
                    retrieved_item_ids
                )
            if self.auto_compact:
                result.compact_report = sc.compact()

        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"

        result.duration_ms = int((time.time() - started_at) * 1000)
        return result
