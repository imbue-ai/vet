import asyncio

import pytest

from vet.imbue_tools.repo_utils.diff_utils import _apply_diff_to_files
from vet.imbue_tools.repo_utils.file_system import InMemoryFileSystem

RENAME_DIFF = """\
diff --git a/old_name.py b/new_name.py
similarity index 85%
rename from old_name.py
rename to new_name.py
index 1234567..abcdefg 100644
--- a/old_name.py
+++ b/new_name.py
@@ -1,3 +1,3 @@
 def hello():
-    return "old"
+    return "new"
"""

PURE_RENAME_DIFF = """\
diff --git a/before.py b/after.py
similarity index 100%
rename from before.py
rename to after.py
"""

NEW_FILE_DIFF = """\
diff --git a/brand_new.py b/brand_new.py
new file mode 100644
index 0000000..abcdefg
--- /dev/null
+++ b/brand_new.py
@@ -0,0 +1,2 @@
+def brand_new():
+    pass
"""

CONTEXT_MISMATCH_DIFF = """\
diff --git a/existing.py b/existing.py
index 1234567..abcdefg 100644
--- a/existing.py
+++ b/existing.py
@@ -1,3 +1,3 @@
 def hello():
-    return "wrong context"
+    return "updated"
"""

PARTIAL_EDIT_DIFF_MISMATCHED = """\
diff --git a/big_file.py b/big_file.py
index 1234567..abcdefg 100644
--- a/big_file.py
+++ b/big_file.py
@@ -3,3 +3,3 @@
 wrong_context_line3
-wrong_context_line4
+line4_modified
 wrong_context_line5
"""

DELETE_DIFF = """\
diff --git a/doomed.py b/doomed.py
deleted file mode 100644
index abcdefg..0000000
--- a/doomed.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def doomed():
-    pass
"""


@pytest.fixture(autouse=True)
def _clear_lru_cache():
    from vet.imbue_tools.repo_utils.diff_utils import apply_diffs_to_files

    apply_diffs_to_files.cache_clear()
    yield
    apply_diffs_to_files.cache_clear()


class TestApplyDiffFallback:
    def test_rename_with_edit(self):
        base = InMemoryFileSystem.build({"old_name.py": b'def hello():\n    return "old"\n'})
        result = asyncio.run(_apply_diff_to_files(base, RENAME_DIFF))
        assert "new_name.py" in result.files
        assert "old_name.py" not in result.files
        text = result.files["new_name.py"].decode() if isinstance(result.files["new_name.py"], bytes) else ""
        assert "def hello():" in text
        assert "new" in text

    def test_pure_rename_preserves_content(self):
        content = b"original content\nline two\n"
        base = InMemoryFileSystem.build({"before.py": content})
        result = asyncio.run(_apply_diff_to_files(base, PURE_RENAME_DIFF))
        assert "after.py" in result.files
        assert "before.py" not in result.files
        assert result.files["after.py"] == content

    def test_new_file_content(self):
        base = InMemoryFileSystem.build({"unrelated.py": b"pass\n"})
        result = asyncio.run(_apply_diff_to_files(base, NEW_FILE_DIFF))
        text = result.files["brand_new.py"].decode() if isinstance(result.files["brand_new.py"], bytes) else ""
        assert "def brand_new():" in text
        assert "pass" in text
        assert result.files["unrelated.py"] == b"pass\n"

    def test_context_mismatch_preserves_context_lines(self):
        base = InMemoryFileSystem.build({"existing.py": b'def hello():\n    return "actual content"\n'})
        result = asyncio.run(_apply_diff_to_files(base, CONTEXT_MISMATCH_DIFF))
        text = result.files["existing.py"].decode() if isinstance(result.files["existing.py"], bytes) else ""
        assert "updated" in text
        assert "def hello():" in text

    def test_partial_edit_preserves_all_lines(self):
        base_content = b"line1\nline2\nline3\nline4\nline5\nline6\nline7\n"
        base = InMemoryFileSystem.build({"big_file.py": base_content})
        result = asyncio.run(_apply_diff_to_files(base, PARTIAL_EDIT_DIFF_MISMATCHED))
        text = result.files["big_file.py"].decode() if isinstance(result.files["big_file.py"], bytes) else ""
        assert "line1" in text
        assert "line2" in text
        assert "line3" in text
        assert "line4_modified" in text
        assert "line5" in text
        assert "line6" in text
        assert "line7" in text

    def test_delete_removes_file(self):
        base = InMemoryFileSystem.build(
            {
                "doomed.py": b"def doomed():\n    pass\n",
                "keeper.py": b"keep\n",
            }
        )
        result = asyncio.run(_apply_diff_to_files(base, DELETE_DIFF))
        assert "doomed.py" not in result.files
        assert "keeper.py" in result.files
