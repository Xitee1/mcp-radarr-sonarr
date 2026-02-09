"""Command-line interface for the Radarr/Sonarr MCP server."""

import argparse
import logging

from .config import Config, RadarrConfig, SonarrConfig, load_config, save_config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def configure():
    """Run the configuration wizard."""
    logging.info("==== Radarr/Sonarr MCP Server Configuration Wizard ====")
    
    # Try to load existing config
    config = None
    try:
        config = load_config()
        logging.info("Loaded existing configuration. Press Enter to keep current values.")
    except Exception:
        # No existing config or error loading
        pass
    
    # Radarr configuration
    radarr_url = input(f"Radarr URL (e.g., http://localhost:7878) [{config.radarr_config.url if config else 'http://localhost:7878'}]: ")
    radarr_url = radarr_url or (config.radarr_config.url if config else 'http://localhost:7878')
    
    radarr_api_key = input(f"Radarr API key [{config.radarr_config.api_key if config else ''}]: ")
    radarr_api_key = radarr_api_key or (config.radarr_config.api_key if config else '')
    if not radarr_api_key:
        logging.warning("Warning: Radarr API key is required for movie functionality!")
    
    radarr_base_path = input(f"Radarr API base path [{config.radarr_config.base_path if config else '/api/v3'}]: ")
    radarr_base_path = radarr_base_path or (config.radarr_config.base_path if config else '/api/v3')
    
    # Sonarr configuration
    sonarr_url = input(f"Sonarr URL (e.g., http://localhost:8989) [{config.sonarr_config.url if config else 'http://localhost:8989'}]: ")
    sonarr_url = sonarr_url or (config.sonarr_config.url if config else 'http://localhost:8989')
    
    sonarr_api_key = input(f"Sonarr API key [{config.sonarr_config.api_key if config else ''}]: ")
    sonarr_api_key = sonarr_api_key or (config.sonarr_config.api_key if config else '')
    if not sonarr_api_key:
        logging.warning("Warning: Sonarr API key is required for TV show functionality!")
    
    sonarr_base_path = input(f"Sonarr API base path [{config.sonarr_config.base_path if config else '/api/v3'}]: ")
    sonarr_base_path = sonarr_base_path or (config.sonarr_config.base_path if config else '/api/v3')
    
    # Read-only mode
    read_only_default = config.read_only if config else False
    read_only_input = input(f"Enable read-only mode? (y/n) [{'y' if read_only_default else 'n'}]: ").strip().lower()
    if read_only_input:
        read_only = read_only_input in ("y", "yes", "true", "1")
    else:
        read_only = read_only_default
    
    # Create new config
    new_config = Config(
        radarr_config=RadarrConfig(
            api_key=radarr_api_key,
            url=radarr_url,
            base_path=radarr_base_path
        ),
        sonarr_config=SonarrConfig(
            api_key=sonarr_api_key,
            url=sonarr_url,
            base_path=sonarr_base_path
        ),
        read_only=read_only
    )
    
    # Save config
    save_config(new_config)
    logging.info("Configuration saved successfully!")
    logging.info("Server is now ready for use with Claude Code via MCP protocol.")
    
    return new_config


def start(config_path=None):
    """Start the MCP server (for development/testing only - Claude Code starts it automatically)."""
    import subprocess
    import sys
    
    logging.info("Note: Claude Code starts the MCP server automatically.")
    logging.info("This command is only for development/testing purposes.")
    
    # Run the server module directly
    cmd = [sys.executable, "-m", "radarr_sonarr_mcp.server"]
    if config_path:
        cmd.extend(["--config", config_path])
    
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        logging.info("Server stopped by user")
    except Exception as e:
        logging.error(f"Server failed to start: {e}")


def show_status():
    """Show the current status of the server."""
    try:
        config = load_config()
        logging.info("==== Radarr/Sonarr MCP Server Status ====")
        logging.info(f"Radarr URL: {config.radarr_config.url}")
        logging.info(f"Sonarr URL: {config.sonarr_config.url}")
        logging.info(f"Read-only mode: {'enabled' if config.read_only else 'disabled'}")
        logging.info(f"Transport: STDIO (for Claude Code integration)")
        logging.info(f"Server is configured and ready for Claude Code.")
    except Exception as e:
        logging.error(f"Server is not configured: {e}")
        logging.info("Run 'radarr-sonarr-mcp configure' to set up the server.")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Radarr/Sonarr MCP Server")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Configure command
    configure_parser = subparsers.add_parser("configure", help="Configure the MCP server")
    
    # Start command  
    start_parser = subparsers.add_parser("start", help="Start the MCP server (for testing only - Claude Code will start it automatically)")
    start_parser.add_argument("--config", help="Path to config file")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Show the server status")
    
    args = parser.parse_args()
    
    if args.command == "configure":
        configure()
    elif args.command == "start":
        start(args.config)
    elif args.command == "status":
        show_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
