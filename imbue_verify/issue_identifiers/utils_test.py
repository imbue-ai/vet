import contextvars
import threading
from typing import Generator

from imbue_verify.issue_identifiers.utils import multiplex_generators
from imbue_verify.issue_identifiers.utils import xml_post_escape


def test_xml_post_escape_does_not_escape_if_not_necessary() -> None:
    input_string = "<root><code_part>hello</code_part></root>"
    assert xml_post_escape(input_string, "code_part") == input_string


def test_xml_post_escape_properly_escapes_single_line() -> None:
    input_string = "<root><desc>Hey</desc><code_part>1 < 2</code_part></root>"
    assert xml_post_escape(input_string, "code_part") == "<root><desc>Hey</desc><code_part>1 &lt; 2</code_part></root>"


def test_xml_post_escape_properly_escapes_multi_line() -> None:
    input_string = """
    <root>
        <code_part>
            1 < 2
        </code_part>
    </root>
    """
    assert (
        xml_post_escape(input_string, "code_part")
        == """
    <root>
        <code_part>
            1 &lt; 2
        </code_part>
    </root>
    """
    )


def test_xml_post_escape_does_not_escape_if_not_asked_to() -> None:
    input_string = "<root><desc>Hey</desc><code_part>1 < 2</code_part></root>"
    assert xml_post_escape(input_string, "desc") == "<root><desc>Hey</desc><code_part>1 < 2</code_part></root>"


def test_xml_post_escape_does_not_change_case() -> None:
    input_string = "<root><desc>Hey</desc><code_part>1 < 2</CODE_PART></root>"
    assert xml_post_escape(input_string, "code_part") == "<root><desc>Hey</desc><code_part>1 &lt; 2</CODE_PART></root>"


def test_xml_post_escape_does_nothing_if_element_not_present() -> None:
    input_string = "<root><greeting>hello</greeting></root>"
    assert xml_post_escape(input_string, "code_part") == input_string


def _generator_with_barrier(value: int, count: int, barrier: threading.Barrier) -> Generator[int, None, int]:
    for i in range(count):
        barrier.wait(timeout=1.0)
        yield value + i
    return value * 100


def test_multiplex_generators_runs_in_parallel() -> None:
    barrier = threading.Barrier(2)

    gen1 = _generator_with_barrier(0, 3, barrier)
    gen2 = _generator_with_barrier(10, 3, barrier)

    multiplexed = multiplex_generators([gen1, gen2], max_workers=2)

    results = []
    for item in multiplexed:
        results.append(item)

    assert len(results) == 6
    assert set(results) == {0, 1, 2, 10, 11, 12}


def test_multiple_generators_transfers_contextvars() -> None:
    """Test that existing context variables are transferred to the generator threads."""
    var = contextvars.ContextVar("test_var", default=123)

    def _gen_with_contextvar() -> Generator[int, None, None]:
        yield var.get()

    gen = _gen_with_contextvar()

    multiplexed = multiplex_generators([gen])

    results = []
    for item in multiplexed:
        results.append(item)

    assert results == [123]
