import os
import pathlib

from pydantic import SecretStr


class Secret(SecretStr):
    """Pydantic-aware secret wrapper that hides values in logs."""

    def __str__(self) -> str:
        return "[redacted]"

    __repr__ = __str__

    def unwrap(self) -> str:
        return self.get_secret_value()


class YouAreBeingTooFancyInYourSettingsFile(Exception):
    pass


def parse_secrets_file(filepath: str | pathlib.Path) -> dict[str, str]:
    """Parse bashenv_secrets.sh-style file into a dict.
    We should REALLY NOT BE DOING THIS EVER but unfortunately that's not the case so at least let's only do it once here

    Not a great parser; will break in probably many scenarios but end-of-line comments are one that comes to mind
    """
    out: dict[str, str] = {}
    with open(filepath) as f:
        for line in f:
            if "$" in line:
                raise YouAreBeingTooFancyInYourSettingsFile(
                    "Yeah, don't do that. This .sh file is meant to be simple definitions, it should not use any features of bash or sh, including string interpolation via $"
                )
            if "#" in line:
                if not line.startswith("#"):
                    raise YouAreBeingTooFancyInYourSettingsFile(
                        "Put comments at the start of the line"
                    )
                continue
            if "\\" in line:
                raise YouAreBeingTooFancyInYourSettingsFile(
                    "No line continuations or other character escapes allowed"
                )
            if line.startswith("export "):
                k, v = line.strip("export ").strip().split("=", maxsplit=1)
                k = k.strip()
                if k != k.upper():
                    raise YouAreBeingTooFancyInYourSettingsFile(
                        f"Key {k} must be uppercase"
                    )
                v = v.strip()
                if v.startswith('"'):
                    if not v.endswith('"'):
                        raise YouAreBeingTooFancyInYourSettingsFile(
                            f"Value {v} must end with a double quote"
                        )
                    v = v[1:-1]
                if v.startswith("'"):
                    if not v.endswith("'"):
                        raise YouAreBeingTooFancyInYourSettingsFile(
                            f"Value {v} must end with a single quote"
                        )
                    v = v[1:-1]
                out[k] = v
            elif line.strip():
                raise YouAreBeingTooFancyInYourSettingsFile(
                    f"All lines must start with 'export ', but this line did not: {line}"
                )
    return out


# TODO: this is gross and bad--we should make better handling for secrets.
#  Right now we read the necessary secrets out of the bashenv files
def get_secret(secret_name: str) -> str | None:
    value = os.environ.get(secret_name)
    if value is not None:
        return value
    secrets_files = (
        "science/secrets/environment_vars/bashenv.sh",
        "science/secrets/environment_vars/bashenv_secrets.sh",
        "science/secrets/environment_vars/common_vars.sh",
    )
    for file in secrets_files:
        if os.path.exists(file):
            secrets = parse_secrets_file(file)
            value = secrets.get(secret_name, None)
            if value is not None:
                return value
    return None
