from types import TracebackType
from typing import Any
from typing import Self
from typing import cast

from tblib import Traceback


class FixedTraceback(Traceback):
    """
    This class exists mostly to fix a bug in tblib where tb_lasti is not properly initialized.
    We don't care about that value, so we just set it to -1.

    While I was at it, I also fixed the types for the methods we use.
    """

    def __init__(self, tb: TracebackType) -> None:
        super().__init__(tb)
        tb_next = self
        while tb_next:
            setattr(tb_next, "tb_lasti", -1)
            tb_next = tb_next.tb_next

    def as_traceback(self) -> TracebackType | None:
        return cast(TracebackType | None, super().as_traceback())

    @classmethod
    def from_tb(cls, tb: TracebackType) -> Self:
        result = cls(tb)
        return result

    @classmethod
    def from_dict(cls, dct: dict[str, Any]) -> Self:
        # pyre-fixme[11]: pyre seems to have some trouble with Self in some specific cases, including cast
        return cast(cls, super().from_dict(dct))
