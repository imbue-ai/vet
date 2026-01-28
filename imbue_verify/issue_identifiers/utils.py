import contextvars
import queue
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Generator
from typing import Generic
from typing import Iterable
from typing import TypeVar
from xml.sax.saxutils import escape


def xml_post_escape(input_string: str, element_to_post_escape: str) -> str:
    """
    Post-escape the XML string by replacing the element_to_post_escape with the escaped version of it.

    We do this because LLMs cannot reliably xml-escape strings themselves so we need to try doing that after the fact.

    Arguments:
        input_string -- the whole xml response as a string to post-escape
        element_to_post_escape -- the element to post-escape (e.g. "code_part")

    """
    pattern = re.compile(f"<({element_to_post_escape})>(.*?)</({element_to_post_escape})>", re.IGNORECASE | re.DOTALL)
    return re.sub(
        pattern,
        lambda x: f"<{x.group(1)}>{escape(x.group(2))}</{x.group(3)}>",
        input_string,
    )


IterT = TypeVar("IterT")
ReturnT = TypeVar("ReturnT")


class ReturnCapturingGenerator(Generic[IterT, ReturnT]):
    """
    A wrapper around a generator that captures the return value when the generator is exhausted.

    Usually, when a Generator returns a value, you have to iterate over it like this:
    ```python
    try:
        while True:
            item = next(generator)
            ...
    except StopIteration as e:
        # Return value is "returned" as the value of the StopIteration
        result = e.value
    ```

    With the ReturnCapturingGenerator, you can do this instead:
    ```python
    generator = ReturnCapturingGenerator(original_generator)
    for item in generator:
        ...
    result = generator.return_value
    ```
    """

    def __init__(self, generator: Generator[IterT, None, ReturnT]):
        self._generator = generator
        self._done_iterating = False

    def __iter__(self) -> Generator[IterT, None, None]:
        # pyre-ignore[16]: we made _generator in __init__
        self._return_value = yield from self._generator
        self._done_iterating = True

    @property
    def return_value(self) -> ReturnT:
        assert self._done_iterating, "Cannot call return_value before the generator is exhausted"
        # pyre-ignore[16]: we made _return_value in __init__
        return self._return_value


class GeneratorDoneSentinel:
    pass


def _run_and_queue_generator(
    generator: Generator[IterT, None, ReturnT], output_queue: queue.Queue[IterT | GeneratorDoneSentinel]
) -> ReturnT:
    try:
        generator_with_capture = ReturnCapturingGenerator(generator)
        for item in generator_with_capture:
            output_queue.put(item)
        return generator_with_capture.return_value
    finally:
        output_queue.put(GeneratorDoneSentinel())


def multiplex_generators(
    generators: Iterable[Generator[IterT, None, ReturnT]],
    max_workers: int | None = None,
) -> Generator[IterT, None, tuple[ReturnT, ...]]:
    """
    Execute multiple generators in parallel, yielding their outputs as they become available.

    Uses a thread pool executor for parallelism.
    """
    return_values = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        output_queue: queue.Queue[IterT | GeneratorDoneSentinel] = queue.Queue()
        futures = [
            executor.submit(contextvars.copy_context().run, _run_and_queue_generator, gen, output_queue=output_queue)
            for gen in generators
        ]

        remaining_futures = len(futures)
        while remaining_futures > 0:
            item_or_done: IterT | GeneratorDoneSentinel = output_queue.get()
            if isinstance(item_or_done, GeneratorDoneSentinel):
                remaining_futures -= 1
            else:
                item: IterT = item_or_done
                yield item

        for future in futures:
            return_values.append(future.result())

    return tuple(return_values)
