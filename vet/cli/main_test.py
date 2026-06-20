from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

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


def _env_for_isolated_config(tmp_path: Path) -> dict[str, str]:
    """Return env overrides that isolate XDG dirs to tmp_path."""
    return {
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }


class TestUpdateModels:
    """CLI integration tests for the --update-models flag."""

    def test_update_models_success(self, tmp_path: Path, capsys, make_mock_response) -> None:
        mock_response = make_mock_response(_REMOTE_PROVIDER_JSON.encode())
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

    def test_update_models_writes_cache_file(self, tmp_path: Path, make_mock_response) -> None:
        mock_response = make_mock_response(_REMOTE_PROVIDER_JSON.encode())
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

    def test_update_models_invalid_remote_data_returns_1(self, tmp_path: Path, capsys, make_mock_response) -> None:
        mock_response = make_mock_response(b"<html>Not Found</html>")
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

    def test_update_models_does_not_write_cache_on_invalid_data(self, tmp_path: Path, make_mock_response) -> None:
        mock_response = make_mock_response(b"not json at all")
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch(
                "vet.cli.config.loader.urllib.request.urlopen",
                return_value=mock_response,
            ):
                main(["--update-models"])

        cache_file = tmp_path / "cache" / "vet" / "remote_models.json"
        assert not cache_file.exists()


class TestListModels:
    """CLI integration tests for the --list-models flag."""

    def test_list_models_shows_registry_models(self, tmp_path: Path, capsys, make_mock_response) -> None:
        """Registry models should appear in --list-models output after --update-models."""
        mock_response = make_mock_response(_REMOTE_PROVIDER_JSON.encode())
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch(
                "vet.cli.config.loader.urllib.request.urlopen",
                return_value=mock_response,
            ):
                main(["--update-models"])

            exit_code = main(["--list-models"])

        assert exit_code == 0

        captured = capsys.readouterr()
        assert "remote-model-a" in captured.out
        assert "remote-model-b" in captured.out


class TestListConfigs:
    """CLI integration tests for the --list-configs flag."""

    def _write_models_json(self, tmp_path: Path, model_id: str) -> None:
        config_dir = tmp_path / "config" / "vet"
        config_dir.mkdir(parents=True)
        (config_dir / "models.json").write_text(
            json.dumps(
                {
                    "providers": {
                        "local": {
                            "base_url": "http://localhost:11434/v1",
                            "models": {
                                model_id: {
                                    "context_window": 131072,
                                    "max_output_tokens": 8192,
                                    "supports_temperature": True,
                                }
                            },
                        }
                    }
                }
            )
        )

    def _write_configs_toml(self, tmp_path: Path, model_id: str) -> None:
        config_dir = tmp_path / "config" / "vet"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "configs.toml").write_text(f'[mypreset]\nmodel = "{model_id}"\n')

    def test_list_configs_valid_model_no_warning(self, tmp_path: Path, capsys) -> None:
        self._write_models_json(tmp_path, "my-local-model")
        self._write_configs_toml(tmp_path, "my-local-model")
        env = _env_for_isolated_config(tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        with patch.dict(os.environ, env):
            exit_code = main(["--list-configs", "--repo", str(repo)])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "my-local-model" in captured.out
        assert "check for a typo" not in captured.out

    def test_list_configs_unknown_model_shows_warning(self, tmp_path: Path, capsys) -> None:
        self._write_models_json(tmp_path, "my-local-model")
        self._write_configs_toml(tmp_path, "my-local-model-typo")
        env = _env_for_isolated_config(tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        with patch.dict(os.environ, env):
            exit_code = main(["--list-configs", "--repo", str(repo)])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "my-local-model-typo" in captured.out
        assert "check for a typo" in captured.out

    def test_list_configs_registry_model_no_warning(self, tmp_path: Path, capsys, make_mock_response) -> None:
        registry_json = json.dumps(
            {
                "providers": {
                    "remote": {
                        "base_url": "http://remote:8080/v1",
                        "models": {
                            "registry-only-model": {
                                "context_window": 128000,
                                "max_output_tokens": 16384,
                                "supports_temperature": True,
                            }
                        },
                    }
                }
            }
        )
        mock_response = make_mock_response(registry_json.encode())
        self._write_configs_toml(tmp_path, "registry-only-model")
        env = _env_for_isolated_config(tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        with patch.dict(os.environ, env):
            with patch("vet.cli.config.loader.urllib.request.urlopen", return_value=mock_response):
                main(["--update-models"])
            exit_code = main(["--list-configs", "--repo", str(repo)])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "registry-only-model" in captured.out
        assert "check for a typo" not in captured.out


class TestModelRefusal:
    """CLI integration tests for surfacing model refusals."""

    def test_model_refusal_prints_error_and_returns_1(self, tmp_path: Path, capsys) -> None:
        import subprocess

        from vet.imbue_core.agents.llm_apis.errors import ModelRefusalError

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"],
            cwd=repo,
            check=True,
        )

        env = _env_for_isolated_config(tmp_path) | {"ANTHROPIC_API_KEY": "test-key"}
        refusal = ModelRefusalError(
            "The model refused to generate a response (the provider's safety classifiers declined the request)."
        )

        with patch.dict(os.environ, env):
            # configure_logging would tear down the logging handlers installed by test fixtures.
            with patch("vet.cli.main.configure_logging"):
                with patch("vet.api.find_issues", side_effect=refusal):
                    exit_code = main(["test goal", "--repo", str(repo), "--quiet"])

        assert exit_code == 1

        captured = capsys.readouterr()
        assert "refused" in captured.err
        assert "try re-running" in captured.err
