# imbue_verify

Imbue verify is a library and CLI tool for verifying code quality and correctness.

## Installation

From the repository root:

```bash
uv sync --project imbue-verify
```

## Usage

```bash
uv run imbue-verify --help
uv run imbue-verify "description of what the code change accomplishes"
uv run imbue-verify --list-models
uv run imbue-verify "description of what the code change accomplishes" --model claude-opus-4-5-20251101
uv run imbue-verify --model claude-opus-4-5-20251101 # no goal specified
uv run imbue-verify --model claude-opus-4-5-20251101 --base-commit main # default is HEAD
```

## Custom Models

You can configure custom models (e.g., Ollama, OpenRouter, or other OpenAI-compatible APIs) by creating a `models.json` file in one of these locations:

- `~/.config/imbue/models.json` - Global configuration
- `<git-repo-root>/models.json` - Project-specific configuration (overrides global)

Example configuration:

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

## Exit Status

The following are the **expected** exit status codes for imbue-verify:

- `0` - Success, no issues found
- `1` - Issues were found in the code
- `2` - Invalid arguments or configuration

## Concepts

### Issue identifiers

Issue identifiers are pieces of logic capable of finding issues in code. We foresee two basic kinds of those:

1. File-checking ones.
    - To check for "objective" issues in existing files.
2. Commit-checking ones.
    - To check for the quality of a single commit.
    - "Assuming that we can treat the commit message as a requirement, how well does the commit implement it?"

By default, `imbue_verify` runs all the registered issue identifiers and outputs all the found issues on the standard output in JSON format.

#### Adding new Issue Identifiers

If you want to add a new issue identifier, you need to:

1. Implement the `IssueIdentifier` protocol from `imbue_tools.repo_utils.data_types`.
2. Register the new issue identifier by adding it to `IDENTIFIERS` in `imbue_verify.issue_identifiers.registry`.

Based on your needs, instead of the above, you can also extend one of the existing batched zero-shot issue identifiers:
    - `imbue_verify/issue_identifiers/batched_commit_check.py`
      (for commit checking)
In that case you would simply expand the rubric in the prompt. That is actually the preferred way to catch issues at the moment due to efficiency.
Refer to the source code for more details.

## Development Notes

### Logging Configuration

When creating a new entrypoint into imbue_verify, you must call `ensure_core_log_levels_configured()` to register the custom log levels used throughout the codebase.

```python
from imbue_core.log_utils import ensure_core_log_levels_configured

ensure_core_log_levels_configured()
```
