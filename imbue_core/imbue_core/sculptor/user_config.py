import sys
from enum import StrEnum
from typing import Any

from pydantic import Field
from pydantic.alias_generators import to_camel

from imbue_core.pydantic_serialization import SerializableModel
from imbue_core.sculptor.telemetry_constants import ConsentLevel
from imbue_core.sculptor.telemetry_utils import never_log
from imbue_core.sculptor.telemetry_utils import with_consent
from imbue_core.sculptor.telemetry_utils import without_consent

_DEFAULT_MODIFIER_KEY = "Cmd" if sys.platform == "darwin" else "Ctrl"


class UpdateChannel(StrEnum):
    """Update channel for receiving Sculptor updates."""

    STABLE = "STABLE"
    ALPHA = "ALPHA"


class PrivacySettings(SerializableModel):
    """This model contains a subset of the the privacy fields that we support."""

    is_error_reporting_enabled: bool = Field(False, description="Whether to enable error reporting, i.e. Sentry")
    is_product_analytics_enabled: bool = Field(
        False, description="Whether to enable product analytics, e.g. through PostHog"
    )
    is_llm_logs_enabled: bool = Field(False, description="Whether to enable LLM logs spooling to our systems")
    is_session_recording_enabled: bool = Field(False, description="Whether to enable session recording")
    is_repo_backup_enabled: bool = Field(False, description="Whether to enable repo backup")
    is_full_contribution: bool = Field(
        False,
        description="Synthetic field to let us know if the user has selected full contribution. This includes 'full LLM logs, including code' to train our agent.",
    )
    telemetry_consent_level: str = Field("", description="Telemetry level description")


class UserConfig(SerializableModel):
    """Most configuration for user and for Sculptor app behavior should go here.

    All required fields must be provided or validation will fail.

    When you add a new field, you should add it as a field with a default value so that it is backwards compatible.
    """

    user_email: str = without_consent(..., description="User email address")
    user_full_name: str | None = without_consent(None, description="Full name of the user")
    user_git_username: str = without_consent(..., description="Git User name")
    user_id: str = without_consent(..., description="User ID")
    anonymous_access_token: str = never_log(
        ..., description="Unique and local anonymous access token for imbue_gateway"
    )
    organization_id: str = without_consent(..., description="Organization ID")
    instance_id: str = without_consent(..., description="Instance ID")
    is_error_reporting_enabled: bool = without_consent(False, description="Whether to enable error reporting")
    is_product_analytics_enabled: bool = without_consent(False, description="Whether to enable product analytics")
    is_llm_logs_enabled: bool = without_consent(False, description="Whether to enable LLM logs")
    is_session_recording_enabled: bool = without_consent(False, description="Whether to enable session recording")
    is_repo_backup_enabled: bool = without_consent(False, description="Whether to enable repo backup")
    is_full_contribution: bool = without_consent(
        False,
        description="Synthetic field to let us know if the user has selected full contribution. This includes 'full LLM logs, including code' to train our agent.",
    )
    telemetry_consent_level: str = without_consent("", description="Telemetry level description")
    # For now, we give users the option to opt-out of syncing their Claude settings with Sculptor.
    is_claude_configuration_synchronized: bool = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=True,
        description="Whether user's local Claude Code configuration is synchronized with Sculptor.",
    )
    anthropic_api_key: str | None = never_log(None, description="Anthropic API key")
    openai_api_key: str | None = never_log(None, description="OpenAI API key")
    gemini_api_key: str | None = never_log(None, description="Gemini API key")
    is_privacy_policy_consented: bool = without_consent(
        False, description="Whether the user consented to our privacy policy"
    )
    is_telemetry_level_set: bool = without_consent(
        False, description="Whether the user consented to our telemetry level"
    )
    # App configuration:
    app_theme: str = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default="system",
        description="App theme: light, dark, or system",
    )
    does_send_message_shortcut_include_modifier: bool = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=True,
        description="True if the send message shortcut includes the modifier key. Eg. Cmd+Enter instead of Enter alone.)",
    )
    new_agent_shortcut: str = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=f"{_DEFAULT_MODIFIER_KEY}+N",
        description="Shortcut for creating a new agent",
    )
    search_agents_shortcut: str = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=f"{_DEFAULT_MODIFIER_KEY}+K",
        description="Shortcut for searching agents",
    )
    toggle_sidebar_shortcut: str = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=f"{_DEFAULT_MODIFIER_KEY}+S",
        description="Shortcut for toggling the sidebar",
    )
    global_hotkey: str = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default="",
        description="Global hotkey to open Sculptor",
    )
    default_llm: str | None = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=None,
        description="Default LLM model for new agents. If None, then most recently used LLM will be used.",
    )
    has_seen_pairing_mode_modal: bool = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=False,
        description="Whether the user has seen the pairing mode modal",
    )
    are_suggestions_enabled: bool = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=True,
        description="Whether to enable the suggestions feature",
    )
    imbue_verify_run_frequency: str = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default="auto",
        description="Frequency for running Imbue Verify: auto or manual",
    )
    imbue_verify_token_usage_requirement: str = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default="low",
        description="Token threshold for running Imbue Verify: none, low, medium, or high",
    )
    is_forking_beta_feature_on: bool = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=False,
        description="Whether to enable the forking beta feature",
    )
    is_pairing_mode_stashing_beta_feature_on: bool = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=False,
        description="Whether to enable the pairing mode stashing beta feature",
    )
    is_pairing_mode_warning_before_stash_enabled: bool = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=True,
        description="Whether to show a warning dialog before stashing changes when starting pairing mode",
    )
    are_dev_suggestions_on: bool = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=False,
        description="Whether to enable the dev suggestions pane",
    )
    is_scout_beta_feature_on: bool = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=False,
        description="Whether to enable the scout beta feature",
    )

    # NOTE: The electron frontend might read this value directly in configFallback.ts. Please remember to keep them in sync.
    update_channel: UpdateChannel = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=UpdateChannel.STABLE,
        description="Update channel for receiving Sculptor updates (stable or alpha)",
    )
    max_snapshot_size_bytes: int = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=50 * 1024 * 1024,
        description="Maximum snapshot size in bytes.",
    )
    min_free_disk_gb: float = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=2.0,
        description="The minimum free disk space before Sculptor will stop allowing new tasks and messages",
    )

    @property
    def is_imbue_user(self) -> bool:
        return self.user_email.endswith("@imbue.com")

    @property
    def free_disk_gb_warn_limit(self) -> float:
        return self.min_free_disk_gb * 3.0

    @property
    def privacy_settings(self) -> PrivacySettings:
        """Retrieves the subset of fields associated with Privacy Settings"""
        return PrivacySettings(
            is_error_reporting_enabled=self.is_error_reporting_enabled,
            is_product_analytics_enabled=self.is_product_analytics_enabled,
            is_llm_logs_enabled=self.is_llm_logs_enabled,
            is_session_recording_enabled=self.is_session_recording_enabled,
            is_repo_backup_enabled=self.is_repo_backup_enabled,
            is_full_contribution=self.is_full_contribution,
            telemetry_consent_level=self.telemetry_consent_level,
        )

    @property
    def sentry_user_context(self) -> dict[str, str]:
        """Returns a dictionary of user context information for Sentry error reporting."""
        return {
            "id": self.user_id,  # this is conveniently the same id as used by posthog client
            "email": self.user_email,
            "username": self.user_email,  # traditionally what we have been setting as username
        }


# At Runtime, ensure that all fields in PrivacySettings are also in UserConfig
for field in PrivacySettings.model_fields:
    assert field in UserConfig.model_fields, f"PrivacySettings field {field} is missing from UserConfig"


def _generate_user_config_field_enum() -> type[StrEnum]:
    """Generate UserConfigField enum from UserConfig model fields"""
    fields = {}
    for field_name in UserConfig.model_fields.keys():
        # Convert field name to SCREAMING_SNAKE_CASE for enum constant
        enum_name = field_name.upper()
        fields[enum_name] = to_camel(field_name)
    # pyre thinks this is an instance of a StrEnum because it doesn't understand enums
    return StrEnum("UserConfigField", fields)  # pyre-ignore[7, 19]


UserConfigField: type[StrEnum] = _generate_user_config_field_enum()


def calculate_user_config_prior_values(
    old_config: UserConfig, new_config: UserConfig, privacy_settings: PrivacySettings
) -> dict[str, Any]:
    from imbue_core.sculptor.telemetry import is_consent_allowable

    old_dict = old_config.model_dump()
    new_dict = new_config.model_dump()
    prior_values: dict[str, Any] = {}

    for field_name in old_dict:
        if old_dict[field_name] != new_dict[field_name]:
            field_info = UserConfig.model_fields.get(field_name)
            if field_info:
                metadata = field_info.json_schema_extra or {}
                required_level = metadata.get("consent_level")
                if is_consent_allowable(required_level, privacy_settings):
                    prior_values[field_name] = old_dict[field_name]
                else:
                    prior_values[field_name] = None

    return prior_values
