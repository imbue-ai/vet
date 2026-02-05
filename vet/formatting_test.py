import subprocess
from pathlib import Path


def test_black_formatting():
    """Ensure all Python files are formatted with black."""
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        ["black", "--check", "."],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"black found formatting issues:\n{result.stderr}{result.stdout}"
