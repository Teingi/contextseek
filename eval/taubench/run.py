#!/usr/bin/env python3
"""CLI entry point for tau-bench + ContextSeek evaluations.

Usage:
    uv run python -m eval.taubench.run \
        --config eval/taubench/config/baseline.yaml \
        --stage run,evaluate

    uv run python -m eval.taubench.run \
        --config eval/taubench/config/contextseek_react.yaml \
        --stage run,distill,evaluate
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Python 3.13 compat: must come before tau2 imports
from eval.taubench import tau2_compat  # noqa: F401

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def load_config(path: str) -> dict[str, Any]:
    """Load YAML config with ${VAR} environment substitution."""
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
        pass

    with open(config_path) as f:
        text = f.read()

    def replace_env(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), match.group(0))

    return yaml.safe_load(re.sub(r"\$\{(\w+)\}", replace_env, text))


def resolve_scope(config: dict[str, Any]) -> str:
    """Resolve the ContextSeek scope from config."""
    seek_cfg = config.get("contextseek", {})
    domain = config.get("domain", "airline")
    return seek_cfg.get("scope", f"taubench/{domain}/shared/global")


def build_contextseek_client(config: dict[str, Any]) -> Any:
    """Build a ContextSeek client from config."""
    from contextseek import ContextSeek

    seek_cfg = config.get("contextseek", {})
    storage_cfg = seek_cfg.get("storage", {})
    domain = config.get("domain", "airline")
    scope = resolve_scope(config)

    if str(storage_cfg.get("backend", "")).lower() in {"oceanbase", "ob"}:
        ctx = build_oceanbase_contextseek(seek_cfg)
        return ctx, scope, domain

    ctx = ContextSeek()
    if storage_cfg.get("backend") == "file":
        path = storage_cfg.get("path", f".contextseek/taubench/{domain}")
        from seekvfs import VFS
        from contextseek.storage.file_backend import FileBackend
        from contextseek.storage.storage_adapter import SeekVFSStorageAdapter

        backend = FileBackend(root_dir=path)
        backend.initialize()
        vfs = VFS(
            routes={"contextseek://": {"backend": backend}},
            scheme="contextseek://",
        )
        ctx.adapter = SeekVFSStorageAdapter(vfs)

    return ctx, scope, domain


def build_oceanbase_contextseek(seek_cfg: dict[str, Any]) -> Any:
    """Build an OceanBase-backed ContextSeek instance for tau-bench."""
    import seekvfs
    from contextseek import ContextSeek, ContextSeekSettings
    from contextseek.storage import OceanBaseBackend, SeekVFSStorageAdapter
    from contextseek.config.factory import build_embedder, build_llm, build_summarizer
    from contextseek.config.settings import (
        EmbeddingSettings,
        EvolutionSettings,
        LLMSettings,
        ObservabilitySettings,
        RetrievalSettings,
        SecuritySettings,
        StorageSettings,
        SummarizerSettings,
        to_strategy_config,
    )
    from contextseek.routing.resolver import ScopeResolver

    settings = ContextSeekSettings(
        storage=StorageSettings(**seek_cfg.get("storage", {})),
        embedding=EmbeddingSettings(**seek_cfg.get("embedding", {})),
        llm=LLMSettings(**seek_cfg.get("llm", {})),
        summarizer=SummarizerSettings(**seek_cfg.get("summarizer", {})),
        retrieval=RetrievalSettings(**seek_cfg.get("retrieval", {})),
        evolution=EvolutionSettings(**seek_cfg.get("evolution", {})),
        security=SecuritySettings(**seek_cfg.get("security", {})),
        observability=ObservabilitySettings(**seek_cfg.get("observability", {})),
    )
    embedder = build_embedder(settings.embedding)
    if embedder is None:
        raise ValueError(
            "contextseek.storage.backend=oceanbase requires contextseek.embedding "
            "to configure a real embedding provider."
        )

    shared_llm = build_llm(settings.llm)
    summarizer = build_summarizer(settings.summarizer, llm=shared_llm)

    ob_cfg = seek_cfg.get("storage", {}).get("oceanbase", {})
    vector_dims = int(ob_cfg.get("vector_dims") or settings.embedding.dims or 0)
    if vector_dims <= 0:
        raise ValueError("OceanBase storage requires vector_dims or embedding.dims")

    backend = OceanBaseBackend(
        table_name=ob_cfg.get("table_name", "contextseek_taubench"),
        vector_dims=vector_dims,
        host=ob_cfg.get("host", "127.0.0.1"),
        port=str(ob_cfg.get("port", "2881")),
        user=ob_cfg.get("user", "root@test"),
        password=ob_cfg.get("password", ""),
        db_name=ob_cfg.get("db_name", "contextseek"),
        fulltext_parser=ob_cfg.get("fulltext_parser", "ngram"),
        vidx_metric_type=ob_cfg.get("metric", ob_cfg.get("vidx_metric_type", "cosine")),
        vector_weight=float(ob_cfg.get("vector_weight", 0.7)),
        fts_weight=float(ob_cfg.get("fts_weight", 0.3)),
        rrf_k=int(ob_cfg.get("rrf_k", 60)),
    )
    backend.initialize()

    scheme = settings.storage.uri_scheme
    vfs = seekvfs.VFS({scheme: {"backend": backend}}, scheme=scheme)
    adapter = SeekVFSStorageAdapter(vfs)
    strategy = to_strategy_config(settings)

    audit_log = None
    if settings.observability.audit_enabled:
        from contextseek.observability.audit import AuditLog

        audit_log = AuditLog(
            persist_path=settings.observability.audit_path,
            metrics_path=(
                settings.observability.metrics_path
                if settings.observability.metrics_enabled
                else None
            ),
        )

    evolution_engine = None
    if settings.evolution.enabled:
        from contextseek.evolution.engine import EvolutionEngine

        evolution_engine = EvolutionEngine()

    return ContextSeek(
        adapter=adapter,
        resolver=ScopeResolver(uri_scheme=scheme),
        embedder=embedder,
        summarizer=summarizer,
        evolution_engine=evolution_engine,
        audit_log=audit_log,
        strategy=strategy,
        _strategy_version=strategy.version,
    )


def build_llm_args(agent_cfg: dict[str, Any]) -> dict[str, Any]:
    """Build LiteLLM kwargs shared by tau2 agent and user simulator."""
    llm_args: dict[str, Any] = {"temperature": agent_cfg.get("temperature", 0.0)}
    api_base = (
        agent_cfg.get("api_base")
        or agent_cfg.get("base_url")
        or os.environ.get("OPENAI_API_BASE")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("LLM_BASE_URL")
    )
    if api_base:
        llm_args["api_base"] = api_base
    api_key = agent_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY")
    if api_key:
        llm_args["api_key"] = api_key
    return llm_args


def extract_wiki_text(environment_info: Any) -> str:
    """Extract wiki.md text from tau2 get_environment_info() variants."""
    if isinstance(environment_info, dict):
        for key in ("wiki", "wiki_text", "policy", "policy_text"):
            value = environment_info.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""
    if isinstance(environment_info, (list, tuple)):
        if len(environment_info) >= 2 and isinstance(environment_info[1], str):
            return environment_info[1]
        for value in environment_info:
            if isinstance(value, str) and value.strip():
                return value
    return environment_info if isinstance(environment_info, str) else ""


def cmd_run(args: argparse.Namespace, config: dict[str, Any]) -> int:
    """Run stage: execute tasks and write trajectories."""
    from eval.taubench.adapters.baseline import BaselineAdapter
    from eval.taubench.adapters.contextseek_react import ContextSeekReactAdapter
    from eval.taubench.context import TauBenchContextSeekClient
    from eval.taubench.pipeline.runner import load_task_ids, run_stage

    domain = config.get("domain", "airline")
    agent_cfg = config.get("agent", {})
    seek_cfg = config.get("contextseek", {})
    max_tasks = config.get("max_tasks")
    num_trials = config.get("num_trials", 1)
    task_split = config.get("task_split", "base")
    experiment = config.get("experiment_name", "taubench_eval")
    output_dir = Path(config.get("output_dir", f"output/taubench/{experiment}"))
    resume = config.get("resume", True)
    adapter_name = config.get("adapter", "baseline")

    llm_agent = agent_cfg.get("model", "gpt-4o")
    llm_args = build_llm_args(agent_cfg)
    max_steps = agent_cfg.get("max_steps", 100)
    llm_user = agent_cfg.get("user_model", "gpt-4o")

    task_ids = load_task_ids(domain, max_tasks=max_tasks, task_split=task_split)

    # Build adapter
    if adapter_name == "baseline":
        adapter = BaselineAdapter(
            domain=domain,
            llm_agent=llm_agent,
            llm_args_agent=llm_args,
            llm_user=llm_user,
            max_steps=max_steps,
            seed=config.get("seed", 42),
        )
    else:
        ctx, scope, _domain = build_contextseek_client(config)
        sc = TauBenchContextSeekClient(ctx=ctx, scope=scope, domain=domain)
        adapter = ContextSeekReactAdapter(
            domain=domain,
            llm_agent=llm_agent,
            llm_args_agent=llm_args,
            llm_user=llm_user,
            max_steps=max_steps,
            contextseek_client=sc,
            store_only=seek_cfg.get("store_only", False),
            auto_compact=seek_cfg.get("auto_compact", False),
            initial_context_tokens=seek_cfg.get("initial_context_tokens", 1200),
            error_context_limit=seek_cfg.get("error_context_limit", 3),
            seed=config.get("seed", 42),
        )

    traj_path = output_dir / "trajectories" / f"{adapter_name}.jsonl"
    print(f"Running {len(task_ids)} tasks with adapter '{adapter_name}'...")
    results = run_stage(
        adapter,
        task_ids,
        traj_path,
        resume=resume,
        num_trials=num_trials,
    )

    # Snapshot config
    (output_dir / "config_snapshot.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2)
    )

    print(f"\nDone. {len(results)} results → {traj_path}")
    return 0


def cmd_distill(args: argparse.Namespace, config: dict[str, Any]) -> int:
    """Distill stage: extract knowledge from trajectories."""
    from eval.taubench.context import TauBenchContextSeekClient
    from eval.taubench.pipeline.distiller import distill_stage

    domain = config.get("domain", "airline")
    experiment = config.get("experiment_name", "taubench_eval")
    output_dir = Path(config.get("output_dir", f"output/taubench/{experiment}"))
    distill_cfg = config.get("distill", {})
    compact_after = distill_cfg.get("compact_after", True)
    max_records = distill_cfg.get("max_records")

    ctx, scope, _domain = build_contextseek_client(config)
    sc = TauBenchContextSeekClient(ctx=ctx, scope=scope, domain=domain)

    # Import policy document if configured
    if distill_cfg.get("import_policy_doc", False):
        from tau2.run import get_environment_info
        wiki = extract_wiki_text(get_environment_info(domain))
        if wiki:
            count = sc.import_policy_document(wiki)
            print(f"Imported {count} policy document items from wiki.md")

    trajectories_dir = output_dir / "trajectories"
    distill_dir = output_dir / "distill"
    status = distill_stage(
        trajectories_dir,
        distill_dir,
        sc,
        compact_after=compact_after,
        max_records=max_records,
    )
    for name, msg in status.items():
        print(f"  {name}: {msg}")
    return 0


def cmd_evaluate(args: argparse.Namespace, config: dict[str, Any]) -> int:
    """Evaluate stage: generate reports and metrics."""
    from eval.taubench.pipeline.evaluator import evaluate_stage

    domain = config.get("domain", "airline")
    experiment = config.get("experiment_name", "taubench_eval")
    output_dir = Path(config.get("output_dir", f"output/taubench/{experiment}"))
    adapter_name = config.get("adapter", "baseline")
    num_trials = config.get("num_trials", 1)

    trajectories_dir = output_dir / "trajectories"
    evaluate_dir = output_dir / "evaluate"
    summary = evaluate_stage(
        trajectories_dir,
        evaluate_dir,
        experiment_name=experiment,
        domain=domain,
        context_mode=adapter_name,
        num_trials=num_trials,
    )
    print(f"Report → {evaluate_dir / 'report.md'}")
    print(f"Summary → {evaluate_dir / 'summary.json'}")
    print(f"Success rate: {summary.get('success_rate', 0):.2%}")
    return 0


STAGE_HANDLERS = {
    "run": cmd_run,
    "distill": cmd_distill,
    "evaluate": cmd_evaluate,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="tau-bench + ContextSeek Evaluation Runner"
    )
    parser.add_argument(
        "--config", "-c", required=True, help="Path to YAML config file"
    )
    parser.add_argument(
        "--stage",
        default="run,evaluate",
        help="Comma-separated stages: run, distill, evaluate",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore existing trajectory files and re-run all tasks",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.no_resume:
        config["resume"] = False

    stages = [s.strip() for s in args.stage.split(",")]

    for stage in stages:
        handler = STAGE_HANDLERS.get(stage)
        if handler is None:
            print(f"Unknown stage: {stage}")
            return 2
        print(f"\n── Stage: {stage} ──")
        rc = handler(args, config)
        if rc != 0:
            return rc

    return 0


if __name__ == "__main__":
    sys.exit(main())
