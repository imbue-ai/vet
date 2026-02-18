#!/usr/bin/env bash
set -euo pipefail

REPO="imbue-ai/vet"
BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/${REPO}/${BRANCH}/skills/vet"
FILES=(
  "SKILL.md"
  "scripts/export_opencode_session.py"
  "scripts/export_codex_session.py"
  "scripts/export_claude_code_session.py"
)

echo ""
echo "  Vet Skill Installer"
echo "  --------------------"
echo ""
echo "  [1] Project level  - install into the current repo (.agents/ and .claude/)"
echo "  [2] User level     - install into your home directory (~/.agents/, ~/.opencode/, ~/.claude/, ~/.codex/)"
echo ""

printf "  Choose [1/2]: " 
read -r choice </dev/tty

case "$choice" in
  1)
    dirs=(".agents" ".claude")
    label="project"
    ;;
  2)
    dirs=("$HOME/.agents" "$HOME/.opencode" "$HOME/.claude" "$HOME/.codex")
    label="user"
    ;;
  *)
    echo "  Invalid choice. Exiting."
    exit 1
    ;;
esac

echo ""

for dir in "${dirs[@]}"; do
  mkdir -p "$dir/skills/vet/scripts"
  for file in "${FILES[@]}"; do
    printf "  Downloading %s -> %s/skills/vet/%s\n" "$file" "$dir" "$file"
    curl -fsSL "${BASE_URL}/${file}" -o "$dir/skills/vet/$file"
  done
done

echo ""
echo "  Done! Vet skill installed at the ${label} level."

if [ "$label" = "project" ]; then
  echo ""
  echo "  Installed to:"
  for dir in "${dirs[@]}"; do
    echo "    $dir/skills/vet/"
  done
  echo ""
  echo "  You may want to commit these files to your repo."
fi

echo ""
