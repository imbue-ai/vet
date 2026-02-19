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

You can use the `Dockerfile` in `dev/` at the repo root to create a container that suffices to run Vet for development purposes.

#### Setup

##### Basic Setup

Create a `.env` file at the repo that contains your API keys you'd like to use with Vet. The recommended API keys are `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `CODEX_API_KEY`.

NOTE: Claude Code is **not** installed into the image by default. See the agentic verifier section for an explanation.

Run the following command to build the image:

```bash
./dev/build.sh
```

Run the following command to start a container based on the image:

```bash
./dev/run.sh
```

You can then run Vet with:

```bash
uv run vet
```

This will be slower the first time you run it because `uv` has to set up your virtual environment, but since since the Vet repo is bind mounted into the container, subsequent runs should be fast.

##### Agentic Verifier

The agentic verifier calls out to Claude Code or Codex. Codex is part of the image by default, and if you have your `CODEX_API_KEY` set in your `.env` it will be used. As such, no further actions are required to run the agentic verifier with Codex unless you would like to use another auth approach which requires signing into Codex interactively (oauth and such).

Since Claude Code is proprietary, it is not installed by default. If you wish to have it installed as part of your image, run

```bash
./dev/build.sh claude
```

Then, to start a container based on this image run:

```bash
./dev/run.sh claude
```

NOTE: Without passing `claude` into `build.sh` it will default to the image without Claude Code installed.

Within the container, you can run `claude` to begin interactive authentication to get it setup.

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

1. Create and checkout a branch to bump the version
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

### Logging Configuration

When creating a new entrypoint into vet, you must call `ensure_core_log_levels_configured()` to register the custom log levels used throughout the codebase.

```python
from vet.imbue_core.log_utils import ensure_core_log_levels_configured

ensure_core_log_levels_configured()
```

### README links

The README is rendered on PyPI which does not resolve relative links that otherwise work on GitHub. Always use full URLs when linking to resources from the README.
