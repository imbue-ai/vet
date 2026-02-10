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

## GitHub PRs (Actions)

Vet can run on pull requests.

Create `.github/workflows/vet.yml` (see [this repo's workflow](.github/workflows/vet.yml) for a working example):

```yaml
name: Vet

permissions:
  contents: read

on:
  pull_request:
    types: [opened, synchronize, reopened]

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
      - run: pip install git+https://github.com/imbue-ai/vet.git
      - name: Run vet
        if: github.event.pull_request.head.repo.full_name == github.repository
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          VET_GOAL: |
            ${{ github.event.pull_request.title }}

            Additional context (not necessarily part of the goal):
            ${{ github.event.pull_request.body }}
        run: |
          set +e
          vet "$VET_GOAL" --quiet --output-format github --base-commit "${{ github.event.pull_request.base.sha }}"
          status=$?
          if [ "$status" -eq 1 ]; then exit 0; fi
          exit "$status"
```

NOTE: This will not fail in CI if Vet finds an issue. The `github` output format emits `::warning`/`::error` workflow commands that GitHub renders as inline annotations on the PR diff.

#### Environment variables

- **CI-friendly safety net**: catches classes of problems that may not be covered by existing tests.
- **Bring-your-own-model**: can run against hosted providers or local/self-hosted OpenAI-compatible endpoints.

## Output & exit codes

- Exit code `0`: no issues found
- Exit code `1`: issues found
- Exit code `2`: invalid usage/configuration error

Output formats:
- `text` — human-readable (default)
- `json` — machine-readable structured output
- `github` — GitHub Actions workflow commands (`::warning`/`::error` annotations)

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

See [the example](https://github.com/imbue-ai/vet/blob/main/vet.toml) in this project.

## License

This project is licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0-only)](LICENSE).
