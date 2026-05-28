"""Pipeline stage: evaluate tau-bench trajectories and generate reports."""

from __future__ import annotations

import json
from math import comb
from pathlib import Path
from typing import Any


def evaluate_stage(
    results_dir: Path,
    output_dir: Path,
    *,
    experiment_name: str = "taubench_eval",
    domain: str = "airline",
    context_mode: str = "baseline",
    num_trials: int = 1,
) -> dict[str, Any]:
    """Generate evaluation report and summary from trajectory JSONL.

    Args:
        results_dir: Directory containing *.jsonl trajectory files.
        output_dir: Directory to write report.md and summary.json.
        experiment_name: Name for the report header.
        domain: Domain name.
        context_mode: Label for the experiment group.
        num_trials: Number of trials per task (for Pass^k calculation).

    Returns:
        Summary dict with key metrics.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load all trajectories
    all_tasks: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("*.jsonl")):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    all_tasks.append(json.loads(line))

    if not all_tasks:
        summary = {
            "experiment": experiment_name,
            "domain": domain,
            "context_mode": context_mode,
            "num_tasks": 0,
            "num_trials": num_trials,
            "error": "no trajectories found",
        }
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2)
        )
        return summary

    # ── Compute metrics ──
    num_tasks = len({t["task_id"] for t in all_tasks})
    num_success = sum(1 for t in all_tasks if t.get("success"))
    success_rate = num_success / len(all_tasks) if all_tasks else 0.0
    avg_reward = sum(t.get("reward", 0.0) for t in all_tasks) / len(all_tasks)

    steps = [t.get("num_steps", 0) for t in all_tasks if t.get("num_steps", 0) > 0]
    avg_steps = sum(steps) / len(steps) if steps else 0.0

    durations = [t.get("duration_ms", 0) for t in all_tasks]
    avg_duration_ms = sum(durations) / len(durations) if durations else 0.0

    # Context metrics
    total_retrieved = sum(t.get("context_items_retrieved", 0) for t in all_tasks)
    total_stored = sum(t.get("context_items_stored", 0) for t in all_tasks)
    total_feedback = sum(t.get("feedback_applied", 0) for t in all_tasks)

    # Error count
    errors = [t for t in all_tasks if t.get("error")]
    error_count = len(errors)

    # ── Pass^k calculation (tau-bench style) ──
    pass_hat_ks: dict[int, float] = {}
    if num_trials > 1:
        c_per_task: dict[int, int] = {}
        for t in all_tasks:
            tid = t["task_id"]
            c_per_task.setdefault(tid, 0)
            if _is_successful_reward(t.get("reward", 0.0)):
                c_per_task[tid] += 1

        for k in range(1, num_trials + 1):
            sum_pass = 0.0
            for c in c_per_task.values():
                if num_trials >= k:
                    sum_pass += comb(c, k) / comb(num_trials, k)
            pass_hat_ks[k] = sum_pass / len(c_per_task) if c_per_task else 0.0

    # ── Per-task breakdown ──
    per_task: dict[int, dict[str, Any]] = {}
    for t in all_tasks:
        tid = t["task_id"]
        if tid not in per_task:
            per_task[tid] = {
                "task_id": tid,
                "trials": [],
                "any_success": False,
            }
        per_task[tid]["trials"].append({
            "trial": t.get("trial", 0),
            "success": t.get("success", False),
            "reward": t.get("reward", 0.0),
            "num_steps": t.get("num_steps", 0),
            "duration_ms": t.get("duration_ms", 0),
            "error": t.get("error"),
        })
        if t.get("success"):
            per_task[tid]["any_success"] = True

    tasks_with_any_success = sum(1 for v in per_task.values() if v["any_success"])

    # ── Write summary ──
    summary: dict[str, Any] = {
        "experiment": experiment_name,
        "domain": domain,
        "context_mode": context_mode,
        "num_tasks": num_tasks,
        "num_trials": num_trials,
        "total_runs": len(all_tasks),
        "num_success": num_success,
        "success_rate": round(success_rate, 4),
        "avg_reward": round(avg_reward, 4),
        "avg_steps": round(avg_steps, 2),
        "avg_duration_ms": round(avg_duration_ms, 0),
        "tasks_with_any_success": tasks_with_any_success,
        "pass_hat_ks": {str(k): round(v, 4) for k, v in pass_hat_ks.items()},
        "context": {
            "total_retrieved": total_retrieved,
            "total_stored": total_stored,
            "total_feedback": total_feedback,
        },
        "error_count": error_count,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )

    # ── Write report.md ──
    report = _generate_report(
        experiment_name=experiment_name,
        domain=domain,
        context_mode=context_mode,
        summary=summary,
        per_task=per_task,
        pass_hat_ks=pass_hat_ks,
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return summary


def _is_successful_reward(reward: float) -> bool:
    return (1 - 1e-6) <= reward <= (1 + 1e-6)


def _generate_report(
    experiment_name: str,
    domain: str,
    context_mode: str,
    summary: dict[str, Any],
    per_task: dict[int, dict[str, Any]],
    pass_hat_ks: dict[int, float],
) -> str:
    lines = [
        "# tau-bench Evaluation Report",
        "",
        f"**Experiment:** {experiment_name}",
        f"**Domain:** {domain}",
        f"**Context Mode:** {context_mode}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total tasks | {summary['num_tasks']} |",
        f"| Total runs | {summary['total_runs']} |",
        f"| Successful runs | {summary['num_success']} |",
        f"| Success rate | {summary['success_rate']:.2%} |",
        f"| Avg reward | {summary['avg_reward']:.4f} |",
        f"| Avg steps (successful) | {summary['avg_steps']:.1f} |",
        f"| Avg duration (ms) | {summary['avg_duration_ms']:.0f} |",
        f"| Tasks with ≥1 success | {summary['tasks_with_any_success']} |",
        f"| Errors | {summary['error_count']} |",
        "",
    ]

    if pass_hat_ks:
        lines.append("## Pass^k")
        lines.append("")
        lines.append("| k | Pass^k |")
        lines.append("|---|--------|")
        for k, v in sorted(pass_hat_ks.items()):
            lines.append(f"| {k} | {v:.2%} |")
        lines.append("")

    ctx = summary.get("context", {})
    if ctx.get("total_retrieved", 0) > 0:
        lines.extend([
            "## ContextSeek Metrics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Context items retrieved | {ctx['total_retrieved']} |",
            f"| Context items stored | {ctx['total_stored']} |",
            f"| Feedback applied | {ctx['total_feedback']} |",
            "",
        ])

    lines.extend([
        "## Per-Task Results",
        "",
        "| Task ID | Any Success | Trials | Avg Steps | Avg Duration (ms) |",
        "|---------|------------|--------|-----------|-------------------|",
    ])
    for tid in sorted(per_task.keys()):
        info = per_task[tid]
        t_count = len(info["trials"])
        t_steps = [t["num_steps"] for t in info["trials"] if t["num_steps"] > 0]
        t_dur = [t["duration_ms"] for t in info["trials"]]
        avg_s = sum(t_steps) / len(t_steps) if t_steps else 0
        avg_d = sum(t_dur) / len(t_dur) if t_dur else 0
        status = "✅" if info["any_success"] else "❌"
        lines.append(
            f"| {tid} | {status} | {t_count} | {avg_s:.1f} | {avg_d:.0f} |"
        )

    lines.append("")
    return "\n".join(lines)
