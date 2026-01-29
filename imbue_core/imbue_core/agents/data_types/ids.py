from abc import ABC

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema
from typeid import TypeID
from typeid import get_prefix_and_suffix


class TypeIDPrefixMismatchError(Exception):
    pass


class ObjectID(TypeID, ABC):
    """
    A convenience class for string-based object IDs.

    Use in place of strings for IDs. (We don't use raw UUIDs because they are not supported by SQLite.)

    Use `tag` to prefix the ID with the ID type. (We don't use `prefix` because it's already taken by the ancestor class.)

    """

    # Override this in subclasses to specify the ID type.
    tag: str = "oid"

    def __init__(self, value: str | None = None) -> None:
        if value is not None:
            prefix, suffix = get_prefix_and_suffix(value)
            # For convenience, don't require the caller to strip the prefix from existing IDs.
            if prefix is not None:
                if prefix != self.tag:
                    raise TypeIDPrefixMismatchError(f"Expected prefix '{self.tag}', got '{prefix}'")
                value = suffix
        super().__init__(self.tag, value)

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


class TaskID(ObjectID):
    tag: str = "tsk"


class ProjectID(ObjectID):
    tag: str = "prj"


class AgentMessageID(ObjectID):
    tag: str = "agm"
