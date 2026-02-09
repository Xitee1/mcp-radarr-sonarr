"""Configuration management for the Radarr/Sonarr MCP server."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RadarrConfig:
    """Radarr configuration."""
    api_key: str
    url: str  # Full URL like http://10.0.0.23:7878
    base_path: str = "/api/v3"


@dataclass
class SonarrConfig:
    """Sonarr configuration."""
    api_key: str
    url: str  # Full URL like http://10.0.0.23:8989
    base_path: str = "/api/v3"


@dataclass
class Config:
    """Main configuration container."""
    radarr_config: RadarrConfig
    sonarr_config: SonarrConfig
    read_only: bool = False


def get_config_path() -> Path:
    """Get the path to the config file."""
    # Use user's home directory for config
    config_dir = Path.home() / ".config" / "radarr-sonarr-mcp"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from file or environment variables."""
    if config_path:
        path = Path(config_path)
    else:
        path = get_config_path()
    
    # Environment variable override for read-only mode (takes precedence)
    read_only_env = os.getenv("READ_ONLY", "").lower()
    
    # Try to load from config file first
    if path.exists():
        with open(path, 'r') as f:
            data = json.load(f)
        
        read_only = data.get("read_only", False)
        if read_only_env:
            read_only = read_only_env in ("true", "1", "yes")
        
        return Config(
            radarr_config=RadarrConfig(**data["radarr_config"]),
            sonarr_config=SonarrConfig(**data["sonarr_config"]),
            read_only=read_only
        )
    
    # Fall back to environment variables
    radarr_api_key = os.getenv("RADARR_API_KEY", "")
    radarr_url = os.getenv("RADARR_URL", "http://localhost:7878")
    radarr_base_path = os.getenv("RADARR_BASE_PATH", "/api/v3")
    
    sonarr_api_key = os.getenv("SONARR_API_KEY", "")
    sonarr_url = os.getenv("SONARR_URL", "http://localhost:8989")
    sonarr_base_path = os.getenv("SONARR_BASE_PATH", "/api/v3")
    
    read_only = read_only_env in ("true", "1", "yes") if read_only_env else False
    
    return Config(
        radarr_config=RadarrConfig(api_key=radarr_api_key, url=radarr_url, base_path=radarr_base_path),
        sonarr_config=SonarrConfig(api_key=sonarr_api_key, url=sonarr_url, base_path=sonarr_base_path),
        read_only=read_only
    )


def save_config(config: Config, config_path: Optional[str] = None) -> None:
    """Save configuration to file."""
    if config_path:
        path = Path(config_path)
    else:
        path = get_config_path()
    
    # Ensure directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "radarr_config": {
            "api_key": config.radarr_config.api_key,
            "url": config.radarr_config.url,
            "base_path": config.radarr_config.base_path
        },
        "sonarr_config": {
            "api_key": config.sonarr_config.api_key,
            "url": config.sonarr_config.url,
            "base_path": config.sonarr_config.base_path
        },
        "read_only": config.read_only
    }
    
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)