# Vet : Verify Everything

Vet is a standalone verification tool for **code changes** and **coding agent behavior**.

It reviews git diffs, and optionally an agent's conversation history, to find issues that tests and linters often miss. Vet is optimized for use by humans, CI, and coding agents.

## Installation

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

## How it works

Vet snapshots the repo and diff, optionally adds a goal and agent conversation, runs LLM checks, then filters/deduplicates findings into a final list of issues.

![architecture](architecture.svg)

## Why Vet

- **Verification for agentic workflows**: "the agent said it ran tests" is not the same as "all tests ran successfully".
- **CI-friendly safety net**: catches classes of problems that may not be covered by existing tests.
- **Bring-your-own-model**: can run against hosted providers or local/self-hosted OpenAI-compatible endpoints.
- **No telemetry collected by us**: Vet does not collect any user data.

## Output & exit codes

- Exit code `0`: no issues found
- Exit code `1`: issues found
- Exit code `2`: invalid usage/configuration error

Output formats:
- `text`
- `json`

## CI usage

Recommended CI usage is to run Vet with JSON output and display a warning if any issues are found.

Example:

```bash
vet --base-commit main --output-format json > vet-report.json
```

- If Vet exits `0`, no issues were found.
- If Vet exits `1`, issues were found (treat as a failing check).
- If Vet exits `2`, the invocation/config is invalid (treat as a failing check).

## Configuration

### Model configuration

Vet supports custom model definitions using OpenAI-compatible endpoints via JSON config files searched in:

- `$XDG_CONFIG_HOME/imbue/models.json` (or `~/.config/imbue/models.json`)
- `models.json` at your repo root

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

## Advanced usage

### Conversation history

Vet can **optionally** ingest agent conversation history via a **history loader command**.

#### History loader contract

`--history-loader` runs a shell command and reads **stdout** as plaintext.

Security note: this executes a command on your machine. Only run history loader commands you trust.

- Output format: **any text**
- Vet treats this as an opaque transcript (it may include user/assistant messages, tool calls, tool results, logs, etc.)
- If you want Vet to catch “claimed to run tests” style issues reliably, ensure your transcript includes tool invocations/results (or other evidence), not just prose.

Example:

```bash
vet "Fix flaky tests without behavior changes" \
  --history-loader "<command that prints a transcript>"
```

## Privacy / telemetry

Vet does **not** collect telemetry and does not send usage data to external services.

If you configure Vet to use a hosted inference provider, that provider may log requests; selecting a provider is the user’s responsibility.
