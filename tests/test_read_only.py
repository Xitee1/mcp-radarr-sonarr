"""Tests for read-only mode functionality."""

import json
import os
import tempfile

import pytest
import pytest_asyncio

from radarr_sonarr_mcp.config import Config, RadarrConfig, SonarrConfig, load_config, save_config
from radarr_sonarr_mcp.server import WRITE_TOOLS, handle_list_tools, handle_call_tool


# --- Config tests ---

class TestReadOnlyConfig:
    """Tests for read-only mode configuration loading."""

    def _make_config_data(self, read_only=False):
        return {
            "radarr_config": {"api_key": "test", "url": "http://localhost:7878", "base_path": "/api/v3"},
            "sonarr_config": {"api_key": "test", "url": "http://localhost:8989", "base_path": "/api/v3"},
            "read_only": read_only,
        }

    def test_config_defaults_to_read_only_false(self):
        config = Config(
            radarr_config=RadarrConfig(api_key="k", url="http://localhost:7878"),
            sonarr_config=SonarrConfig(api_key="k", url="http://localhost:8989"),
        )
        assert config.read_only is False

    def test_config_read_only_true(self):
        config = Config(
            radarr_config=RadarrConfig(api_key="k", url="http://localhost:7878"),
            sonarr_config=SonarrConfig(api_key="k", url="http://localhost:8989"),
            read_only=True,
        )
        assert config.read_only is True

    def test_load_config_from_file_read_only_true(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(self._make_config_data(read_only=True)))
        config = load_config(str(config_file))
        assert config.read_only is True

    def test_load_config_from_file_read_only_false(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(self._make_config_data(read_only=False)))
        config = load_config(str(config_file))
        assert config.read_only is False

    def test_load_config_from_file_missing_read_only_defaults_false(self, tmp_path):
        data = self._make_config_data()
        del data["read_only"]
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(data))
        config = load_config(str(config_file))
        assert config.read_only is False

    def test_env_var_overrides_config_file(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(self._make_config_data(read_only=False)))
        monkeypatch.setenv("READ_ONLY", "true")
        config = load_config(str(config_file))
        assert config.read_only is True

    def test_env_var_overrides_config_file_to_false(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(self._make_config_data(read_only=True)))
        monkeypatch.setenv("READ_ONLY", "false")
        config = load_config(str(config_file))
        assert config.read_only is False

    def test_env_var_accepts_1(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(self._make_config_data(read_only=False)))
        monkeypatch.setenv("READ_ONLY", "1")
        config = load_config(str(config_file))
        assert config.read_only is True

    def test_env_var_accepts_yes(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(self._make_config_data(read_only=False)))
        monkeypatch.setenv("READ_ONLY", "yes")
        config = load_config(str(config_file))
        assert config.read_only is True

    def test_env_var_fallback_when_no_config_file(self, tmp_path, monkeypatch):
        config_file = tmp_path / "nonexistent.json"
        monkeypatch.setenv("READ_ONLY", "true")
        monkeypatch.setenv("RADARR_API_KEY", "test")
        monkeypatch.setenv("SONARR_API_KEY", "test")
        config = load_config(str(config_file))
        assert config.read_only is True

    def test_save_config_includes_read_only(self, tmp_path):
        config = Config(
            radarr_config=RadarrConfig(api_key="k", url="http://localhost:7878"),
            sonarr_config=SonarrConfig(api_key="k", url="http://localhost:8989"),
            read_only=True,
        )
        config_file = tmp_path / "config.json"
        save_config(config, str(config_file))
        with open(config_file) as f:
            data = json.load(f)
        assert data["read_only"] is True


# --- Server tests ---

class TestReadOnlyServer:
    """Tests for read-only mode in the server."""

    def test_write_tools_set_is_not_empty(self):
        assert len(WRITE_TOOLS) > 0

    def test_expected_write_tools(self):
        expected = {
            "add_radarr_movie", "add_sonarr_series",
            "delete_radarr_movie", "delete_sonarr_series",
            "update_radarr_movie", "update_sonarr_series",
            "monitor_sonarr_episodes", "remove_from_queue",
            "manual_import", "execute_command", "refresh_monitored",
        }
        assert WRITE_TOOLS == expected

    @pytest.mark.asyncio
    async def test_write_tool_blocked_in_read_only(self, monkeypatch):
        """When read-only is enabled, write tools return an error message."""
        monkeypatch.setenv("READ_ONLY", "true")
        # Use a non-existent config path so env vars are used
        monkeypatch.setenv("RADARR_API_KEY", "test")
        monkeypatch.setenv("SONARR_API_KEY", "test")

        result = await handle_call_tool("add_radarr_movie", {"tmdbId": 1, "title": "Test", "year": 2024})
        assert len(result) == 1
        assert "read-only mode" in result[0].text

    @pytest.mark.asyncio
    async def test_read_tool_allowed_in_read_only(self, monkeypatch):
        """When read-only is enabled, read tools still work (they may fail for other reasons like no API)."""
        monkeypatch.setenv("READ_ONLY", "true")
        monkeypatch.setenv("RADARR_API_KEY", "")
        monkeypatch.setenv("SONARR_API_KEY", "")

        # This should NOT be blocked by read-only - it should attempt to run
        # (and likely fail due to no API key, but that's fine)
        result = await handle_call_tool("get_radarr_movies", {})
        assert len(result) == 1
        # Should not contain the read-only error
        assert "read-only mode" not in result[0].text

    @pytest.mark.asyncio
    async def test_all_write_tools_blocked(self, monkeypatch):
        """Verify every tool in WRITE_TOOLS is blocked in read-only mode."""
        monkeypatch.setenv("READ_ONLY", "true")
        monkeypatch.setenv("RADARR_API_KEY", "test")
        monkeypatch.setenv("SONARR_API_KEY", "test")

        for tool_name in WRITE_TOOLS:
            result = await handle_call_tool(tool_name, {})
            assert "read-only mode" in result[0].text, f"{tool_name} should be blocked in read-only mode"

    @pytest.mark.asyncio
    async def test_handle_list_tools_filters_write_tools(self, monkeypatch):
        """In read-only mode, write tools should not be listed."""
        monkeypatch.setenv("READ_ONLY", "true")
        monkeypatch.setenv("RADARR_API_KEY", "test")
        monkeypatch.setenv("SONARR_API_KEY", "test")

        tools = await handle_list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names.isdisjoint(WRITE_TOOLS), f"Write tools should not be listed: {tool_names & WRITE_TOOLS}"

    @pytest.mark.asyncio
    async def test_handle_list_tools_includes_all_when_not_read_only(self, monkeypatch):
        """When not in read-only mode, all tools should be listed."""
        monkeypatch.delenv("READ_ONLY", raising=False)
        monkeypatch.setenv("RADARR_API_KEY", "test")
        monkeypatch.setenv("SONARR_API_KEY", "test")

        tools = await handle_list_tools()
        tool_names = {t.name for t in tools}
        assert WRITE_TOOLS.issubset(tool_names), f"Missing write tools: {WRITE_TOOLS - tool_names}"
