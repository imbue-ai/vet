# Vet : Verify Everything

[![PyPi](https://img.shields.io/pypi/v/verify-everything.svg)](https://pypi.python.org/pypi/verify-everything/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/verify-everything)](https://pypi.python.org/pypi/verify-everything/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
![Build Status](https://github.com/imbue-ai/vet/actions/workflows/test.yml/badge.svg)

Vet is a standalone verification tool for **code changes** and **coding agent behavior**.

It reviews git diffs, and optionally an agent's conversation history, to find issues that tests and linters often miss. Vet is optimized for use by humans, CI, and coding agents.

## Why Vet

- **Verification for agentic workflows**: "the agent said it ran tests" is not the same as "all tests ran successfully".
- **CI-friendly safety net**: catches classes of problems that may not be covered by existing tests.
- **Bring-your-own-model**: can run against hosted providers or local/self-hosted OpenAI-compatible endpoints.

## Installation

```bash
pip install verify-everything
```

Or install from source:

```bash
pip install git+https://github.com/imbue-ai/vet.git
```

## Quickstart

Run Vet in the current repo:

```bash
vet "Implement X without breaking Y"
```

Compare against a base ref/commit:

```bash
vet "Refactor storage layer" --base-commit main
```

## Using Vet with Coding Agents

Vet ships as an [agent skill](https://agentskills.io) that coding agents like [OpenCode](https://opencode.ai) and [Codex](https://github.com/openai/codex) can discover and use automatically. When installed, agents will proactively run vet after code changes and include conversation history for better analysis.

### Install the skill

```bash
for dir in ~/.agents ~/.opencode ~/.claude ~/.codex; do
  mkdir -p "$dir/skills/vet/scripts"
  for file in SKILL.md scripts/export_opencode_session.py scripts/export_codex_session.py scripts/export_claude_code_session.py; do
    curl -fsSL "https://raw.githubusercontent.com/imbue-ai/vet/main/skills/vet/$file" \
      -o "$dir/skills/vet/$file"
  done
done
```
This places the skill in `~/.agents/skills/vet/`, `~/.opencode/skills/vet/`, `~/.claude/skills/vet/`, and `~/.codex/skills/vet/`, so it is discovered by OpenCode, Claude Code, and Codex.

### Security note

The `--history-loader` option executes the specified shell command as the current user to load the conversation history. It is important to review history loader commands and shared config presets before use.

## GitHub PRs (Actions)

Vet can run on pull requests.

Create `.github/workflows/vet.yml`:

```yaml
name: Vet

permissions:
  contents: read
  pull-requests: write

on:
  pull_request:
    types: [opened, edited, synchronize, reopened]

jobs:
  vet:
    if: github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install verify-everything==0.1.4
      - name: Run vet
        if: github.event.pull_request.head.repo.full_name == github.repository
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          VET_GOAL: |
            ${{ github.event.pull_request.title }}

            Additional context (not necessarily part of the goal):
            ${{ github.event.pull_request.body }}
        run: |
          set +e
          vet "$VET_GOAL" --quiet --output-format github \
            --base-commit "${{ github.event.pull_request.base.sha }}" \
            > "$RUNNER_TEMP/review.json"
          status=$?
          if [ "$status" -ne 0 ] && [ "$status" -ne 10 ]; then exit "$status"; fi

          jq --arg sha "${{ github.event.pull_request.head.sha }}" \
            '. + {commit_id: $sha}' "$RUNNER_TEMP/review.json" > "$RUNNER_TEMP/review-final.json"

          gh api "repos/${{ github.repository }}/pulls/${{ github.event.pull_request.number }}/reviews" \
            --method POST --input "$RUNNER_TEMP/review-final.json" > /dev/null || \
            gh pr comment "${{ github.event.pull_request.number }}" \
              --body "$(jq -r '[.body] + [.comments[] | "**\(.path):\(.line)**\n\n\(.body)"] | join("\n\n---\n\n")' "$RUNNER_TEMP/review-final.json")"
          exit 0
```

NOTE: This will not fail in CI if Vet finds an issue.

#### Environment variables

- `ANTHROPIC_API_KEY` is required for the default model configuration.

## How it works

Vet snapshots the repo and diff, optionally adds a goal and agent conversation, runs LLM checks, then filters/deduplicates findings into a final list of issues.

![architecture](https://raw.githubusercontent.com/imbue-ai/vet/main/architecture.svg)

## Output & exit codes

- Exit code `0`: no issues found
- Exit code `1`: unexpected runtime error
- Exit code `2`: invalid usage/configuration error
- Exit code `10`: issues found

Output formats:
- `text`
- `json`
- `github`

## Configuration

### Model configuration

Vet supports custom model definitions using OpenAI-compatible endpoints via JSON config files searched in:

- `$XDG_CONFIG_HOME/vet/models.json` (or `~/.config/vet/models.json`)
- `.vet/models.json` at your repo root

#### Example `models.json`

```json
{
  "providers": {
    "openai": {
      "name": "OpenAI",
      "api_type": "openai_compatible",
      "base_url": "https://api.openai.com/v1",
      "api_key_env": "OPENAI_API_KEY",
      "models": {
        "gpt-4o": {
          "model_id": "gpt-4o-2024-08-06",
          "context_window": 128000,
          "max_output_tokens": 16384
        },
        "gpt-4o-mini": {
          "model_id": "gpt-4o-mini-2024-07-18",
          "context_window": 128000,
          "max_output_tokens": 16384
        },
        "o1": {
          "model_id": "o1-2024-12-17",
          "context_window": 200000,
          "max_output_tokens": 100000
        }
      }
    }
  }
}
```

Then:

```bash
vet "Harden error handling" --model gpt-4o-mini
```

### Configuration profiles (TOML)

Vet supports named profiles so teams can standardize CI usage without long CLI invocations.

Profiles set defaults like model choice, enabled issue codes, output format, and thresholds.

See [the example](https://github.com/imbue-ai/vet/blob/main/.vet/configs.toml) in this project.

### Custom issue guides

You can customize the guide text for the issue codes via `guides.toml`. Guide files are loaded from:

- `$XDG_CONFIG_HOME/vet/guides.toml` (or `~/.config/vet/guides.toml`)
- `.vet/guides.toml` at your repo root

#### Example `guides.toml`

```toml
[logic_error]
suffix = """
- Check for integer overflow in arithmetic operations
"""

[insecure_code]
replace = """
- Check for SQL injection: flag any string concatenation or f-string formatting used to build SQL queries rather than parameterized queries
- Check for XSS: flag user-supplied data rendered into HTML templates without proper escaping or sanitization
- Check for path traversal: flag file operations where user input flows into file paths without validation against directory traversal (e.g. ../)
- Check for insecure cryptography: flag use of deprecated or weak algorithms (e.g. MD5, SHA1 for security purposes, DES, RC4)
- Check for hardcoded credentials: flag passwords, API keys, or tokens embedded directly in source code
"""
```

Section keys must be valid issue codes (`vet --list-issue-codes`). Each section supports three optional fields: `prefix` (prepends to built-in guide), `suffix` (appends to built-in guide), and `replace` (fully replaces the built-in guide). `prefix` and `suffix` can be used together, but `replace` is mutually exclusive with the other two. Guide text should be formatted as a list.

## License

This project is licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0-only)](https://github.com/imbue-ai/vet/blob/main/LICENSE).
