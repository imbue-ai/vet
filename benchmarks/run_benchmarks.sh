#!/usr/bin/env bash
# Run all non-LLM CLI benchmarks using hyperfine.
#
# Usage:
#   ./benchmarks/run_benchmarks.sh
#
# Prerequisites:
#   - hyperfine (cargo install hyperfine)
#   - uv (for running vet and the benchmark script)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_DIR"

# Ensure cargo-installed binaries are on PATH
export PATH="$HOME/.cargo/bin:$PATH"

WARMUP=3
RUNS=10

echo "=============================================="
echo " Tier 1: Early-exit CLI commands"
echo "=============================================="
echo ""
echo "These measure Python startup + import chain + the specific early-exit logic."
echo ""

hyperfine \
    --warmup "$WARMUP" \
    --runs "$RUNS" \
    --command-name 'vet --version' \
        'uv run vet --version' \
    --command-name 'vet --list-fields' \
        'uv run vet --list-fields' \
    --command-name 'vet --list-issue-codes' \
        'uv run vet --list-issue-codes' \
    --command-name 'vet --list-models' \
        'uv run vet --list-models' \
    --command-name 'vet --list-configs' \
        'uv run vet --list-configs' \
    --export-json benchmarks/results-tier1.json

echo ""
echo "=============================================="
echo " Tier 2: Pre-LLM context pipeline"
echo "=============================================="
echo ""
echo "This measures git diff, pygit2 repo snapshot, diff application,"
echo "strategy selection, file formatting, token counting, and Jinja2 rendering."
echo ""

hyperfine \
    --warmup 1 \
    --runs 5 \
    --command-name 'context pipeline' \
        'uv run python benchmarks/bench_context_pipeline.py' \
    --export-json benchmarks/results-tier2.json

echo ""
echo "=============================================="
echo " Results saved to:"
echo "   benchmarks/results-tier1.json"
echo "   benchmarks/results-tier2.json"
echo "=============================================="
