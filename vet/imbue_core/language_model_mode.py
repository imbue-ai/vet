from enum import StrEnum


class LanguageModelMode(StrEnum):
    LIVE = "LIVE"
    UPDATE_SNAPSHOT = "UPDATE_SNAPSHOT"
    OFFLINE = "OFFLINE"
    MOCKED = "MOCKED"
