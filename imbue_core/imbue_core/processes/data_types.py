from pathlib import Path

from imbue_core.pydantic_serialization import FrozenModel


class SSHConnectionData(FrozenModel):
    host: str
    port: int
    user: str
    keyfile: Path | None = None
