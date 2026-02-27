from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from vet.cli.main import main

_REMOTE_PROVIDER_JSON = json.dumps(
    {
        "providers": {
            "remote-provider": {
                "base_url": "http://remote:8080/v1",
                "api_key_env": "REMOTE_KEY",
                "models": {
                    "remote-model-a": {
                        "context_window": 128000,
                        "max_output_tokens": 16384,
                        "supports_temperature": True,
                    },
                    "remote-model-b": {
                        "context_window": 64000,
                        "max_output_tokens": 8192,
                        "supports_temperature": False,
                    },
                },
            }
        }
    }
)


def _make_mock_response(data: bytes):
    """Create a mock urllib response object."""
    return type(
        "Response",
        (),
        {
            "read": lambda self: data,
            "__enter__": lambda self: self,
            "__exit__": lambda *a: None,
        },
    )()


def _env_for_isolated_config(tmp_path: Path) -> dict[str, str]:
    """Return env overrides that isolate XDG dirs to tmp_path."""
    return {
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }


class TestUpdateModels:
    """CLI integration tests for the --update-models flag."""

    def test_update_models_success(self, tmp_path: Path, capsys) -> None:
        mock_response = _make_mock_response(_REMOTE_PROVIDER_JSON.encode())
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch(
                "vet.cli.config.loader.urllib.request.urlopen",
                return_value=mock_response,
            ):
                exit_code = main(["--update-models"])

        assert exit_code == 0

        captured = capsys.readouterr()
        assert "Updated model registry" in captured.out
        assert "2 models from 1 providers" in captured.out
        assert "Cache written to" in captured.out

    def test_update_models_writes_cache_file(self, tmp_path: Path) -> None:
        mock_response = _make_mock_response(_REMOTE_PROVIDER_JSON.encode())
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch(
                "vet.cli.config.loader.urllib.request.urlopen",
                return_value=mock_response,
            ):
                main(["--update-models"])

        cache_file = tmp_path / "cache" / "vet" / "remote_models.json"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert "remote-provider" in data["providers"]

    def test_update_models_network_error_returns_1(self, tmp_path: Path, capsys) -> None:
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch(
                "vet.cli.config.loader.urllib.request.urlopen",
                side_effect=OSError("connection refused"),
            ):
                exit_code = main(["--update-models"])

        assert exit_code == 1

        captured = capsys.readouterr()
        assert "failed to update model registry" in captured.err
        assert "connection refused" in captured.err

    def test_update_models_invalid_remote_data_returns_1(self, tmp_path: Path, capsys) -> None:
        mock_response = _make_mock_response(b"<html>Not Found</html>")
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch(
                "vet.cli.config.loader.urllib.request.urlopen",
                return_value=mock_response,
            ):
                exit_code = main(["--update-models"])

        assert exit_code == 1

        captured = capsys.readouterr()
        assert "failed to update model registry" in captured.err

    def test_update_models_does_not_write_cache_on_invalid_data(self, tmp_path: Path) -> None:
        mock_response = _make_mock_response(b"not json at all")
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch(
                "vet.cli.config.loader.urllib.request.urlopen",
                return_value=mock_response,
            ):
                main(["--update-models"])

        cache_file = tmp_path / "cache" / "vet" / "remote_models.json"
        assert not cache_file.exists()
