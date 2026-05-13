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


@pytest.fixture(autouse=True)
def _clear_lru_cache():
    from vet.imbue_tools.repo_utils.diff_utils import apply_diffs_to_files

    apply_diffs_to_files.cache_clear()
    yield
    apply_diffs_to_files.cache_clear()


class TestApplyDiffRenames:
    def test_rename_with_edit(self):
        base = InMemoryFileSystem.build({"old_name.py": b'def hello():\n    return "old"\n'})
        result = asyncio.run(_apply_diff_to_files(base, RENAME_DIFF))
        assert "new_name.py" in result.files
        assert "old_name.py" not in result.files

    def test_new_file_not_in_base(self):
        base = InMemoryFileSystem.build({"unrelated.py": b"pass\n"})
        result = asyncio.run(_apply_diff_to_files(base, NEW_FILE_DIFF))
        assert "brand_new.py" in result.files
        assert "unrelated.py" in result.files

    def test_context_mismatch(self):
        base = InMemoryFileSystem.build({"existing.py": b'def hello():\n    return "actual content"\n'})
        result = asyncio.run(_apply_diff_to_files(base, CONTEXT_MISMATCH_DIFF))
        assert "existing.py" in result.files
