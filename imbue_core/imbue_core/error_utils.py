"""Error handling utilities."""

import sys
import traceback

import traceback_with_variables
from traceback_with_variables import Format


def get_traceback_with_vars(exception: BaseException | None = None) -> str:

    # be careful of potential performance regressions with increasing these limits
    tb_format = Format(max_value_str_len=100_000, max_exc_str_len=2_000_000)
    if exception is None:
        # no exception passed in; get the current exception. this will still be None if not in an exception handler
        exception = sys.exception()
    try:
        if exception is not None:
            # we are in an exception handler, use that for the traceback
            # for some reason this breaks when casting to an `Exception`, so just using type: ignore
            return traceback_with_variables.format_exc(exception, fmt=tb_format)  # type: ignore
        else:
            # not in an exception handler, just get the current stack
            return traceback_with_variables.format_cur_tb(fmt=tb_format)
    except Exception as e:
        return (
            f"got exception while formatting traceback with `traceback_with_variables`: {traceback.format_exception(e)}"
        )
