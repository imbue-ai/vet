# Development

For general usage, installation, and configuration, see the [README](README.md).

## Dev Setup

```bash
uv sync
```

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
- `vet.yml` (`Vet`, job: `vet`) — Self-review via vet on PRs
- `publish-pypi.yml` (`Publish / PyPI`, job: `pypi`) — Build and publish to PyPI on tag push

### Continuous Deployment

Vet is published to PyPI via the `publish-pypi.yml` GitHub Actions workflow. Deployment is triggered by pushing a git tag that starts with `v` (e.g. `v0.2.0`).

### Releasing a new version

1. Create and checkout a branch to bump the version
2. Update the version in `pyproject.toml`
3. Update `pkgver` in `pkg/arch/PKGBUILD`
4. Update the recommended GitHub action pinned version in the `README.md` 
   ```yaml
   - run: pip install verify-everything==0.2.0
   ```
5. Commit and push the changes
6. Tag the commit and push the tag:
   ```bash
   git tag v0.2.0 -m "v0.2.0: Updated XYZ"
   git push origin v0.2.0
   ```
7. Create a PR for the new branch
8. The `Publish / PyPI` workflow will automatically build and publish the package
9. Merge PR into main.

### Why pin the version in the README?

The README contains a sample GitHub Actions workflow that users copy into their repos. The `pip install verify-everything==X.Y.Z` line in that sample should always reference the latest stable release so that new adopters get a known-good version. Vet is very much experimental. While we give guarantees about it working in a barebones sense, it is not guaranteed that breaking changes won't be made over time so pinning a version for CI makes sense for most use cases.

## Development Notes

### Logging Configuration

When creating a new entrypoint into vet, you must call `ensure_core_log_levels_configured()` to register the custom log levels used throughout the codebase.

```python
from vet.imbue_core.log_utils import ensure_core_log_levels_configured

ensure_core_log_levels_configured()
```

### README links

The README is rendered on PyPI which does not resolve relative links that otherwise work on GitHub. Always use full URLs when linking to resources from the README.
