"""From https://github.com/OpenAutoCoder/Agentless/blob/main/agentless/util/compress_file.py"""

import re

from loguru import logger


def stubify_code_file(
    path: str | None,
    raw_code: str,
    keep_constant: bool = True,
    keep_indent: bool = False,
) -> str:
    # Defer libcst import to avoid pulling in the heavy library at module load time.
    # libcst costs ~165ms to import and is only needed when stubification is actually invoked.
    import libcst as cst
    import libcst.matchers as m

    from vet.imbue_tools.repo_utils._stubify_transformer import CompressTransformer

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
