from enum import StrEnum
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

ApiType = Literal["openai_compatible"]


class ModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str | None = None
    context_window: int
    max_output_tokens: int


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    api_type: ApiType = "openai_compatible"
    base_url: str
    api_key_env: str | None = None
    models: dict[str, ModelConfig] = Field(default_factory=dict)


class ModelsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    providers: dict[str, ProviderConfig] = Field(default_factory=dict)


class GuideMode(StrEnum):
    PREFIX = "prefix"
    SUFFIX = "suffix"
    REPLACE = "replace"


class CustomGuideConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: GuideMode
    guide: str


class CustomGuidesConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    guides: dict[str, CustomGuideConfig] = Field(default_factory=dict)
