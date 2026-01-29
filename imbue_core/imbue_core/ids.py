from typing import Any
from typing import Self

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema


class NonEmptyStr(str):
    # pyre-fixme[11]: pyre seems to have some trouble with Self in some specific cases, including type[Self]
    def __new__(cls: type[Self], *args: Any, **kwargs: Any) -> Self:
        value = str.__new__(cls, *args, **kwargs)
        if len(value) == 0:
            raise ValueError("NonEmptyStr cannot be empty")
        return value

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: type, handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        """
        Support transparently deserializing strings into ObjectID instances and vice versa.
        """
        return core_schema.no_info_before_validator_function(
            lambda raw_value: cls(raw_value) if isinstance(raw_value, str) else raw_value,
            core_schema.union_schema(
                [
                    core_schema.is_instance_schema(cls),
                    core_schema.str_schema(),
                ]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda instance: str(instance), return_schema=core_schema.str_schema()
            ),
        )


class ExternalID(NonEmptyStr):
    pass


class AssistantMessageID(ExternalID):
    pass


class ToolUseID(ExternalID):
    pass
