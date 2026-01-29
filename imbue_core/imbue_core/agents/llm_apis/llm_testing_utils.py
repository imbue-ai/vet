from google.genai.types import CountTokensResponse
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.single_file import SingleFileAmberSnapshotExtension
from syrupy.extensions.single_file import SingleFileSnapshotExtension

from imbue_core.agents.llm_apis.data_types import CachedCostedModelResponse
from imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from imbue_core.caching import AsyncCache
from imbue_core.frozen_utils import FrozenMapping


async def check_llm_responses_in_cache(snapshot: SnapshotAssertion, temp_cache: AsyncCache, suffix: str = "") -> None:
    """Runs as the test fixture completes to check that the LLM inputs and outputs stay the same, in a human-readable format."""

    async with temp_cache as cache:
        all_keys: tuple[str, ...] = await cache.get_all_keys()  # Contains both the streaming and non-streaming keys?
        value_by_key: FrozenMapping[str, CachedCostedModelResponse | None] = await cache.get_all(all_keys)

    cache_items: list[tuple[str, CachedCostedModelResponse]] = [
        (k, v) for k, v in value_by_key.items() if v is not None
    ]
    cache_items.sort(key=lambda x: x[1].timestamp)
    for cache_index, (cache_key, cached_response) in enumerate(cache_items):
        prompt: bytes = b""
        joined_responses: bytes = b""
        metadata_lines: list[str] = []

        metadata_lines.append(f"{cache_index=} (when cache is sorted by timestamp)")
        metadata_lines.append(f"{cache_key=}")  # Keys must be stable and not too big.
        if cached_response.inputs is not None:
            prompt = cached_response.inputs.prompt.encode("utf-8")
            metadata_lines.append(f"request metdata ({type(cached_response.inputs)})")
            for field, field_value in cached_response.inputs.__dict__.items():
                if field != "prompt":  # print the prompt separately below.
                    metadata_lines.append(f"    {field}: {field_value}")

        metadata_lines.append("cached_response metadata:")
        for field, field_value in cached_response.__dict__.items():
            if field not in ("inputs", "response"):  # already printed above
                metadata_lines.append(f"    {field}: {field_value}")

        if cached_response.response is not None:
            match cached_response.response:
                case CostedLanguageModelResponse():
                    joined_responses = "".join([r.text for r in cached_response.response.responses]).encode("utf-8")
                    for response_index, response in enumerate(cached_response.response.responses):
                        metadata_lines.append(f"response[{response_index}] metadata:")
                        for (
                            field,
                            field_value,
                        ) in cached_response.response.__dict__.items():
                            if field != "responses":  # already printed the responses above
                                metadata_lines.append(f"    {field}: {field_value}")
                case CountTokensResponse():
                    metadata_lines.append("response metadata:")
                    for field, field_value in cached_response.response.__dict__.items():
                        metadata_lines.append(f"    {field}: {field_value}")

        snapshotted_prompt = snapshot(
            extension_class=SingleFileSnapshotExtension,
            name=f"{cache_index:03d}_inputs{suffix}",
        )

        # TODO nasty syrupy hacking
        snapshot_contents, _ = snapshotted_prompt._recall_data(snapshotted_prompt.index)

        assert (
            snapshotted_prompt == prompt
        ), f"Your prompt changed, did you mean for this to happen?\nExpected prompt: {snapshot_contents!r}\nPrompt: {prompt!r}"

        snapshotted_response = snapshot(
            extension_class=SingleFileSnapshotExtension,
            name=f"{cache_index:03d}_response{suffix}",
        )

        assert (
            snapshotted_response == joined_responses
        ), "Your response changed; maybe you aren't actually hitting the cache?"

        snapshotted_metadata = snapshot(
            extension_class=SingleFileAmberSnapshotExtension,
            name=f"{cache_index:03d}_metadata{suffix}",
        )
        assert snapshotted_metadata == "\n".join(
            metadata_lines
        ), "Metadata changed; maybe you aren't actually hitting the cache?"
