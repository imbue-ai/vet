import asyncio
import inspect
import os
import shutil
from contextlib import asynccontextmanager
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from typing import AsyncGenerator
from typing import Callable
from typing import ContextManager
from typing import Coroutine
from typing import Generator
from typing import Iterable
from typing import Protocol
from typing import Sequence
from typing import TYPE_CHECKING
from typing import TypeVar
from uuid import uuid4

import anyio
import pytest
import pytest_asyncio
from _pytest.fixtures import Config
from _pytest.python import Function

from imbue_core.common import get_temp_dir

if TYPE_CHECKING:
    # noinspection PyProtectedMember
    from _pytest.fixtures import _ScopeName

T = TypeVar("T")

_TestFunc = Callable[..., None] | Callable[..., Coroutine[Any, Any, None]]


def fixture(
    fixture_function: Any | None = None,
    *,
    scope: "_ScopeName | Callable[[str, Config], _ScopeName]" = "function",
    params: Iterable[object] | None = None,
    autouse: bool = False,
    ids: Sequence[object | None] | Callable[[Any], object | None] | None = None,
) -> Any:
    def decorator(function: Any) -> Any:
        true_name = function.__name__[:-1]
        if inspect.iscoroutinefunction(function):
            return pytest_asyncio.fixture(
                function,
                name=true_name,
                scope=scope,
                params=params,
                autouse=autouse,
                ids=ids,  # type: ignore
            )
        else:
            return pytest.fixture(
                function,
                name=true_name,
                scope=scope,
                params=params,
                autouse=autouse,
                ids=ids,
            )

    if fixture_function is not None and callable(fixture_function):
        return decorator(fixture_function)

    return decorator


def placeholder_param_for_mark(
    marks: pytest.MarkDecorator | list[pytest.MarkDecorator],
) -> object:
    """Returns a param for annotating a fixture with marks.

    It can be useful to add marks to a fixture that propagate to all functions that use it.
    However, decorating a fixture function with "@pytest.mark.foo_bar" has no effect.

    On the other hand, parameterized fixtures can have marks attached to each parameter;
    thus a workaround is to parameterize the fixture with a single placeholder param.
    Use this function like this:

        @pytest.fixture(params=placeholder_param_for_mark(pytest.mark.foo_bar))

    One slightly annoying side effect is that the param will show up in the test name.
    We can get rid of it with pytest_collection_modifyitems,
    but it's probably simpler to live with it.

    You don't need this function if the fixture is already parameterized;
    simply add the desired mark to the params:

        @pytest.fixture(params=[pytest.param(0, marks=pytest.mark.foo_bar),
                                pytest.param(1, marks=pytest.mark.foo_bar)])

    See https://github.com/pytest-dev/pytest/issues/1368 for more context.
    """
    return pytest.param("placeholder_param", marks=marks)


def use(*args: Callable[..., Any]) -> Any:
    true_names = [x.__name__[:-1] for x in args]
    return pytest.mark.usefixtures(*true_names)


def integration_test(function: _TestFunc) -> Any:
    return pytest.mark.integration_test(function)


def slow_integration_test(function: _TestFunc) -> Any:
    return pytest.mark.slow_integration_test(function)


class RequestFixture(Protocol[T]):
    """Yes, there is a class called FixtureRequest, but the types are quite bad for it"""

    node: Function
    param: T


@fixture
def temp_file_path_() -> Generator[Path, None, None]:
    with create_temp_file_path() as output:
        yield output


@fixture
def temp_path_() -> Generator[Path, None, None]:
    with temp_dir(get_temp_dir()) as output:
        yield output


def create_temp_file_path(cleanup: bool = True) -> ContextManager[Path]:
    @contextmanager
    def context() -> Generator[Path, None, None]:
        random_id = uuid4()
        output_path = os.path.join(get_temp_dir(), str(random_id))
        try:
            yield Path(output_path)
        finally:
            if cleanup and os.path.exists(output_path):
                if os.path.isfile(output_path):
                    os.remove(output_path)
                else:
                    shutil.rmtree(output_path)

    # noinspection PyTypeChecker
    return context()


def temp_dir(base_dir: str, is_uuid_concatenated: bool = False) -> ContextManager[Path]:
    @contextmanager
    def context() -> Generator[Path, None, None]:
        random_id = uuid4()
        if is_uuid_concatenated:
            output_path = Path(base_dir.rstrip("/") + "_" + str(random_id))
        else:
            output_path = Path(base_dir) / str(random_id)
        output_path.mkdir(parents=True, exist_ok=True)
        try:
            yield output_path
        finally:
            if output_path.exists():
                try:
                    shutil.rmtree(str(output_path))
                except OSError:
                    os.unlink(str(output_path))

    # noinspection PyTypeChecker
    return context()


@asynccontextmanager
async def async_temp_dir(base_dir: str, is_uuid_concatenated: bool = False) -> AsyncGenerator[Path, None]:
    random_id = uuid4()
    if is_uuid_concatenated:
        output_path = anyio.Path(base_dir.rstrip("/") + "_" + str(random_id))
    else:
        output_path = anyio.Path(base_dir) / str(random_id)
    await output_path.mkdir(parents=True, exist_ok=True)
    try:
        yield Path(output_path)
    finally:
        if await output_path.exists():
            try:
                await asyncio.to_thread(shutil.rmtree, str(output_path))
            except OSError:
                await output_path.unlink()
