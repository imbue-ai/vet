"""This module exposes an interface for instrumenting telemetry in Sculptor. It's implemented in Imbue Core so that it
may be re-used between both Sculptor and Imbue CLI.

To use this module well, you MUST:

* call either init_posthog or init_anonymous_posthog on application or lifetime startup.
* Make sure to call shutdown_posthog() on application close.

* emit_posthog_event() is a low-level library function to send an event to PostHog. If you are a product developer on
  Sculptor, you should probably use fire_posthog_event instead.

Similary you can call

* init_sentry()
* and MUST call flush_sentry_and_exit_program()

For some reason, flush_sentry_and_exit_program() also shuts down posthog. We will figure this out.
"""

import os
import traceback
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Generator
from typing import Generic
from typing import Mapping
from typing import Optional
from typing import Protocol
from typing import TypeVar
from typing import cast
from typing import runtime_checkable

import sentry_sdk
from loguru import logger
from posthog import Posthog
from posthog.scopes import identify_context
from posthog.scopes import new_context
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from pydantic import create_model
from pydantic.fields import FieldInfo
from sentry_sdk.types import Event
from sentry_sdk.types import Hint

from imbue_core.agents.data_types.ids import TaskID
from imbue_core.async_monkey_patches import inject_exception_and_log
from imbue_core.async_monkey_patches import log_exception
from imbue_core.async_monkey_patches import pre_filter_exception
from imbue_core.common import is_running_within_a_pytest_tree
from imbue_core.constants import ExceptionPriority
from imbue_core.pydantic_serialization import SerializableModel
from imbue_core.pydantic_utils import model_update
from imbue_core.sculptor.telemetry_constants import ConsentLevel
from imbue_core.sculptor.telemetry_constants import ProductComponent
from imbue_core.sculptor.telemetry_constants import SculptorPosthogEvent
from imbue_core.sculptor.telemetry_constants import UserAction
from imbue_core.sculptor.telemetry_utils import with_consent
from imbue_core.sculptor.telemetry_utils import without_consent
from imbue_core.sculptor.user_config import PrivacySettings
from imbue_core.sculptor.user_config import UserConfig

# This file is written into the state directory by the Sculptor server inside the task container
# to provide it with the telemetry info for the task.
TELEMETRY_TASK_INFO_JSON_STATE_FILE = "telemetry_task_info.json"


class TelemetryInfo(SerializableModel):
    """Information needed for setting up telemetry.

    This data structure is generated once in the Sculptor server,
    and gets propagated elsewhere (such as to Imbue CLI).
    """

    # Putting the User Config into this object is a smell. The UserConfig can and will change idependently of this
    # model, and that can lead to all sorts of issues. Consider refactoring this code.
    user_config: UserConfig
    sculptor_version: str
    sculptor_git_sha: str
    sculptor_execution_instance_id: str
    posthog_token: str
    posthog_api_host: str
    sentry_dsn: str


class TelemetryProjectInfo(SerializableModel):
    """Used to communicate project-level information tasks inside containers."""

    telemetry_info: TelemetryInfo
    project_id: str

    # Does not contain a token -- that should come through the environment.
    gitlab_mirror_repo_url: str | None
    original_git_repo_url: str | None


class TelemetryTaskInfo(SerializableModel):
    """Used to communicate task-level information tasks inside containers."""

    telemetry_project_info: TelemetryProjectInfo
    task_id: TaskID


class PosthogEventPayload(SerializableModel):
    """A base model for PostHog events that validates the presence of
    'consent_level' metadata on each field.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)  # pyre-fixme[6]: pyre can't type check this untyped dict

        # Run validation after subclass is defined
        cls._validate_class()

    @classmethod
    def _validate_class(cls) -> None:
        """
        Checks that every field has a 'consent_level' in its JSON schema metadata.
        Issues a UserWarning if the metadata is missing.
        """
        for field_name in cls.__annotations__.keys():
            field_info = cls.__dict__[field_name]
            # Check that we're using pydantic.Field
            assert isinstance(field_info, FieldInfo), "Field {} does not extend pydantic.Field".format(field_name)
            # Get the extra schema info, defaulting to an empty dict if it's None
            extra_schema: dict[str, Any] = {}
            match field_info.json_schema_extra:
                # If it's a callable we can call it to get the FieldInfo
                case None:
                    pass
                case dict() as d:
                    extra_schema = d
                case func if callable(func):
                    maybe_extra_schema = func({})
                    # TODO: func is supposed to be -> None, so the following should in theory never happen...
                    if maybe_extra_schema is not None:
                        extra_schema = cast(dict[str, Any], maybe_extra_schema)
                case _:
                    pass

            assert (
                "consent_level" in extra_schema
            ), """Field '{}' in '{}' is missing the
'consent_level' metadata. Please use the decorator
with_consent or without_consent to populate the field annotation:
`json_schema_extra={{'consent_level': ...}}`""".format(
                field_name, cls.__name__
            )


# All data models sent to PostHog MUST define consent annotations and subclass PosthogEventPayload.
T = TypeVar("T", bound=PosthogEventPayload)


# Potentially we could have a ratchet test to remind folks to use
# consent decorators.
class PosthogEventModel(SerializableModel, Generic[T]):
    """
    Represents a PostHog event, with each field tagged
    with the minimum consent level required for logging.
    """

    # Always defined fields
    name: SculptorPosthogEvent = without_consent(description="Name of event, give it meaning!")
    component: ProductComponent = without_consent(description="App component")

    # User Activity field
    action: UserAction | None = with_consent(ConsentLevel.PRODUCT_ANALYTICS)

    # Task ID - should be set if this event is associated with a task.
    task_id: str | None = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        description="The task id if this event is task-specific",
    )

    # Payload field with consent level
    payload: T | None = without_consent(description="PostHog Event payload Model")


def _create_posthog_event_payload_event_data_class(
    additional_field_definitions: Mapping[str, Any] | None = None,
) -> type[PosthogEventPayload]:
    """Generates a subclass of PosthogEventPayload with the type annotations and consent declarations set up.

    The PosthogEventPayload type can very based on the Event, so we are going to provide a mechanism to call this for
    any Posthog Event that needs it.
    """
    field_definitions = {}

    additional_field_definitions = additional_field_definitions or {}

    for field_name, field_info in UserConfig.model_fields.items():
        field_type = field_info.annotation | None if field_info.annotation else None
        field_definitions[field_name] = (field_type, field_info)

    for field_name, field_tuple in additional_field_definitions.items():
        field_definitions[field_name] = field_tuple

    field_definitions["sculptor_version"] = (Optional[str], without_consent())

    return create_model(
        "TelemetryInfoEventData",
        __base__=PosthogEventPayload,
        **field_definitions,
    )


# When we don't know what kind of Payload to use, we use this, which is the bare minimum TelemetryInfo data.
TelemetryInfoEventData: type[PosthogEventPayload] = _create_posthog_event_payload_event_data_class()


# For every Event, we define additional fields that it might have.
# NOTE: This will need to be refactored into a proper covariant pattern, but this works for now.
SCULPTOR_POSTHOG_EVENT_TO_PAYLOAD_TYPE = defaultdict(
    lambda: TelemetryInfoEventData,
    {
        SculptorPosthogEvent.ONBOARDING_EMAIL_CONFIRMATION: _create_posthog_event_payload_event_data_class(
            {"did_opt_in_to_marketing": (Optional[bool], without_consent())}
        )
    },
)


def make_telemetry_event_data(telemetry_info: TelemetryInfo) -> PosthogEventPayload:
    user_config_data = telemetry_info.user_config.model_dump()
    return TelemetryInfoEventData(**user_config_data)


@runtime_checkable
class PosthogProtocol(Protocol):
    """
    A protocol satisfied by the Posthog client class and a stub implementation.
    """

    host: str

    def capture(
        self,
        distinct_id=None,
        event=None,
        properties=None,
        timestamp=None,
        uuid=None,
        groups=None,
        send_feature_flags=False,
        disable_geoip=None,
    ) -> None:
        """
        Capture a telemetry event.
        """

    def identify(self, identifier, properties=None) -> None:
        """
        Identifies a user.
        """

    def alias(
        self,
        previous_id=None,
        distinct_id=None,
        context=None,
        timestamp=None,
        uuid=None,
        disable_geoip=None,
    ) -> None:
        """
        Links two users together, distinct_id -(maps)-> previous_id
        """

    def shutdown(self) -> None:
        """
        Flush all messages and cleanly shut down the client.
        """

    def capture_exception(self, exception: BaseException, distinct_id=None, properties=None) -> None:
        """Capture an exception event."""


# TODO: Should this inherit from PosthogProtocol?
class StubPosthog:
    host: str = "stub"

    def capture(
        self,
        distinct_id=None,
        event=None,
        properties=None,
        timestamp=None,
        uuid=None,
        groups=None,
        send_feature_flags=False,
        disable_geoip=None,
    ) -> None:
        # Do nothing for now.
        #
        # If we want to test calls to posthog.capture later,
        # we can augment this method to save the arguments internally.
        pass

    def identify(self, identifier, properties=None) -> None:
        pass

    def alias(
        self,
        previous_id=None,
        distinct_id=None,
        context=None,
        timestamp=None,
        uuid=None,
        disable_geoip=None,
    ) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def capture_exception(self, exception: BaseException, distinct_id=None, properties=None) -> None:
        pass


class PosthogUserInstance(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    posthog_instance: PosthogProtocol
    is_anonymous: bool

    # Every PosthogUserInstance needs to access the UserConfig, this is a function which returns that.
    user_config_accessor: Callable[[], UserConfig]

    def access_user_config(self) -> UserConfig:
        return self.user_config_accessor()


class AnonymousPosthogUserInstance(PosthogUserInstance):
    """This specific case is used to store a user when they happen to be initted."""

    initial_user_id: str


# This private in-memory cached value is set or updated whenever we
# * begin with an anonymous user (init_posthog)
# * begin with an identified user (init_anonymous_posthog)
# * convert an identified user into an anonymous user (identify_user)
_POSTHOG_USER_INSTANCE: PosthogUserInstance | AnonymousPosthogUserInstance | None = None


def is_posthog_identified() -> bool:
    return _POSTHOG_USER_INSTANCE is not None and not _POSTHOG_USER_INSTANCE.is_anonymous


# This used to be cached, but we wanted the user to be able to change telemetry preferences within a container.
def _get_telemetry_task_info_if_inside_container() -> TelemetryTaskInfo | None:
    """Mock this for testing.

    It is arranged thus because `get_telemetry_task_info_if_inside_container` is imported in many places,
    and to mock, monkeypatch would need to replace definitions at those locations.

    With this, monkeypatch only needs to replace this function."""
    telemetry_info_path = Path("/imbue_addons/state") / TELEMETRY_TASK_INFO_JSON_STATE_FILE
    if telemetry_info_path.exists():
        try:
            telemetry_task_info = TelemetryTaskInfo.model_validate_json(telemetry_info_path.read_text())
            return telemetry_task_info
        except ValidationError as e:
            log_exception(
                e,
                "Telemetry info file {telemetry_info_path} invalid, not initializing Posthog.",
                telemetry_info_path=telemetry_info_path,
            )
    return None


def get_telemetry_task_info_if_inside_container() -> TelemetryTaskInfo | None:
    """Loads the telemetry task info from the expected location in the container.
    This is a no-op if the file doesn't exist."""
    return _get_telemetry_task_info_if_inside_container()


# TODO (CAP-636): Remove upstream git repo logic once GitLab mirroring is completed.
def get_original_git_repo_url_if_inside_container() -> str | None:
    telemetry_task_info = get_telemetry_task_info_if_inside_container()
    if telemetry_task_info and telemetry_task_info.telemetry_project_info.original_git_repo_url:
        return telemetry_task_info.telemetry_project_info.original_git_repo_url
    return None


def init_posthog(
    info: TelemetryInfo,
    source: str,
    user_config_accessor: Callable[[], UserConfig] | None = None,
    is_anonymous: bool = False,
) -> None:
    """Initialize Posthog for a _known_ user.

    After this function is called,
       get_user_posthog_instance and posthog_context can be used.

    This function lives here so that the Sculptor backend and Imbue CLI can initialize PostHog in the same way.

    Args:
        user_config_accessor: Primarily exists to provide the PosthogUser instance a way to get the _latest_ user config at any time.
    """
    global _POSTHOG_USER_INSTANCE
    if _POSTHOG_USER_INSTANCE is not None:
        raise RuntimeError("Posthog endpoint already initialized.")

    posthog: Posthog | StubPosthog

    # TODO: Try to remove this test-specific code if possible.
    if is_running_within_a_pytest_tree():
        posthog = StubPosthog()
    else:
        posthog = Posthog(
            info.posthog_token,
            host=info.posthog_api_host,
            super_properties={
                "source": source,
                "sculptor_version": info.sculptor_version,
                "session": {
                    # In theory we should go through the accessor here,
                    # but at init time, when the user start the first time,
                    # they should be the same.
                    "instance_id": info.user_config.instance_id,
                    "execution_instance_id": info.sculptor_execution_instance_id,
                },
            },
        )
        if not is_anonymous:
            posthog.identify(
                info.user_config.user_id,
                {"email": info.user_config.user_email},
            )

    if is_anonymous:
        _POSTHOG_USER_INSTANCE = AnonymousPosthogUserInstance(
            posthog_instance=posthog,  # pyre-fixme[6]: pyre seems confused by PosthogProtocol
            is_anonymous=True,
            initial_user_id=info.user_config.user_id,
            user_config_accessor=user_config_accessor or (lambda: info.user_config),
        )
    else:
        _POSTHOG_USER_INSTANCE = PosthogUserInstance(
            posthog_instance=posthog,  # pyre-fixme[6]: pyre seems confused by PosthogProtocol
            is_anonymous=False,
            user_config_accessor=user_config_accessor or (lambda: info.user_config),
        )


def identify_posthog_user(user_config_accessor: Callable[[], UserConfig]) -> None:
    """Update the initialized PostHog instance with user identity.

    At this point, the previous posthog instance should be an anonymous PostHog instance.
    This means logs emitted prior to this call will create a new person entry and not
    populate `person.properties.email` field.

    We will use PostHog client's alias function to associate two unique ids together to
    the same person entry.
    """
    global _POSTHOG_USER_INSTANCE
    if _POSTHOG_USER_INSTANCE is None:
        logger.error("Posthog endpoint not initialized")
        return
    if not _POSTHOG_USER_INSTANCE.is_anonymous:
        logger.error("Posthog endpoint already identified with user")
        return

    if not isinstance(_POSTHOG_USER_INSTANCE, AnonymousPosthogUserInstance):
        raise RuntimeError("Anonymous PosthogUser instance expected")

    # At this point, the previous DataModel holds the anonymous instance id generated.
    initial_user_id = _POSTHOG_USER_INSTANCE.initial_user_id

    # We can preserve the previously running posthog instance.
    posthog = _POSTHOG_USER_INSTANCE.posthog_instance

    _POSTHOG_USER_INSTANCE = PosthogUserInstance(
        posthog_instance=posthog,
        is_anonymous=False,
        user_config_accessor=user_config_accessor,
    )

    latest_user_config = _POSTHOG_USER_INSTANCE.access_user_config()

    # Identify should only be called once per instance lifetime.
    posthog.identify(
        initial_user_id,
        {"email": latest_user_config.user_email},
    )
    posthog.alias(previous_id=latest_user_config.user_id, distinct_id=initial_user_id)

    logger.info(
        "Associating identified user {} with current instance initial user {}",
        latest_user_config.user_id,
        initial_user_id,
    )


def get_user_posthog_instance() -> PosthogUserInstance | None:
    """Returns the global PostHog client or None if it has not been configured"""
    return _POSTHOG_USER_INSTANCE


@contextmanager
def posthog_context(
    posthog_user_instance: PosthogUserInstance | None = None,
) -> Generator[PosthogProtocol, None, None]:
    """A context manager that creates a PostHog context with the appropriate user ID.

    Must be called after init_posthog or with a passed in posthog_user_instance.

    TODO: Can we delete this in favor of emit_posthog_event?  If not, explain here when to use this.
    TODO: Do we actually need to yield the PosthogProtocol?
    """
    posthog_user_instance = posthog_user_instance or _POSTHOG_USER_INSTANCE
    assert posthog_user_instance is not None
    with new_context():
        # Not having a distinct ID is troublesome...
        current_user_id = posthog_user_instance.access_user_config().user_id
        identify_context(current_user_id)
        try:
            yield posthog_user_instance.posthog_instance
        except Exception as e:
            log_exception(e, "Error in logging to posthog")


def is_consent_allowable(required_consent: ConsentLevel | None, privacy_settings: PrivacySettings) -> bool:
    """Check the appropriate value of user consent fields to establish allowable consent."""
    if required_consent is None:
        return True
    elif required_consent == ConsentLevel.NONE:
        return True
    elif required_consent == ConsentLevel.ERROR_REPORTING:
        return privacy_settings.is_error_reporting_enabled
    elif required_consent == ConsentLevel.PRODUCT_ANALYTICS:
        return privacy_settings.is_product_analytics_enabled
    elif required_consent == ConsentLevel.LLM_LOGS:
        return privacy_settings.is_llm_logs_enabled
    elif required_consent == ConsentLevel.SESSION_RECORDING:
        return privacy_settings.is_session_recording_enabled
    elif required_consent == ConsentLevel.NEVER_PERSIST:
        return False
    else:
        logger.info("Unexpected consent level: {}", required_consent)
        return False


def filter_model_by_consent(model: SerializableModel, privacy_settings: PrivacySettings) -> SerializableModel:
    """Recursively filter a SerializableModel based on consent toggles.

    Args:
        model: The model to filter
        user_config: The user's configuration with consent toggles

    Returns:
        SerializableModel with None for fields that don't meet the consent requirements.
        Tries to handle ValidationError gracefully by creating compatible models.
    """
    updates: dict[str, SerializableModel | list[SerializableModel] | None] = {}

    for field_name, field_info in model.__class__.model_fields.items():
        field_value = getattr(model, field_name)

        # Retrieve the metadata we attached using the decorator
        metadata = field_info.json_schema_extra or {}
        required_level = metadata.get("consent_level")

        # A field without a consent level is considered public OR
        # Include the field if the user's consent level is sufficient
        if is_consent_allowable(required_level, privacy_settings):
            # If the field value is also a SerializableModel, recursively filter it
            if isinstance(field_value, SerializableModel):
                updates[field_name] = filter_model_by_consent(field_value, privacy_settings)
            elif isinstance(field_value, list):
                filtered_list = []
                for item in field_value:
                    if isinstance(item, SerializableModel):
                        filtered_list.append(filter_model_by_consent(item, privacy_settings))
                    else:
                        filtered_list.append(item)
                updates[field_name] = filtered_list
            else:
                updates[field_name] = field_value
        else:
            # Set field to None if consent is not allowable
            updates[field_name] = None

    try:
        # Try the standard approach first
        return model_update(model, updates)
    except ValidationError:
        # If validation fails due to non-optional fields being set to None,
        # create a new model where those fields are Optional

        field_definitions: dict[str, tuple[type[Any] | None, FieldInfo | None]] = {}
        for field_name, field_info in model.__class__.model_fields.items():
            if field_name in updates and updates[field_name] is None:
                # Make this field Optional since we're setting it to None, preserving metadata
                field_definitions[field_name] = (
                    field_info.annotation | None,
                    Field(default=None, json_schema_extra=field_info.json_schema_extra),
                )
            else:
                # Keep original field definition
                field_definitions[field_name] = (field_info.annotation, field_info)

        # Create a new model class with filtered fields made Optional
        base_class = (
            model.__class__
            if hasattr(model.__class__, "__bases__") and model.__class__.__bases__
            else SerializableModel
        )
        filtered_model_class = create_model(
            f"{model.__class__.__name__}Filtered",
            __base__=base_class,
            **field_definitions,  # pyre-ignore[6]: pyre can't check this since it's an untyped dict
        )
        return filtered_model_class(**updates)  # pyre-ignore[6]: pyre can't check this since it's an untyped dict


def emit_posthog_event(posthog_event: PosthogEventModel[Any]) -> None:
    """Filters properties from a Pydantic model instance based on the user's given consent level.

    This can be called both from inside the imblue-cli task container, or the Sculptor backend.
    If invoked from inside the imbue-cli task container, task_id is added to the event_data by calling
    get_telemetry_task_info_when_inside_container().

    If you are in the Sculptor backend, you should probably use fire_posthog_event instead, as that ensures you're using
    a known event, and attaches correct context.
    """
    posthog_user_instance = get_user_posthog_instance()

    if posthog_user_instance:
        user_config_instance = posthog_user_instance.access_user_config()
        privacy_settings = user_config_instance.privacy_settings

        with posthog_context(posthog_user_instance):
            if not is_consent_allowable(ConsentLevel.NONE, privacy_settings):
                # User did not opt-into any data collection.
                # We should not log user-identifiable PostHog events.
                return
            elif posthog_event.action is not None and not is_consent_allowable(
                ConsentLevel.PRODUCT_ANALYTICS, privacy_settings
            ):
                # If this is a user_activity event but user has not consented
                # to product analytics logging level, do not emit event.
                return
            event_name = posthog_event.name.value

            # Use the recursive filtering function
            try:
                filtered_model = filter_model_by_consent(posthog_event, privacy_settings)
                properties = filtered_model.model_dump()
            except Exception as e:
                logger.info("Failed to filter posthog event: {}", e)
                # We could also choose to drop the entire event, or replace payload with an error message.
                properties = posthog_event.model_dump()

            # some events don't have a payload, but they should still be logged.
            if properties.get("payload"):
                payload = properties["payload"]
                if not any(value is not None for value in payload.values()):
                    logger.debug("No payload data to log for event of type {}", event_name)
                    return

            # Check for task-specific telemetry info and add it to the properties
            telemetry_task_info = get_telemetry_task_info_if_inside_container()
            if telemetry_task_info:
                # I think we will further change where we put this.
                properties["task_id"] = str(telemetry_task_info.task_id)

            posthog_user_instance.posthog_instance.capture(event=event_name, properties=properties)


def shutdown_posthog() -> None:
    """Flush all messages and cleanly shut down the client."""
    posthog_instance = get_user_posthog_instance()
    if posthog_instance is not None:
        posthog_instance.posthog_instance.shutdown()


class PosthogExceptionPayload(PosthogEventPayload):
    exception_name: str = with_consent(ConsentLevel.ERROR_REPORTING, description="The name of the raised exception.")
    exception_value: str = with_consent(ConsentLevel.ERROR_REPORTING, description="The value of the raised exception.")
    exception_traceback: str | None = with_consent(
        ConsentLevel.ERROR_REPORTING,
        description="Formatted traceback of the raised exception.",
    )
    message: str | None = with_consent(
        ConsentLevel.ERROR_REPORTING,
        description="The message that accompanies the raised exception.",
    )


def get_exception_payload(
    exception: BaseException,
    message: str | None = None,
    include_traceback: bool = False,
) -> PosthogExceptionPayload:
    formatted_traceback = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
    return PosthogExceptionPayload(
        exception_name=type(exception).__name__,
        exception_value=str(exception),
        exception_traceback=formatted_traceback if include_traceback else None,
        message=message,
    )


def send_exception_to_posthog(
    error_source: SculptorPosthogEvent,
    exception: BaseException,
    message: str | None = None,
    include_traceback: bool = False,
    component: ProductComponent = ProductComponent.CROSS_COMPONENT,
    task_id: TaskID | None = None,
) -> None:
    """Sends error details to PostHog for telemetry purposes.

    The idea is that for some exceptions, we don't want to send them to Sentry because we're not able to act on them anyway.
    But we should still keep an eye on how often they happen so we send them to PostHog instead.
    """

    # TODO: do we want to include this filtering even if we're sending it to posthog rather than sentry?
    should_skip = pre_filter_exception(exception, message)
    if should_skip:
        return

    emit_posthog_event(
        PosthogEventModel(
            name=error_source,
            component=component,
            payload=get_exception_payload(exception, message, include_traceback),
            task_id=str(task_id) if task_id else None,
        )
    )

    inject_exception_and_log(exception, message or "", priority=ExceptionPriority.LOW_PRIORITY)


def flush_sentry_and_exit_program(exit_code: int, final_message: str) -> None:
    """Flush Sentry events and then immediately exit the program with a final message.

    We enforce the final message so that the last line that the user sees is relevant to the shutdown.
    """
    sentry_sdk.flush()
    shutdown_posthog()
    logger.info(final_message)
    os._exit(exit_code)


def mirror_exception_to_posthog(event: Event, hint: Hint) -> Event:
    """Helper/utility function to mirror an exception from Sentry to PostHog.

    When this is wired up to the before_send hook in Sentry, it will send a correctly-shaped event to PostHog, and annotate the Sentry event with the PostHog user id.
    """
    # Only mirror error events
    if event.get("level") in ("warning", "error", "fatal") and hint and hint.get("exc_info"):
        logger.info("We are going to mirror this exception to posthog")
        _, exc_value, _ = hint["exc_info"]
        # Attach useful Sentry context as PostHog properties
        props = {
            "$exception_level": event.get("level"),
            "sentry_event_id": event.get("event_id"),
            "sentry_issue_id": event.get("contexts", {}).get("trace", {}).get("trace_id"),
            "tags": event.get("tags"),
            "release": event.get("release"),
            "environment": event.get("environment"),
            "log_message": event.get("logentry", {}).get("message"),
        }

        user_posthog_instance = get_user_posthog_instance()
        if user_posthog_instance:
            user_config = user_posthog_instance.access_user_config()
            try:
                user_posthog_instance.posthog_instance.capture_exception(
                    exc_value,
                    # We're relying on the fact that we are in a single-user context to always have a distinct_id.
                    distinct_id=user_config.user_id,
                    properties=props,
                )

                event.setdefault("tags", {})
                assert "tags" in event, "Only to shut up typechecker below"

                event["tags"]["posthog_exception_mirrored"] = "true"

                event.setdefault("extra", {})
                assert "extra" in event, "Only to shut up typechecker below"

                event["extra"]["posthog_user_id"] = (user_config.user_id,)

                posthog_app_domain = user_posthog_instance.posthog_instance.host.replace(
                    ".i.posthog.com", ".posthog.com"
                )

                event["extra"]["posthog_user_link"] = f"{posthog_app_domain}/persons/{user_config.user_id}"

            except Exception as e:
                # We don't want to trigger an infinite loop of exceptions if PostHog is down. We're sending a message to
                # Sentry after all.
                logger.debug("Failed to mirror exception to PostHog: {}", e)
            finally:
                # We must return the event in all code paths to ensure sentry continues.
                return event

    # We must return the event in all code paths to ensure sentry continues.
    return event
