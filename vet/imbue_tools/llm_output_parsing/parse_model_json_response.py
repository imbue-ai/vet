import json
import re
from typing import TypeVar

from pydantic import ValidationError

from vet.imbue_core.async_monkey_patches import log_exception
from vet.imbue_core.pydantic_serialization import SerializableModel


def parse_json_block_from_response_text(response_text: str) -> str:
    """Clean markdown formatting and extra content from LLM response."""
    response_text = response_text.strip()
    # Parse content between first ```json and ``` block
    json_start_line = re.search(r"^.*?```json\s*", response_text, flags=re.MULTILINE)
    if json_start_line:
        response_text = response_text[json_start_line.end() :]
    json_end_line = re.search(r"```\s*$", response_text, flags=re.MULTILINE)
    if json_end_line:
        response_text = response_text[: json_end_line.start()]
    return response_text.strip()


ResponseSchema = TypeVar("ResponseSchema", bound=SerializableModel)


class ResponseParsingError(Exception):
    pass


def parse_model_json_response(response_text: str, result_type: type[ResponseSchema]) -> ResponseSchema:
    """Parse a JSON response from the LLM into a Pydantic model."""
    cleaned_response = parse_json_block_from_response_text(response_text)
    try:
        return result_type.model_validate_json(cleaned_response)
    except json.JSONDecodeError as e:
        log_exception(
            e,
            "Response is not valid JSON.\nraw_response: {response_text}\ncleaned_response: {cleaned_response}",
            response_text=response_text,
            cleaned_response=cleaned_response,
        )
        raise ResponseParsingError(str(e)) from e
    except ValidationError as e:
        log_exception(
            e,
            "Response does not match the expected schema.\nraw_response: {response_text}\ncleaned_response: {cleaned_response}",
            response_text=response_text,
            cleaned_response=cleaned_response,
        )
        raise ResponseParsingError(str(e)) from e
