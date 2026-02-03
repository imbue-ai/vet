"""Command-line interface for vet-history.

Usage:
    vet-history claude-code [--latest | --session ID | --project PATH]
    vet-history opencode [--session current | --session ID]
    vet-history codex [--latest | --session ID]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vet_history import __version__
from vet_history.loaders.base import LoaderError
from vet_history.loaders.base import SessionNotFoundError
from vet_history.loaders.base import SessionParseError
from vet_history.types import messages_to_jsonl


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="vet-history",
        description="Extract conversation history from coding agents for VET",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vet-history claude-code --latest
  vet-history claude-code --project .
  vet-history opencode --session current
  vet-history codex --latest

Use with VET:
  vet --history-loader "vet-history claude-code --latest"
        """,
    )

    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    # Create subparsers for each agent
    subparsers = parser.add_subparsers(
        dest="agent",
        title="agents",
        description="Supported coding agents",
        required=True,
    )

    # Claude Code subcommand
    claude_parser = subparsers.add_parser(
        "claude-code",
        help="Extract history from Claude Code",
        description="Load conversation history from Claude Code sessions",
    )
    claude_group = claude_parser.add_mutually_exclusive_group()
    claude_group.add_argument(
        "--latest",
        action="store_true",
        default=True,
        help="Load the most recent session (default)",
    )
    claude_group.add_argument(
        "--session",
        "-s",
        type=str,
        metavar="ID",
        help="Load a specific session by UUID",
    )
    claude_group.add_argument(
        "--project",
        "-p",
        type=Path,
        metavar="PATH",
        help="Load the latest session for a project path",
    )
    claude_parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List available sessions instead of loading",
    )

    # OpenCode subcommand
    opencode_parser = subparsers.add_parser(
        "opencode",
        help="Extract history from OpenCode",
        description="Load conversation history from OpenCode sessions",
    )
    opencode_group = opencode_parser.add_mutually_exclusive_group()
    opencode_group.add_argument(
        "--latest",
        action="store_true",
        default=True,
        help="Load the most recent session (default)",
    )
    opencode_group.add_argument(
        "--session",
        "-s",
        type=str,
        metavar="ID",
        help="Load a specific session by ID",
    )
    opencode_parser.add_argument(
        "--project",
        "-p",
        type=Path,
        metavar="PATH",
        help="Filter sessions to those in this project directory",
    )
    opencode_parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List available sessions instead of loading",
    )

    # Codex CLI subcommand
    codex_parser = subparsers.add_parser(
        "codex",
        help="Extract history from Codex CLI",
        description="Load conversation history from Codex CLI sessions",
    )
    codex_group = codex_parser.add_mutually_exclusive_group()
    codex_group.add_argument(
        "--latest",
        action="store_true",
        default=True,
        help="Load the most recent session (default)",
    )
    codex_group.add_argument(
        "--session",
        "-s",
        type=str,
        metavar="ID",
        help="Load a specific session by UUID",
    )
    codex_parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List available sessions instead of loading",
    )

    return parser


def cmd_claude_code(args: argparse.Namespace) -> int:
    """Handle claude-code subcommand."""
    from vet_history.loaders.claude_code import ClaudeCodeLoader

    try:
        loader = ClaudeCodeLoader()
    except LoaderError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.list:
        project_path = args.project if hasattr(args, "project") and args.project else None
        sessions = loader.list_sessions(project_path)
        if not sessions:
            print("No sessions found.", file=sys.stderr)
            return 1
        print("Available Claude Code sessions:")
        for session in sessions:
            updated = session.updated_at.isoformat() if session.updated_at else "unknown"
            project = session.project_path or "unknown"
            print(f"  {session.session_id}  {updated}  {project}")
        return 0

    try:
        if args.session:
            messages = loader.load_by_id(args.session)
        elif args.project:
            messages = loader.load_latest(args.project)
        else:
            messages = loader.load_latest()
    except SessionNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except SessionParseError as e:
        print(f"Error parsing session: {e}", file=sys.stderr)
        return 1

    # Output JSONL to stdout
    print(messages_to_jsonl(messages))
    return 0


def cmd_opencode(args: argparse.Namespace) -> int:
    """Handle opencode subcommand."""
    from vet_history.loaders.opencode import OpenCodeLoader

    try:
        loader = OpenCodeLoader()
    except LoaderError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    project_path = args.project if hasattr(args, "project") and args.project else None

    if args.list:
        sessions = loader.list_sessions(project_path)
        if not sessions:
            print("No sessions found.", file=sys.stderr)
            return 1
        print("Available OpenCode sessions:")
        for session in sessions:
            updated = session.updated_at.isoformat() if session.updated_at else "unknown"
            title = session.title[:50] if session.title else "untitled"
            project = session.project_path or ""
            print(f"  {session.session_id}  {updated}  {title}")
            if project:
                print(f"      {project}")
        return 0

    try:
        if args.session:
            messages = loader.load_by_id(args.session)
        else:
            messages = loader.load_latest(project_path)
    except SessionNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except SessionParseError as e:
        print(f"Error parsing session: {e}", file=sys.stderr)
        return 1

    # Output JSONL to stdout
    print(messages_to_jsonl(messages))
    return 0


def cmd_codex(args: argparse.Namespace) -> int:
    """Handle codex subcommand."""
    from vet_history.loaders.codex import CodexLoader

    try:
        loader = CodexLoader()
    except LoaderError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.list:
        sessions = loader.list_sessions()
        if not sessions:
            print("No sessions found.", file=sys.stderr)
            return 1
        print("Available Codex CLI sessions:")
        for session in sessions:
            updated = session.updated_at.isoformat() if session.updated_at else "unknown"
            title = session.title[:50] if session.title else "untitled"
            print(f"  {session.session_id}  {updated}  {title}")
        return 0

    try:
        if args.session:
            messages = loader.load_by_id(args.session)
        else:
            messages = loader.load_latest()
    except SessionNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except SessionParseError as e:
        print(f"Error parsing session: {e}", file=sys.stderr)
        return 1

    # Output JSONL to stdout
    print(messages_to_jsonl(messages))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point for vet-history CLI."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.agent == "claude-code":
        return cmd_claude_code(args)
    elif args.agent == "opencode":
        return cmd_opencode(args)
    elif args.agent == "codex":
        return cmd_codex(args)
    else:
        parser.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())
