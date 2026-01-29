from enum import Enum


class ConsentLevel(Enum):
    """Defines the hierarchy of user consent levels."""

    NONE = 0
    ERROR_REPORTING = 1  # PostHog and Sentry’s error reporting
    PRODUCT_ANALYTICS = 2  # PostHog’s pageview and autocapture events
    LLM_LOGS = 3  # Capability logging
    SESSION_RECORDING = 4  # PostHog and Sentry’s session recording

    NEVER_PERSIST = "never_persist"


class ProductComponent(Enum):
    AGENT_TASK = "agent_task"
    CHECKS = "checks"
    TASK = "task"
    ONBOARDING = "onboarding"
    STARTUP = "startup"
    ENVIRONMENT_SETUP = "environment_setup"
    FIX = "fix"
    CLAUDE_CODE = "claude_code"
    IMBUE_VERIFY = "imbue_verify"
    IMBUE_CLI = "imbue_cli"
    AUTH = "auth"
    DATABASE = "database"
    LOCAL_SYNC = "local_sync"
    MANUAL_SYNC = "manual_sync"
    # CROSS_COMPONENT is for logging concerns that are not local to a specific component.
    CROSS_COMPONENT = "cross_component"
    CONFIGURATION = "configuration"


class UserAction(Enum):
    CLICKED = "clicked"
    CALLED = "called"
    # more to be defined later


# Adding a new event? Please see _get_posthog_token_and_api_host for information about
# using the developer posthog instance as you build/test your event.
class SculptorPosthogEvent(Enum):
    """
    DO NOT MUTATE the string values!

    Mark as deprecated enums when no longer used.
    """

    # TESTING
    TEST_EVENT = "test_event"

    # ONBOARDING
    ONBOARDING_INITIALIZATION = "onboarding_initialization"
    ONBOARDING_CONFIGURATION_WIZARD = "onboarding_configuration_wizard"
    ONBOARDING_EMAIL_CONFIRMATION = "onboarding_email_confirmation"
    ONBOARDING_TELEMETRY_CONSENT = "onboarding_telemetry_consent"
    ONBOARDING_STARTUP_CHECKS = "onboarding_startup_checks"
    ONBOARDING_USER_CONFIG_SETTINGS = "onboarding_user_config_settings"  # Deprecated, use the following one:
    ONBOARDING_USER_CONFIG_SETTINGS_LOADED = "onboarding_user_config_settings_loaded"
    ONBOARDING_COMPLETED = "onboarding_completed"

    ONBOARDING_ANTHROPIC_API_KEY_SET = "onboarding_anthropic_api_key_set"
    ONBOARDING_ANTHROPIC_CREDENTIALS_EXIST = (
        "onboarding_anthropic_credentials_exist"  # This only means that oauth completed.
    )
    ONBOARDING_ANTHROPIC_OAUTH_STARTED = "onboarding_anthropic_oauth_started"
    ONBOARDING_ANTHROPIC_OAUTH_CANCELLED = "onboarding_anthropic_oauth_cancelled"
    ONBOARDING_ANTHROPIC_AUTHORIZED = (
        "onboarding_anthropic_authorized"  # We've successfully authorized, whether via Oauth or API key
    )
    ONBOARDING_OPENAI_AUTHORIZED = "onboarding_openai_authorized"
    ONBOARDING_DOCKER_INSTALLED = "onboarding_docker_installed"
    ONBOARDING_DOCKER_STARTED = "onboarding_docker_started"
    ONBOARDING_GIT_INSTALLED = "onboarding_git_installed"

    # STARTUP
    STARTUP_REMOTE_URL = "startup_remote_url"
    DESKTOP_BACKEND_STARTED = "desktop_backend_started"

    # Settings, configuration and preferences
    USER_CONFIG_SETTINGS_EDITED = "user_config_settings_edited"

    # TASK
    TASK_PREDICT_BRANCH_NAME = "task_predict_branch_name"
    TASK_START_MESSAGE = "task_start_message"
    TASK_START_REQUESTED = "task_start_requested"
    TASK_FORK_REQUESTED = "task_fork_requested"
    TASK_RUN_TASK_STARTED = "task_run_task_started"
    TASK_USER_MESSAGE = "task_user_message"
    TASK_USER_COMMAND = "task_user_command"
    TASK_USER_FEEDBACK = "task_user_feedback"

    # ENVIRONMENT SETUP
    ENVIRONMENT_SETUP_REUSED_EXISTING_ENVIRONMENT = "environment_setup_reused_existing_environment"
    ENVIRONMENT_SETUP_FAILED_TO_REUSE_EXISTING_ENVIRONMENT = "environment_setup_failed_to_reuse_existing_environment"
    ENVIRONMENT_SETUP_IMAGE_CREATION_STARTED = "environment_setup_image_creation_started"
    ENVIRONMENT_SETUP_USING_EXISTING_IMAGE = "environment_setup_using_existing_image"
    ENVIRONMENT_SETUP_IMAGE_CREATION_FINISHED = "environment_setup_image_creation_finished"
    ENVIRONMENT_SETUP_IMAGE_ENSURED = "environment_setup_image_ensured"
    ENVIRONMENT_SETUP_HARD_OVERWROTE_WORKSPACE = "environment_setup_hard_overwrote_workspace"
    ENVIRONMENT_SETUP_DOCKER_CONTROL_PLANE_ALREADY_DOWNLOADED = (
        "environment_setup_docker_control_plane_already_downloaded"
    )
    ENVIRONMENT_SETUP_DOCKER_CONTROL_PLANE_DOWNLOAD_FINISHED = (
        "environment_setup_docker_control_plane_download_finished"
    )
    ENVIRONMENT_SETUP_WAITING_FOR_CONTROL_PLANE_SETUP = "environment_setup_waiting_for_control_plane_setup"
    ENVIRONMENT_SETUP_DOCKER_STARTED_EXISTING_CONTAINER = "environment_setup_docker_started_existing_container"
    ENVIRONMENT_SETUP_DOCKER_CONTAINER_CREATED = "environment_setup_docker_container_created"
    ENVIRONMENT_SETUP_DOCKER_CONTAINER_FINISHED_SETUP = "environment_setup_docker_container_finished_setup"
    ENVIRONMENT_SETUP_REPO_ARCHIVE_CREATED = "environment_setup_repo_archive_created"
    ENVIRONMENT_SETUP_IMAGE_CREATED = "environment_setup_image_created"
    ENVIRONMENT_SETUP_LOCAL_DOCKERFILE_BUILT = "environment_setup_local_dockerfile_built"
    ENVIRONMENT_SETUP_FELL_BACK_TO_DEFAULT_DEVCONTAINER = "environment_setup_fell_back_to_default_devcontainer"
    ENVIRONMENT_SETUP_WRAPPER_DOCKERFILE_BUILT = "environment_setup_wrapper_dockerfile_built"

    # TOOL READINESS
    TOOL_READINESS_EVENT_COMPLETED = "tool_readiness_event_completed"

    # AGENT_TASK
    AGENT_TASK_ENVIRONMENT_SETUP_FINISHED = "agent_task_environment_setup_finished"
    AGENT_TASK_GIT_SETUP_FINALIZED = "agent_task_git_setup_finalized"
    AGENT_TASK_RUNNING_IN_ENVIRONMENT = "agent_task_running_in_environment"
    AGENT_TASK_RECEIVED_FIRST_TOKEN_FROM_AGENT = "agent_task_received_first_token_from_agent"

    # FIX
    FIX_ISSUE_SELECT = "fix_issue_select"

    # AGENT RESPONSES
    AGENT_INIT = "agent_init"
    AGENT_ASSISTANT_MESSAGE = "agent_assistant_message"
    AGENT_TOOL_RESULT = "agent_tool_result"
    AGENT_SESSION_END = "agent_session_end"

    # USER MESSAGES
    USER_CHAT_INPUT = "user_chat_input"
    USER_COMMAND_INPUT = "user_command_input"
    USER_WRITE_FILE = "user_write_file"
    USER_STOP_AGENT = "user_stop_agent"
    USER_INTERRUPT_PROCESS = "user_interrupt_process"
    USER_FORK_AGENT = "user_fork_agent"
    USER_REMOVE_QUEUED_MESSAGE = "user_remove_queued_message"
    USER_GIT_COMMIT_AND_PUSH = "user_git_commit_and_push"
    USER_GIT_PULL = "user_git_pull"
    USER_COMPACT_TASK_MESSAGE = "user_compact_task_message"
    USER_CONFIGURATION_DATA = "user_configuration_data"
    PROJECT_CONFIGURATION_DATA = "project_configuration_data"
    COMPACTION_SUCCESS = "compaction_success"

    # CHECKS
    CHECK_STARTED = "check_started"
    USER_STOP_CHECK_MESSAGE = "user_stop_check_message"
    USER_RESTART_CHECK_MESSAGE = "user_restart_check_message"

    # SYSTEM MESSAGES (eg Local * Manual Sync)
    LOCAL_SYNC_SETUP_STARTED = "local_sync_setup_started"
    LOCAL_SYNC_SETUP_AND_ENABLED = "local_sync_setup_and_enabled"
    LOCAL_SYNC_UPDATE_PENDING = "local_sync_update_pending"
    LOCAL_SYNC_UPDATE_COMPLETED = "local_sync_update_completed"
    LOCAL_SYNC_UPDATE_PAUSED = "local_sync_update_paused"
    LOCAL_SYNC_DISABLED = "local_sync_disabled"
    MANUAL_SYNC_MERGE_INTO_USER_ATTEMPTED = "manual_sync_merge_into_user_attempted"
    MANUAL_SYNC_MERGE_INTO_AGENT_ATTEMPTED = "manual_sync_merge_into_agent_attempted"
    RUNNER_RESUME_USER_MESSAGE = "runner_resume_user_message"
    WARNING_AGENT_MESSAGE = "warning_agent_message"

    # This is poorly named; it refers to starting a claude -p command in the environment
    # CLAUDE MESSAGES
    CLAUDE_COMMAND = "claude_command"

    # This is poorly named; it refers to starting a codex exec command in the environment
    # CODEX MESSAGES
    CODEX_COMMAND = "codex_command"

    # IMBUE VERIFY
    IMBUE_VERIFY_CALLED = "imbue_verify_called"
    TRIMMED_IMBUE_VERIFY_CALLED = "trimmed_imbue_verify_called"
    IMBUE_VERIFY_FAILED = "imbue_verify_failed"

    # IMBUE CLI
    IMBUE_CLI_START = "imbue_cli_start"
    IMBUE_CLI_CHECK_INITIATED = "imbue_cli_check_initiated"

    # LOGIN
    LOGIN_INITIATED = "login_initiated"
    LOGIN_SUCCEEDED = "login_succeeded"

    # DATABASE
    DB_WRITE = "db_write"

    # RUNTIME TRACKING
    RUNTIME_MEASUREMENT = "runtime_measurement"

    # SPACE USAGE TRACKING
    SNAPSHOT_SIZE_MEASUREMENT = "snapshot_size_measurement"
    IMAGE_INFORMATION = "image_information"

    # EXCEPTIONS
    # NOTE: if you're adding a new call to log_error_to_posthog, you should most likely add a new value here!
    # this is the only way that we determine where the error originated (unless you set include_traceback=True),
    # so we don't want to reuse these without a good reason
    IRRECOVERABLE_EXCEPTION = (
        "irrecoverable_exception"  # only use this if we have no other information on the error's source
    )
    SENTRY_EXCEPTION_DATA_COLLECTION_TOO_SLOW = "sentry_exception_data_collection_too_slow"
    CLAUDE_TRANSIENT_ERROR = "claude_transient_error"
    DATABASE_LOCK_ACQUISITION_TIMEOUT = "database_lock_acquisition_timeout"
    INCOMPATIBLE_DATABASE_LIKELY_FROM_DOWNGRADE = "incompatible_database_likely_from_downgrade"
    FAILED_TO_PARSE_LLM_RESPONSE_WHEN_GENERATING_ISSUES = "failed_to_parse_llm_response_when_generating_issues"
    INVALID_FILE_PATH_FROM_LLM_IN_ISSUE_LOCATION = "invalid_file_path_from_llm_in_issue_location"
    TASK_FAILED_WITH_EXPECTED_ERROR = "task_failed_with_expected_error"
    AGENT_RUNNER_FAILED_BECAUSE_DOCKER_IS_DOWN = "agent_runner_failed_because_docker_is_down"
    FAILED_TO_SNAPSHOT_IMAGE_DURING_SHUTDOWN = "failed_to_snapshot_image_during_shutdown"
    THREAD_IRRECOVERABLE_EXCEPTION = "thread_irrecoverable_exception"
