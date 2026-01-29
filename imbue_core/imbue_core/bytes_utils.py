from typing import assert_never


# i have no idea why this isn't built in
def to_str(sb: str | bytes) -> str:
    """Convert a string or bytes to a string, in a path-safe manner."""
    match sb:
        case str():
            return sb
        case bytes():
            return sb.decode("utf-8", errors="surrogateescape")
        case _ as unreachable:
            assert_never(unreachable)
