"""Benchmark the pre-LLM context-building pipeline.

This script exercises the full local computation pipeline that runs before any
LLM call: git diff, pygit2 repo snapshot, diff application, strategy selection,
file formatting, token counting, and Jinja2 template rendering.

Usage:
    uv run python benchmarks/bench_context_pipeline.py

Designed to be called via hyperfine:
    hyperfine --warmup 1 --runs 5 'uv run python benchmarks/bench_context_pipeline.py'
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Ensure the repo root is on the path so vet is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _suppress_logging() -> None:
    """Suppress loguru output so benchmark output is clean."""
    from loguru import logger

    logger.remove()


def bench_git_diff(repo_path: Path, relative_to: str) -> tuple[str, str, str]:
    """Benchmark: resolve base commit + compute diffs (subprocess git calls)."""
    from vet.repo_utils import get_code_to_check

    t0 = time.perf_counter()
    base_commit, diff, diff_no_binary = get_code_to_check(relative_to, repo_path)
    elapsed = time.perf_counter() - t0
    print(f"get_code_to_check          : {elapsed:.4f}s  (diff={len(diff)} chars)")
    return base_commit, diff, diff_no_binary


def bench_token_count(text: str, label: str) -> int:
    """Benchmark: tiktoken token counting."""
    from vet.imbue_core.agents.llm_apis.anthropic_api import count_anthropic_tokens

    t0 = time.perf_counter()
    n = count_anthropic_tokens(text)
    elapsed = time.perf_counter() - t0
    print(f"count_tokens ({label:>14s}): {elapsed:.4f}s  ({n} tokens)")
    return n


def bench_lazy_context(
    base_commit: str,
    diff: str,
    diff_no_binary_tokens: int,
    repo_path: Path,
) -> None:
    """Benchmark: full LazyProjectContext build + materialization.

    This triggers the expensive lazy properties:
      - pygit2 tree walk (original_content_by_path)
      - diff application (content_by_path)
      - modified file detection (modified_file_paths)
      - strategy cascade + formatting + token counting (subrepo_context)
      - Jinja2 render (cached_prompt_prefix)
    """
    from vet.imbue_tools.repo_utils.project_context import LazyProjectContext
    from vet.repo_utils import VET_MAX_PROMPT_TOKENS

    max_output_tokens = 20000
    tokens_to_reserve = VET_MAX_PROMPT_TOKENS + diff_no_binary_tokens + max_output_tokens

    # Build (cheap -- just stores params)
    ctx = LazyProjectContext.build(
        base_commit=base_commit,
        diff=diff,
        language_model_name="claude-sonnet-4-20250514",
        repo_path=repo_path,
        tokens_to_reserve=tokens_to_reserve,
        context_window=200000,
    )

    # Force pygit2 repo snapshot at base commit
    t0 = time.perf_counter()
    _ = ctx.original_content_by_path
    elapsed = time.perf_counter() - t0
    n_files = len(ctx.original_content_by_path.text_files)
    print(f"original_content_by_path   : {elapsed:.4f}s  ({n_files} text files)")

    # Force diff application
    t0 = time.perf_counter()
    _ = ctx.content_by_path
    elapsed = time.perf_counter() - t0
    n_files = len(ctx.content_by_path.text_files)
    print(f"content_by_path            : {elapsed:.4f}s  ({n_files} text files)")

    # Force modified file detection
    t0 = time.perf_counter()
    _ = ctx.modified_file_paths
    elapsed = time.perf_counter() - t0
    print(f"modified_file_paths        : {elapsed:.4f}s  ({len(ctx.modified_file_paths)} modified)")

    # Force strategy cascade + formatting + tokenization
    t0 = time.perf_counter()
    _ = ctx.subrepo_context
    elapsed = time.perf_counter() - t0
    print(
        f"subrepo_context            : {elapsed:.4f}s  (strategy={ctx.subrepo_context.subrepo_context_strategy_label})"
    )

    # Force Jinja2 render
    t0 = time.perf_counter()
    _ = ctx.cached_prompt_prefix
    elapsed = time.perf_counter() - t0
    print(f"cached_prompt_prefix       : {elapsed:.4f}s  ({len(ctx.cached_prompt_prefix)} chars)")


def main() -> None:
    repo_path = REPO_ROOT
    relative_to = "HEAD"

    _suppress_logging()

    print(f"=== Benchmarking pre-LLM pipeline on {repo_path} (relative_to={relative_to}) ===")
    print()

    t_total = time.perf_counter()

    # 1. Git diff
    base_commit, diff, diff_no_binary = bench_git_diff(repo_path, relative_to)

    # 2. Token counting on the diff
    if diff_no_binary:
        diff_tokens = bench_token_count(diff_no_binary, "diff")
    else:
        diff_tokens = 0
        print("count_tokens (          diff): skipped (empty diff)")

    # 3. Full context pipeline
    if diff:
        bench_lazy_context(base_commit, diff, diff_tokens, repo_path)
    else:
        print("\n(empty diff -- skipping context pipeline)")

    elapsed_total = time.perf_counter() - t_total
    print()
    print(f"{'TOTAL':>31s}: {elapsed_total:.4f}s")


if __name__ == "__main__":
    main()
