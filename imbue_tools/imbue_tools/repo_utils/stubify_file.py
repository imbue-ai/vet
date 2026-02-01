"""From https://github.com/OpenAutoCoder/Agentless/blob/main/agentless/util/compress_file.py"""

import re
from typing import Any
from typing import Callable

import libcst as cst
import libcst.matchers as m
from loguru import logger


def check_on_body(stmt: cst.CSTNode, check: Callable[[cst.CSTNode], bool]) -> bool:
    if not m.matches(stmt, m.SimpleStatementLine()):
        return False
    # pyre-ignore[16]: m.SimpleStatementLine has a body attribute which is a Sequence
    first_body_item = stmt.body[0]
    return check(first_body_item)


class CompressTransformer(cst.CSTTransformer):
    DESCRIPTION = str = "Replaces function body with ..."
    replacement_string = '"__FUNC_BODY_REPLACEMENT_STRING__"'

    def __init__(self, keep_constant: bool = True, keep_indent: bool = False) -> None:
        self.keep_constant = keep_constant
        self.keep_indent = keep_indent

    def leave_Module(
        self, original_node: cst.Module, updated_node: cst.Module
    ) -> cst.Module:
        new_body = [
            stmt
            for stmt in updated_node.body
            if m.matches(stmt, m.ClassDef())
            or m.matches(stmt, m.FunctionDef())
            or (
                self.keep_constant
                and check_on_body(
                    stmt, lambda first_body_item: m.matches(first_body_item, m.Assign())
                )
            )
        ]
        return updated_node.with_changes(body=new_body)

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.ClassDef:
        # Remove docstring in the class body
        new_body = [
            stmt
            for stmt in updated_node.body.body
            if not check_on_body(
                stmt,
                lambda first_body_item: m.matches(first_body_item, m.Expr())
                or (
                    hasattr(first_body_item, "value")
                    and m.matches(first_body_item.value, m.SimpleString())
                ),
            )
        ]
        # pyre-fixme[6]: cst.IndentedBlock has a body attribute which is a Sequence[BaseStatement], not a Sequence[BaseSmallStatement] like new_body
        return updated_node.with_changes(body=cst.IndentedBlock(body=new_body))

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.BaseStatement:
        if not self.keep_indent:
            # replace with unindented statement
            new_expr = cst.Expr(value=cst.SimpleString(value=self.replacement_string))
            # pyre-fixme[6]: cst.Expr is a BaseSmallStatement, not a BaseStatement like new_expr
            new_body = cst.IndentedBlock((new_expr,))
            return updated_node.with_changes(body=new_body)
        else:
            # replace with indented statement
            # new_expr = [cst.Pass()]
            new_expr = [
                cst.Expr(value=cst.SimpleString(value=self.replacement_string)),
            ]
            return updated_node.with_changes(
                body=cst.IndentedBlock(body=[cst.SimpleStatementLine(body=new_expr)])
            )


def stubify_code_file(
    path: str | None,
    raw_code: str,
    keep_constant: bool = True,
    keep_indent: bool = False,
) -> str:
    try:
        tree = cst.parse_module(raw_code)
    except cst.ParserSyntaxError:
        logger.debug("failed to stubify code file {}; will leave it as is", path)
        return raw_code

    transformer = CompressTransformer(keep_constant=keep_constant, keep_indent=True)
    modified_tree = tree.visit(transformer)
    code = modified_tree.code

    if keep_indent:
        code = code.replace(CompressTransformer.replacement_string + "\n", "...\n")
        code = code.replace(CompressTransformer.replacement_string, "...\n")
    else:
        pattern = f"\\n[ \\t]*{CompressTransformer.replacement_string}"
        replacement = "\n..."
        code = re.sub(pattern, replacement, code)

    return code
