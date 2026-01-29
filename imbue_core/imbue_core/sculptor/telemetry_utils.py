from typing import Any

from pydantic import Field

from imbue_core.sculptor.telemetry_constants import ConsentLevel


def _with_consent_level(
    level: ConsentLevel, default_factory: Any | None = None, default: Any | None = None, **kwargs: Any
) -> Any:
    """A Pydantic Field factory to annotate a field with a consent level.
    It attaches the level as metadata within the field's JSON schema extras.
    """
    if default_factory is not None:
        assert default is None, "Cannot specify both default and default_factory"
        # pyre-fixme[6]: pyre is confused by the dict literal here, especially since level is not a JsonValue
        return Field(default_factory=default_factory, json_schema_extra={"consent_level": level}, **kwargs)

    # pyre-fixme[6]: pyre is confused by the dict literal here, especially since level is not a JsonValue
    return Field(default, json_schema_extra={"consent_level": level}, **kwargs)


def with_consent(
    level: ConsentLevel, default_factory: Any | None = None, default: Any | None = None, **kwargs: Any
) -> Any:
    """A Pydantic Field factory to annotate a field with a consent level.
    It attaches the level as metadata within the field's JSON schema extras.
    """
    return _with_consent_level(level, default_factory=default_factory, default=default, **kwargs)


def without_consent(default: Any | None = None, default_factory: Any | None = None, **kwargs: Any) -> Any:
    """A Pydantic Field factory to annotate a field without a consent level."""
    return _with_consent_level(ConsentLevel.NONE, default_factory=default_factory, default=default, **kwargs)


def never_log(default: Any | None = None, default_factory: Any | None = None, **kwargs: Any) -> Any:
    """A Pydantic Field factory to annotate a field that should never be logged.
    This is used for in-memory or temporary data that should not be stored long-term.
    """
    return _with_consent_level(ConsentLevel.NEVER_PERSIST, default_factory=default_factory, default=default, **kwargs)
