# Development

For general usage, installation, and configuration, see the [README](README.md).

## Dev Setup

### On your host machine

Ensure you have [uv](https://docs.astral.sh/uv/getting-started/installation/) installed, and that you have the correct env variables set to run Vet (Vet defaults to Anthropic models so this means you should have your ANTHROPIC_API_KEY set).

Then run:

```bash
uv run vet
```

### Containerized

You can use the `Containerfile` in `dev/` at the repo root to create a container that suffices to run Vet for development purposes.

#### Setup

Create a `.env` file at the repo root with your API keys. The recommended keys are `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `CODEX_API_KEY`.

To include Claude Code in the image (proprietary, requires `ANTHROPIC_API_KEY`), add:

```
I_CHOOSE_CONVENIENCE_OVER_FREEDOM=true
```

Without this, only Codex is available as an agent harness.

#### Running Vet in a Container

```bash
./dev/vet.sh --list-models
./dev/vet.sh "check for bugs" --base-commit main
./dev/vet.sh --base-commit main --agentic --agent-harness codex
./dev/vet.sh --base-commit main --agentic --agent-harness claude  # requires I_CHOOSE_CONVENIENCE_OVER_FREEDOM=true
```

The image is built automatically on each run; layer caching makes this near-instant when nothing has changed. To build without running vet, use `./dev/build.sh`.

#### Interactive Development

```bash
./dev/run.sh
```

Starts an interactive shell in the container. The repo is bind-mounted at `/app`. If `I_CHOOSE_CONVENIENCE_OVER_FREEDOM=true` is set, Claude Code is available — run `claude` inside to authenticate. The first `uv run vet` is slower while `uv` sets up the venv; subsequent runs are fast.

## Formatting Hooks

Install pre-commit hooks once per clone:

```bash
uvx pre-commit install
```

Run formatting hooks manually across the repo:

```bash
uvx pre-commit run --all-files
```

After installation, `isort` and `black` run automatically on staged Python files before each commit.

## Running Tests

### Unit tests

All unit tests are run with:

```bash
uv run pytest
```

This command should be preserved the sole way to run unit tests.

## Concepts

### Issue identifiers

Issue identifiers are pieces of logic capable of finding issues in code. We foresee two basic kinds of those:

1. File-checking ones.
    - To check for "objective" issues in existing files.
2. Commit-checking ones.
    - To check for the quality of a single commit.
    - "Assuming that we can treat the commit message as a requirement, how well does the commit implement it?"

By default, `vet` runs all the registered issue identifiers and outputs all the found issues on the standard output in JSON format.

#### Adding new Issue Identifiers

If you want to add a new issue identifier, you need to:

1. Implement the `IssueIdentifier` protocol from `vet.imbue_tools.repo_utils.data_types`.
2. Register the new issue identifier by adding it to `IDENTIFIERS` in `vet.issue_identifiers.registry`.

Based on your needs, instead of the above, you can also extend one of the existing batched zero-shot issue identifiers:
    - `vet/issue_identifiers/batched_commit_check.py`
      (for commit checking)
In that case you would simply expand the rubric in the prompt. That is actually the preferred way to catch issues at the moment due to efficiency.
Refer to the source code for more details.

## CI / CD

### GitHub Actions naming conventions

Workflows follow a consistent naming scheme across three layers:

- **File name**: `<verb>-<target>.yml` (e.g. `test-unit.yml`)
- **Display name** (`name:`): `<Verb> / <Target>` (e.g. `Test / Unit`)
- **Job name**: short target identifier (e.g. `unit`)

The `/` in display names creates visual grouping in the GitHub Actions UI. Group related workflows under a shared prefix (e.g. `Test /`, `Publish /`). Standalone workflows (e.g. `Vet`) don't need a prefix.

Current workflows:

- `test-unit.yml` (`Test / Unit`, job: `unit`) — pytest suite (lint + unit tests)
- `test-pkgbuild.yml` (`Test / PKGBUILD`, job: `pkgbuild`) — Arch Linux package build + smoke test
- `vet.yml` (`Vet`, job: `vet`) — Self-review via vet on PRs (uses the reusable action via `uses: ./`)
- `vet-agentic.yml` (`Vet (Agentic)`, job: `vet`) — Agentic self-review via vet on PRs (uses the reusable action via `uses: ./`)
- `publish-pypi.yml` (`Publish / PyPI`, job: `pypi`) — Build and publish to PyPI on tag push
- `publish-github-release.yml` (`Publish / GitHub Release`, job: `github-release`) — Create a GitHub Release on tag push

### Continuous Deployment

Vet is published to PyPI via the `publish-pypi.yml` GitHub Actions workflow. Deployment is triggered by pushing a git tag that starts with `v` (e.g. `v0.2.0`).

### Releasing a new version

1. Create and checkout a branch to bump the version, using the naming convention `{name}/v{version}` (e.g. `john/v0.2.0`)
2. Update the version in `pyproject.toml`
3. Update `pkgver` in `pkg/arch/PKGBUILD`
4. Commit and push the changes
5. Tag the commit and push the tag:
   ```bash
   git tag v0.2.0 -m "v0.2.0: Updated XYZ"
   git push origin v0.2.0
   ```
6. Create a PR for the new branch
7. The `Publish / PyPI` workflow will automatically build and publish the package
8. Merge PR into main.

## Development Notes

### Logging

When creating a new entry point into vet, you must call `configure_logging(verbose: int, log_file: Path | None)` from `vet.cli.main`.

User-facing status messages (top-level lifecycle, warnings visible to the user) use `print(..., file=sys.stderr)` directly — not loguru. Loguru is for internal diagnostics only.

Log level heuristics:

- **TRACE** - API payloads, token counts, dollar costs, agent subprocess messages.
- **DEBUG** - Everything internal: API exceptions before re-raise, retries, fallbacks, identifier selection, history loading, context assembly. All LLM provider exception handlers must log at DEBUG before raising (see `_openai_exception_manager` for the pattern).
- **WARNING** - Degraded conditions: LLM content blocked/flagged, unrecognized config values, malformed user data. Note: spend limit warnings also `print()` directly to stderr so they are always visible to the user.
- **ERROR** - Failures that prevent producing results. Use `log_exception()` from `vet.imbue_core.async_monkey_patches` for tracebacks.

### README links

The README is rendered on PyPI which does not resolve relative links that otherwise work on GitHub. Always use full URLs when linking to resources from the README.
