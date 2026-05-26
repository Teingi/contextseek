"""Pipeline stage: run AppWorld tasks and write trajectory JSONL."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..adapters.base import AgentAdapter, RunResult
from ..environment import normalize_optional_path


def load_config(path: str) -> dict[str, Any]:
    """Load YAML config with ``${VAR}`` environment substitution."""
    import yaml

    config_path = Path(path).expanduser()
    if config_path.exists():
        config_path = config_path.resolve()

    # Best-effort: preload .env so ${VAR} placeholders can resolve without
    # requiring users to manually export every variable.
    try:
        from dotenv import load_dotenv  # type: ignore

        candidates: list[Path] = []
        cwd_env = Path.cwd() / ".env"
        if cwd_env.exists():
            candidates.append(cwd_env)
        if config_path.is_absolute() and len(config_path.parents) >= 4:
            root_env = config_path.parents[3] / ".env"
            if root_env.exists() and root_env not in candidates:
                candidates.append(root_env)
        for env_file in candidates:
            load_dotenv(env_file, override=False)
    except Exception:
        # Keep config loading resilient when python-dotenv is unavailable.
        pass

    with open(config_path) as f:
        text = f.read()

    def replace_env(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), match.group(0))

    return yaml.safe_load(re.sub(r"\$\{(\w+)\}", replace_env, text))


def load_task_ids(
    dataset: str,
    max_tasks: int | None = None,
    *,
    appworld_python: str | None = None,
) -> list[str]:
    """Load task IDs from an AppWorld task set."""
    python = normalize_optional_path(appworld_python)
    if python:
        code = (
            "import json\n"
            "from appworld.task import load_task_ids\n"
            f"print(json.dumps(load_task_ids({dataset!r})))\n"
        )
        try:
            proc = subprocess.run(
                [python, "-c", code],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(
                f"failed to load AppWorld task ids with python={python!r}: {detail}"
            ) from exc
        task_ids = json.loads(proc.stdout)
    else:
        try:
            from appworld.task import load_task_ids as appworld_load_task_ids

            task_ids = appworld_load_task_ids(dataset)
        except ImportError:
            seeds_path = Path(__file__).resolve().parent.parent / "seeds.json"
            if not seeds_path.exists():
                raise RuntimeError(
                    "AppWorld is not installed in this Python environment. "
                    "Set appworld.python or APPWORLD_PYTHON to the Python executable "
                    "of your separate AppWorld virtualenv."
                )
            task_ids = json.loads(seeds_path.read_text())

    if max_tasks and max_tasks > 0:
        return task_ids[:max_tasks]
    return task_ids


def _result_to_dict(result: RunResult) -> dict[str, Any]:
    return asdict(result)


def run_stage(
    adapter: AgentAdapter,
    task_ids: list[str],
    output_path: Path,
    *,
    resume: bool = True,
) -> list[RunResult]:
    """Run tasks through an adapter, appending JSONL results incrementally."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    done_ids: set[str] = set()
    if resume and output_path.exists():
        with open(output_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    done_ids.add(json.loads(line)["task_id"])

    results: list[RunResult] = []
    total = len(task_ids)
    with open(output_path, "a") as f:
        for idx, task_id in enumerate(task_ids, 1):
            if task_id in done_ids:
                print(f"  [{idx}/{total}] {task_id} -- skipped")
                continue

            print(f"  [{idx}/{total}] {task_id} ...", end=" ", flush=True)
            started_at = time.time()
            result = adapter.run_task(task_id)
            elapsed = time.time() - started_at
            status = "PASS" if result.success else "FAIL"
            line = f"{status} ({result.num_steps} steps, {elapsed:.1f}s)"
            if result.error:
                line += f" — {result.error}"
            print(line)

            f.write(json.dumps(_result_to_dict(result), ensure_ascii=False) + "\n")
            f.flush()
            results.append(result)
    return results
