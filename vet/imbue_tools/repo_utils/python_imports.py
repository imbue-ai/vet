import ast
import sys
from pathlib import Path

from vet.imbue_core.pydantic_serialization import SerializableModel

STANDARD_LIBRARIES: frozenset[str] = sys.stdlib_module_names | frozenset(sys.builtin_module_names)


class QualifiedName(SerializableModel):
    """A qualified name like 'foo.bar.baz'."""

    value: str

    @property
    def top_level_name(self) -> "QualifiedName":
        """Return the top-level module name (e.g., 'foo' from 'foo.bar.baz')."""
        return QualifiedName(value=self.value.split(".", maxsplit=1)[0])

    @property
    def parent_name(self) -> "QualifiedName":
        """Return the parent module name (e.g., 'foo.bar' from 'foo.bar.baz')."""
        return QualifiedName(value=self.value.rsplit(".", maxsplit=1)[0])

    def to_path(self) -> Path:
        """Convert qualified name to a file path (e.g., 'foo.bar' -> 'foo/bar.py')."""
        return Path(self.value.replace(".", "/") + ".py")


class Import(SerializableModel):
    """Represents a single import statement."""

    source: str
    alias: str | None
    qualified_name: QualifiedName


def _collect_global_imports(node: ast.AST, imports: list[Import]) -> None:
    """
    Recursively collect import statements at global scope.

    Stops recursing into function and class definitions since imports
    inside those are not at global scope.

    Args:
        node: The AST node to process
        imports: List to accumulate found imports
    """
    if isinstance(node, ast.Import):
        # Handle: import foo, bar
        # Handle: import foo as bar
        for alias in node.names:
            if alias.asname:
                source = f"import {alias.name} as {alias.asname}"
                alias_name = alias.asname
            else:
                source = f"import {alias.name}"
                alias_name = None
            imports.append(
                Import(
                    source=source,
                    alias=alias_name,
                    qualified_name=QualifiedName(value=alias.name),
                )
            )
    elif isinstance(node, ast.ImportFrom):
        # Handle: from foo import bar, baz
        module = node.module or ""
        if node.names[0].name == "*":
            # from foo import *
            source = f"from {module} import *"
            imports.append(
                Import(
                    source=source,
                    alias=None,
                    qualified_name=QualifiedName(value=f"{module}.*"),
                )
            )
        else:
            for alias in node.names:
                if module:
                    full_name = f"{module}.{alias.name}"
                else:
                    # relative import like: from . import foo
                    full_name = alias.name

                if alias.asname:
                    source = f"from {module} import {alias.name} as {alias.asname}"
                    alias_name = alias.asname
                else:
                    source = f"from {module} import {alias.name}"
                    alias_name = None

                imports.append(
                    Import(
                        source=source,
                        alias=alias_name,
                        qualified_name=QualifiedName(value=full_name),
                    )
                )

    # Don't recurse into function or class definitions - imports there are not global
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return

    # Recurse into child nodes
    for child in ast.iter_child_nodes(node):
        _collect_global_imports(child, imports)


def get_global_imports(source_code: str) -> tuple[Import, ...]:
    """
    Extract all global imports from Python source code.

    This includes imports at module level, as well as imports inside conditionals
    or other control flow structures at the top level (not inside functions or classes).

    Args:
        source_code: Python source code as a string

    Returns:
        Tuple of Import objects representing all imports in the file

    Raises:
        SyntaxError: If the source code cannot be parsed
    """
    tree = ast.parse(source_code)
    imports: list[Import] = []
    _collect_global_imports(tree, imports)
    return tuple(imports)
