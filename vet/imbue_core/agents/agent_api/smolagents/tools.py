import glob as glob_module
import os
import subprocess
from pathlib import Path

from smolagents import Tool

_MAX_LINES = 2000
_MAX_LINE_LENGTH = 2000


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read the contents of a file at the given path and return them as text. "
        "Returns up to 2000 lines by default. Use offset and limit for large files. "
        "Use this to inspect source code, configuration files, or any text file."
    )
    inputs = {
        "file_path": {
            "type": "string",
            "description": "The path to the file to read (absolute or relative to the working directory).",
        },
        "offset": {
            "type": "number",
            "description": "The line number to start reading from (1-indexed). Omit to start from the top.",
            "nullable": True,
        },
        "limit": {
            "type": "number",
            "description": "The number of lines to read. Omit to read up to the default maximum.",
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self._cwd = cwd or "."

    def forward(self, file_path: str, offset: int | None = None, limit: int | None = None) -> str:
        path = Path(file_path)
        if not path.is_absolute():
            path = Path(self._cwd) / path
        path = path.resolve()

        if not path.exists():
            return f"Error: File not found: {path}"
        if not path.is_file():
            return f"Error: Not a file: {path}"

        effective_limit = min(int(limit), _MAX_LINES) if limit is not None else _MAX_LINES
        effective_offset = max(0, int(offset) - 1) if offset is not None else 0

        encodings = ["utf-8", "latin-1", "cp1252"]
        lines = None
        for enc in encodings:
            try:
                with open(path, encoding=enc) as f:
                    lines = f.readlines()
                break
            except UnicodeDecodeError:
                continue

        if lines is None:
            return f"Error: Cannot read binary file: {path}"

        total_lines = len(lines)
        selected = lines[effective_offset : effective_offset + effective_limit]
        truncated = (effective_offset + effective_limit) < total_lines

        result_parts = []
        for i, line in enumerate(selected):
            line_number = effective_offset + i + 1
            text = line.rstrip("\n")
            if len(text) > _MAX_LINE_LENGTH:
                text = text[:_MAX_LINE_LENGTH] + "... (line truncated)"
            result_parts.append(f"{line_number:6d}\t{text}")

        result = "\n".join(result_parts)
        if truncated:
            result += (
                f"\n\n(File truncated. Showing lines {effective_offset + 1}-"
                f"{effective_offset + len(selected)} of {total_lines}. Use offset/limit to read more.)"
            )
        return result


class GrepTool(Tool):
    name = "grep"
    description = (
        "Search for a regex pattern in files under a given path. "
        "Returns matching lines with file paths, line numbers, and surrounding context. "
        "Powered by ripgrep (rg) for fast searching."
    )
    inputs = {
        "pattern": {
            "type": "string",
            "description": "The regex pattern to search for.",
        },
        "path": {
            "type": "string",
            "description": "The directory or file to search in. Defaults to the working directory.",
            "nullable": True,
        },
        "include": {
            "type": "string",
            "description": "Glob pattern to filter files (e.g. '*.py', '*.ts'). Optional.",
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self._cwd = cwd or "."

    def forward(self, pattern: str, path: str | None = None, include: str | None = None) -> str:
        search_path = path or self._cwd
        cmd: list[str] = ["rg", "--no-heading", "-n", "-C", "3", "--max-count", "200"]
        if include:
            cmd.extend(["--glob", include])
        cmd.extend([pattern, search_path])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=self._cwd)
            output = result.stdout.strip()
            if not output:
                return f"No matches found for pattern: {pattern}"
            return output
        except FileNotFoundError:
            fallback_cmd: list[str] = ["grep", "-rn", "-C", "3"]
            if include:
                fallback_cmd.extend(["--include", include])
            fallback_cmd.extend([pattern, search_path])
            try:
                result = subprocess.run(
                    fallback_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=self._cwd,
                )
                output = result.stdout.strip()
                if not output:
                    return f"No matches found for pattern: {pattern}"
                return output
            except Exception as e:
                return f"Error during search: {e}"
        except subprocess.TimeoutExpired:
            return "Error: Search timed out after 30 seconds."
        except Exception as e:
            return f"Error during search: {e}"


class GlobTool(Tool):
    name = "glob"
    description = (
        "Find files matching a glob pattern under a given directory. "
        "Returns a list of matching file paths, one per line. "
        "Supports recursive patterns like '**/*.py' and brace expansion like '**/*.{ts,tsx}'."
    )
    inputs = {
        "pattern": {
            "type": "string",
            "description": "The glob pattern to match (e.g. '**/*.py', 'src/**/*.{ts,tsx}').",
        },
        "path": {
            "type": "string",
            "description": "The base directory to search from. Defaults to the working directory.",
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self._cwd = cwd or "."

    def forward(self, pattern: str, path: str | None = None) -> str:
        base_path = Path(path or self._cwd)
        if not base_path.is_absolute():
            base_path = Path(self._cwd) / base_path
        base_path = base_path.resolve()

        if not base_path.exists():
            return f"Error: Directory not found: {base_path}"
        if not base_path.is_dir():
            return f"Error: Not a directory: {base_path}"

        if "{" in pattern and "}" in pattern:
            prefix, rest = pattern.split("{", 1)
            options_str, suffix = rest.split("}", 1)
            patterns = [f"{prefix}{opt}{suffix}" for opt in options_str.split(",")]
        else:
            patterns = [pattern]

        try:
            all_matches: set[str] = set()
            for p in patterns:
                for match in glob_module.glob(str(base_path / p), recursive=True):
                    if os.path.isfile(match):
                        all_matches.add(match)

            matches = sorted(all_matches)
            if not matches:
                return f"No files found matching pattern: {pattern}"

            max_results = 200
            result_lines = matches[:max_results]
            if len(matches) > max_results:
                result_lines.append(f"... and {len(matches) - max_results} more files")
            return "\n".join(result_lines)
        except Exception as e:
            return f"Error during glob: {e}"


class ListDirectoryTool(Tool):
    name = "list_directory"
    description = (
        "List the contents of a directory, showing files and subdirectories. "
        "Hidden files and __pycache__ directories are excluded. "
        "Directories are shown with a trailing '/'."
    )
    inputs = {
        "path": {
            "type": "string",
            "description": "The directory path to list. Defaults to the working directory.",
            "nullable": True,
        },
    }
    output_type = "string"

    _SKIP_NAMES = {"__pycache__", ".git", ".mypy_cache", ".ruff_cache", ".pytest_cache"}

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self._cwd = cwd or "."

    def forward(self, path: str | None = None) -> str:
        dir_path = Path(path or self._cwd)
        if not dir_path.is_absolute():
            dir_path = Path(self._cwd) / dir_path
        dir_path = dir_path.resolve()

        if not dir_path.exists():
            return f"Error: Directory not found: {dir_path}"
        if not dir_path.is_dir():
            return f"Error: Not a directory: {dir_path}"

        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            result = []
            for entry in entries:
                if entry.name.startswith(".") or entry.name in self._SKIP_NAMES:
                    continue
                result.append(f"{entry.name}/" if entry.is_dir() else entry.name)
            return "\n".join(result) if result else "(empty directory)"
        except PermissionError:
            return f"Error: Permission denied: {dir_path}"
        except Exception as e:
            return f"Error listing directory: {e}"


def build_safe_tools(cwd: str | None = None) -> list[Tool]:
    return [
        ReadFileTool(cwd=cwd),
        GrepTool(cwd=cwd),
        GlobTool(cwd=cwd),
        ListDirectoryTool(cwd=cwd),
    ]
