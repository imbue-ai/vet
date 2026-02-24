<p align="center">
  <a href="https://github.com/imbue-ai/vet">
    <img alt="Vet: Verify Everything" src="https://raw.githubusercontent.com/imbue-ai/vet/main/images/vet.svg" width="30%">
  </a>
</p>

<p align="center">
  <a href="https://pypi.python.org/pypi/verify-everything/"><img src="https://img.shields.io/pypi/v/verify-everything.svg" alt="PyPi"></a>
  <a href="https://www.gnu.org/licenses/agpl-3.0"><img src="https://img.shields.io/badge/License-AGPL_v3-blue.svg" alt="License: AGPL v3"></a>
  <img src="https://github.com/imbue-ai/vet/actions/workflows/test-unit.yml/badge.svg" alt="Build Status">
  <a href="https://discord.gg/sBAVvHPUTE"><img src="https://img.shields.io/badge/Discord-Join%20us-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">Vet is a standalone verification tool for <b>code changes</b> and <b>coding agent behavior</b>.</p>

## Why Vet

- **Reviews intent and code**: checks agent conversations for goal adherence and code changes for correctness.
- **Runs anywhere**: from the terminal, as a coding agent skill, or in CI.
- **Bring-your-own-model**: works with any provider using your own API keys, no subscription required.
- **No data collection**: requests go directly to inference providers, never through our servers.

## Using Vet with Coding Agents

Vet can run as part of a skill coding agents discover and use automatically. When installed, agents will proactively run vet after code changes and include conversation history for better analysis.

### Install the skill

```bash
curl -fsSL https://raw.githubusercontent.com/imbue-ai/vet/main/install-skill.sh | bash
```

You will be prompted to choose between:

- **Project level**: installs into `.agents/skills/vet/`, `.opencode/skills/vet/`, `.claude/skills/vet/`, and `.codex/skills/vet/` at the repo root (run from your repo directory)
- **User level**: installs into `~/.agents/`, `~/.opencode/`, `~/.claude/`, and `~/.codex/` skill directories, discovered globally by all agents

<details>
<summary>Manual installation</summary>

#### Project Level

From the root of your git repo:

```bash
for dir in .agents .opencode .claude .codex; do
  mkdir -p "$dir/skills/vet/scripts"
  for file in SKILL.md scripts/export_opencode_session.py scripts/export_codex_session.py scripts/export_claude_code_session.py; do
    curl -fsSL "https://raw.githubusercontent.com/imbue-ai/vet/main/skills/vet/$file" \
      -o "$dir/skills/vet/$file"
  done
done
```

#### User Level

```bash
for dir in ~/.agents ~/.opencode ~/.claude ~/.codex; do
  mkdir -p "$dir/skills/vet/scripts"
  for file in SKILL.md scripts/export_opencode_session.py scripts/export_codex_session.py scripts/export_claude_code_session.py; do
    curl -fsSL "https://raw.githubusercontent.com/imbue-ai/vet/main/skills/vet/$file" \
      -o "$dir/skills/vet/$file"
  done
done
```

</details>

### Security note

The `--history-loader` option executes the specified shell command as the current user to load the conversation history. It is important to review history loader commands and shared config presets before use.

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

## GitHub PRs (Actions)

Vet can run on pull requests using the reusable GitHub Action.

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
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
      - uses: imbue-ai/vet@main
        with:
          agentic: false
```

The action handles Python setup, vet installation, merge base computation, and posting the review to the PR. `ANTHROPIC_API_KEY` must be set as a repository secret when using Anthropic models (the default). See [`action.yml`](https://github.com/imbue-ai/vet/blob/main/action.yml) for all available inputs.

## How it works

Vet snapshots the repo and diff, optionally adds a goal and agent conversation, runs LLM checks, then filters/deduplicates findings into a final list of issues.

![architecture](https://raw.githubusercontent.com/imbue-ai/vet/main/images/architecture.svg)

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
    "openrouter": {
      "name": "OpenRouter",
      "api_type": "openai_compatible",
      "base_url": "https://openrouter.ai/api/v1",
      "api_key_env": "OPENROUTER_API_KEY",
      "models": {
        "gpt-5.2": {
          "model_id": "openai/gpt-5.2",
          "context_window": 400000,
          "max_output_tokens": 128000,
          "supports_temperature": true
        },
        "kimi-k2": {
          "model_id": "moonshotai/kimi-k2",
          "context_window": 131072,
          "max_output_tokens": 32768,
          "supports_temperature": true
        }
      }
    }
  }
}
```

Then:

```bash
vet "Harden error handling" --model gpt-5.2
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

## Community

Join the [Imbue Discord](https://discord.gg/sBAVvHPUTE) for discussion, questions, and support. For bug reports and feature requests, please use [GitHub Issues](https://github.com/imbue-ai/vet/issues).

## License

This project is licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0-only)](https://github.com/imbue-ai/vet/blob/main/LICENSE).
