"""Smolagents tool definitions for filesystem and search operations.

These tools give the agent read-only access to the repository, mirroring the
capabilities available to the Claude/Codex harnesses.
"""

from __future__ import annotations

import glob as glob_module
import re
import subprocess
from pathlib import Path
from typing import Any


def make_tools(cwd: str | Path | None) -> list[Any]:
    """Build the list of smolagents Tool instances for a given working directory."""
    from smolagents import tool

    repo_root = Path(cwd).resolve() if cwd else Path.cwd()

    @tool
    def read_file(path: str) -> str:
        """Read the contents of a file at the given path.

        Args:
            path: Path to the file to read, relative to the repository root or absolute.
        """
        target = Path(path) if Path(path).is_absolute() else repo_root / path
        try:
            return target.read_text(errors="replace")
        except OSError as e:
            return f"Error reading file: {e}"

    @tool
    def list_directory(path: str = ".") -> str:
        """List the contents of a directory.

        Args:
            path: Directory path relative to the repository root (default: repository root).
        """
        target = Path(path) if Path(path).is_absolute() else repo_root / path
        try:
            entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
            lines = []
            for entry in entries:
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{entry.name}{suffix}")
            return "\n".join(lines) if lines else "(empty directory)"
        except OSError as e:
            return f"Error listing directory: {e}"

    @tool
    def glob(pattern: str, base_path: str = ".") -> str:
        """Find files matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g. '**/*.py', 'src/*.ts').
            base_path: Base directory for the search, relative to the repository root.
        """
        base = Path(base_path) if Path(base_path).is_absolute() else repo_root / base_path
        matches = sorted(glob_module.glob(pattern, root_dir=str(base), recursive=True))
        if not matches:
            return "No files found matching pattern."
        return "\n".join(matches)

    @tool
    def grep(pattern: str, path: str = ".", include: str = "") -> str:
        """Search for a regex pattern in files.

        Args:
            pattern: Regular expression pattern to search for.
            path: Directory or file to search in, relative to the repository root.
            include: Optional glob pattern to restrict which files are searched (e.g. '*.py').
        """
        target = Path(path) if Path(path).is_absolute() else repo_root / path
        try:
            results: list[str] = []
            glob_pattern = include if include else "**/*"
            if target.is_file():
                files = [target]
            else:
                files = [Path(p) for p in glob_module.glob(glob_pattern, root_dir=str(target), recursive=True)]
                files = [target / f for f in files if (target / f).is_file()]
            compiled = re.compile(pattern)
            for file_path in sorted(files):
                try:
                    for lineno, line in enumerate(file_path.read_text(errors="replace").splitlines(), 1):
                        if compiled.search(line):
                            rel = file_path.relative_to(repo_root)
                            results.append(f"{rel}:{lineno}: {line}")
                except OSError:
                    continue
            if not results:
                return "No matches found."
            return "\n".join(results[:500])  # cap at 500 lines to avoid context overflow
        except re.error as e:
            return f"Invalid regex pattern: {e}"

    @tool
    def run_command(command: str) -> str:
        """Run a shell command in the repository root and return its output.

        Only read-only commands are appropriate (e.g. git log, git diff, find, cat).
        Do not use this to modify files.

        Args:
            command: Shell command to run.
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(repo_root),
                timeout=30,
            )
            output = result.stdout
            if result.returncode != 0 and result.stderr:
                output += f"\nstderr: {result.stderr}"
            return output or "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: command timed out after 30 seconds."
        except OSError as e:
            return f"Error running command: {e}"

    return [read_file, list_directory, glob, grep, run_command]
