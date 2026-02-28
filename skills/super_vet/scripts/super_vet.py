#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from dataclasses import dataclass
from dataclasses import field


@dataclass
class RunSpec:
    mode: str
    model: str | None
    run_index: int
    extra_args: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        model_tag = f"/{self.model}" if self.model else ""
        return f"{self.mode}{model_tag}#{self.run_index}"


@dataclass
class RunResult:
    spec: RunSpec
    issues: list[dict]
    returncode: int
    duration_seconds: float
    error: str | None = None


def build_vet_command(
    spec: RunSpec,
    goal: str | None,
    base_commit: str | None,
    history_loader: str | None,
    confidence_threshold: float | None,
) -> list[str]:
    cmd = ["vet"]

    if goal:
        cmd.append(goal)

    cmd.extend(["--output-format", "json", "--quiet"])

    if spec.mode == "agentic-claude":
        cmd.extend(["--agentic", "--agent-harness", "claude"])
    elif spec.mode == "agentic-codex":
        cmd.extend(["--agentic", "--agent-harness", "codex"])

    if spec.model:
        cmd.extend(["--model", spec.model])

    if base_commit:
        cmd.extend(["--base-commit", base_commit])

    if history_loader:
        cmd.extend(["--history-loader", history_loader])

    if confidence_threshold is not None:
        cmd.extend(["--confidence-threshold", str(confidence_threshold)])

    cmd.extend(spec.extra_args)
    return cmd


def _error_result(spec: RunSpec, duration: float, error: str, returncode: int = 1) -> RunResult:
    return RunResult(
        spec=spec,
        issues=[],
        returncode=returncode,
        duration_seconds=round(duration, 1),
        error=error,
    )


async def _kill_proc(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    await proc.wait()


async def run_vet(
    spec: RunSpec,
    goal: str | None,
    base_commit: str | None,
    history_loader: str | None,
    confidence_threshold: float | None,
    repo: str | None,
) -> RunResult:
    cmd = build_vet_command(spec, goal, base_commit, history_loader, confidence_threshold)
    if repo:
        cmd.extend(["--repo", repo])

    label = spec.label
    print(f"[super_vet] Starting run: {label}", file=sys.stderr)
    print(f"[super_vet]   cmd: {' '.join(cmd)}", file=sys.stderr)

    start = time.monotonic()
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        duration = time.monotonic() - start

        stdout_str = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()

        if proc.returncode not in (0, 10):
            print(
                f"[super_vet] Run {label} failed (exit {proc.returncode})",
                file=sys.stderr,
            )
            if stderr_str:
                print(f"[super_vet]   stderr: {stderr_str[:500]}", file=sys.stderr)
            return _error_result(
                spec,
                duration,
                stderr_str[:1000] if stderr_str else f"exit code {proc.returncode}",
                returncode=proc.returncode or 1,
            )

        issues = []
        if stdout_str:
            try:
                data = json.loads(stdout_str)
                issues = data.get("issues", [])
            except json.JSONDecodeError as e:
                print(
                    f"[super_vet] Run {label}: failed to parse JSON: {e}",
                    file=sys.stderr,
                )
                return _error_result(spec, duration, f"JSON parse error: {e}")

        print(
            f"[super_vet] Run {label} completed: {len(issues)} issue(s) in {duration:.1f}s",
            file=sys.stderr,
        )
        return RunResult(
            spec=spec,
            issues=issues,
            returncode=proc.returncode or 0,
            duration_seconds=round(duration, 1),
        )

    except FileNotFoundError:
        duration = time.monotonic() - start
        msg = "vet command not found. Is it installed?"
        print(f"[super_vet] Run {label}: {msg}", file=sys.stderr)
        return _error_result(spec, duration, msg)
    except Exception as e:
        duration = time.monotonic() - start
        print(f"[super_vet] Run {label}: unexpected error: {e}", file=sys.stderr)
        return _error_result(spec, duration, str(e))
    finally:
        if proc is not None and proc.returncode is None:
            print(f"[super_vet] Run {label}: cleaning up subprocess", file=sys.stderr)
            await _kill_proc(proc)


def build_run_specs(
    claude_runs: int,
    codex_runs: int,
    standard_runs: int,
    claude_model: str | None,
    codex_model: str | None,
    standard_model: str | None,
) -> list[RunSpec]:
    specs: list[RunSpec] = []

    for i in range(claude_runs):
        specs.append(RunSpec(mode="agentic-claude", model=claude_model, run_index=i))

    for i in range(codex_runs):
        specs.append(RunSpec(mode="agentic-codex", model=codex_model, run_index=i))

    for i in range(standard_runs):
        specs.append(RunSpec(mode="standard", model=standard_model, run_index=i))

    return specs


def _issue_fingerprint(issue: dict) -> str:
    return "|".join(str(issue.get(k, "")) for k in ("issue_code", "file_path", "line_number", "description"))


def aggregate_results(results: list[RunResult]) -> dict:
    seen: dict[str, dict] = {}

    for result in results:
        source_info = {
            "mode": result.spec.mode,
            "model": result.spec.model,
            "run_index": result.spec.run_index,
            "label": result.spec.label,
        }

        for issue in result.issues:
            fp = _issue_fingerprint(issue)
            if fp in seen:
                seen[fp]["found_by"].append(source_info)
                seen[fp]["found_by_count"] += 1
            else:
                seen[fp] = {
                    **issue,
                    "found_by": [source_info],
                    "found_by_count": 1,
                }

    all_issues = sorted(
        seen.values(),
        key=lambda x: (x["found_by_count"], x.get("confidence") or 0),
        reverse=True,
    )

    runs_summary = []
    for r in results:
        runs_summary.append(
            {
                "label": r.spec.label,
                "mode": r.spec.mode,
                "model": r.spec.model,
                "run_index": r.spec.run_index,
                "issues_found": len(r.issues),
                "duration_seconds": r.duration_seconds,
                "returncode": r.returncode,
                "error": r.error,
            }
        )

    total_runs = len(results)
    successful_runs = sum(1 for r in results if r.error is None)
    failed_runs = total_runs - successful_runs

    issues_by_mode: dict[str, int] = {}
    for issue in all_issues:
        for mode in {source["mode"] for source in issue["found_by"]}:
            issues_by_mode[mode] = issues_by_mode.get(mode, 0) + 1

    return {
        "issues": all_issues,
        "runs": runs_summary,
        "summary": {
            "total_unique_issues": len(all_issues),
            "total_runs": total_runs,
            "successful_runs": successful_runs,
            "failed_runs": failed_runs,
            "issues_by_mode": issues_by_mode,
        },
    }


async def async_main(args: argparse.Namespace) -> int:
    if not shutil.which("vet"):
        print("[super_vet] Error: 'vet' CLI not found on PATH.", file=sys.stderr)
        return 2

    specs = build_run_specs(
        claude_runs=args.claude_runs,
        codex_runs=args.codex_runs,
        standard_runs=args.standard_runs,
        claude_model=args.claude_model,
        codex_model=args.codex_model,
        standard_model=args.standard_model,
    )

    if not specs:
        print(
            "[super_vet] Error: no runs configured. Use --runs or --claude-runs etc.",
            file=sys.stderr,
        )
        return 2

    total = len(specs)
    print(f"[super_vet] Launching {total} vet run(s) in parallel...", file=sys.stderr)
    for s in specs:
        print(f"[super_vet]   - {s.label}", file=sys.stderr)

    semaphore = asyncio.Semaphore(args.max_parallel)

    async def limited_run(spec: RunSpec) -> RunResult:
        async with semaphore:
            return await run_vet(
                spec=spec,
                goal=args.goal,
                base_commit=args.base_commit,
                history_loader=args.history_loader,
                confidence_threshold=args.confidence_threshold,
                repo=args.repo,
            )

    start = time.monotonic()
    results = await asyncio.gather(*[limited_run(s) for s in specs])
    wall_time = time.monotonic() - start

    output = aggregate_results(list(results))
    output["wall_time_seconds"] = round(wall_time, 1)

    print(
        f"\n[super_vet] Done. {output['summary']['total_unique_issues']} unique issue(s) "
        f"from {output['summary']['successful_runs']}/{output['summary']['total_runs']} "
        f"successful run(s) in {wall_time:.1f}s wall time.",
        file=sys.stderr,
    )

    json.dump(output, sys.stdout, indent=2)
    print()

    return 10 if output["issues"] else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="super_vet",
    )

    parser.add_argument("goal", nargs="?", default=None)

    run_group = parser.add_argument_group("run configuration")
    run_group.add_argument("--runs", "-n", type=int, default=None)
    run_group.add_argument("--claude-runs", type=int, default=None)
    run_group.add_argument("--codex-runs", type=int, default=None)
    run_group.add_argument("--standard-runs", type=int, default=None)

    model_group = parser.add_argument_group("model configuration")
    model_group.add_argument("--model", "-m", default=None)
    model_group.add_argument("--claude-model", default=None)
    model_group.add_argument("--codex-model", default=None)
    model_group.add_argument("--standard-model", default=None)

    vet_group = parser.add_argument_group("vet options (passed through)")
    vet_group.add_argument("--base-commit", default=None)
    vet_group.add_argument("--history-loader", default=None)
    vet_group.add_argument("--confidence-threshold", type=float, default=0.0)
    vet_group.add_argument("--repo", "-r", default=None)

    parser.add_argument("--max-parallel", type=int, default=6)

    args = parser.parse_args(argv)

    default_runs = args.runs if args.runs is not None else 1
    if args.claude_runs is None:
        args.claude_runs = default_runs
    if args.codex_runs is None:
        args.codex_runs = default_runs
    if args.standard_runs is None:
        args.standard_runs = default_runs

    if args.claude_model is None:
        args.claude_model = args.model
    if args.codex_model is None:
        args.codex_model = args.model
    if args.standard_model is None:
        args.standard_model = args.model

    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    sys.exit(main())
