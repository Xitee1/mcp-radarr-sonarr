#!/usr/bin/env python
"""MCP server for Radarr and Sonarr integration with Claude Code."""

import argparse
import asyncio
import importlib.metadata
import logging
import os
import sys
from typing import Any, Optional

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
import requests

from .config import load_config as load_config_module
from .tools_extended import get_extended_tools
from .handlers_extended import (
    handle_download_queue, handle_remove_from_queue, handle_get_history,
    handle_manual_import, handle_calendar, handle_wanted, handle_system_status,
    handle_disk_space, handle_execute_command, handle_get_collections,
    handle_refresh_monitored
)
from .response_formatter import format_response

# Set up logging to stderr (never to stdout as it corrupts MCP JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Global server instance
server = Server("radarr-sonarr-mcp")

# Tools that modify data (blocked in read-only mode)
WRITE_TOOLS = {
    "add_radarr_movie",
    "add_sonarr_series",
    "delete_radarr_movie",
    "delete_sonarr_series",
    "update_radarr_movie",
    "update_sonarr_series",
    "monitor_sonarr_episodes",
    "remove_from_queue",
    "manual_import",
    "execute_command",
    "refresh_monitored",
}


def load_config():
    """Load configuration from config module."""
    try:
        config = load_config_module()
        # Convert to internal format
        return {
            "radarrConfig": {
                "apiKey": config.radarr_config.api_key,
                "url": config.radarr_config.url,
                "basePath": config.radarr_config.base_path
            },
            "sonarrConfig": {
                "apiKey": config.sonarr_config.api_key,
                "url": config.sonarr_config.url,
                "basePath": config.sonarr_config.base_path
            },
            "readOnly": config.read_only
        }
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        read_only_env = os.getenv("READ_ONLY", "").lower()
        return {
            "radarrConfig": {"apiKey": "", "url": "http://localhost:7878", "basePath": "/api/v3"},
            "sonarrConfig": {"apiKey": "", "url": "http://localhost:8989", "basePath": "/api/v3"},
            "readOnly": read_only_env in ("true", "1", "yes")
        }


def get_radarr_url(config):
    """Get Radarr API URL."""
    url = config["radarrConfig"]["url"].rstrip('/')
    base_path = config["radarrConfig"]["basePath"]
    return f"{url}{base_path}"


def get_sonarr_url(config):
    """Get Sonarr API URL."""
    url = config["sonarrConfig"]["url"].rstrip('/')
    base_path = config["sonarrConfig"]["basePath"]
    return f"{url}{base_path}"


def make_radarr_request(config, endpoint, params=None, method="GET", json_data=None):
    """Make a request to Radarr API."""
    base_url = get_radarr_url(config)
    api_key = config["radarrConfig"]["apiKey"]
    
    if not api_key:
        raise ValueError("Radarr API key not configured")
    
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    url = f"{base_url}/{endpoint.lstrip('/')}"
    
    try:
        if method.upper() == "POST":
            response = requests.post(url, headers=headers, params=params, json=json_data, timeout=30)
        elif method.upper() == "PUT":
            response = requests.put(url, headers=headers, params=params, json=json_data, timeout=30)
        else:
            response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Radarr API request failed: {e}")
        raise


def make_sonarr_request(config, endpoint, params=None, method="GET", json_data=None):
    """Make a request to Sonarr API."""
    base_url = get_sonarr_url(config)
    api_key = config["sonarrConfig"]["apiKey"]
    
    if not api_key:
        raise ValueError("Sonarr API key not configured")
    
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    url = f"{base_url}/{endpoint.lstrip('/')}"
    
    try:
        if method.upper() == "POST":
            response = requests.post(url, headers=headers, params=params, json=json_data, timeout=30)
        elif method.upper() == "PUT":
            response = requests.put(url, headers=headers, params=params, json=json_data, timeout=30)
        else:
            response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Sonarr API request failed: {e}")
        raise


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools."""
    base_tools = [
        types.Tool(
            name="get_radarr_movies",
            description="Get list of movies from Radarr",
            inputSchema={
                "type": "object",
                "properties": {
                    "monitored": {
                        "type": "boolean",
                        "description": "Filter by monitored status"
                    },
                    "downloaded": {
                        "type": "boolean", 
                        "description": "Filter by downloaded status"
                    }
                },
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="get_sonarr_series",
            description="Get list of TV series from Sonarr",
            inputSchema={
                "type": "object",
                "properties": {
                    "monitored": {
                        "type": "boolean",
                        "description": "Filter by monitored status"
                    },
                    "downloaded": {
                        "type": "boolean",
                        "description": "Filter by downloaded status" 
                    }
                },
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="search_radarr_movies",
            description="Search for movies in Radarr",
            inputSchema={
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "Search term for movie title"
                    }
                },
                "required": ["term"],
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="search_sonarr_series",
            description="Search for TV series in Sonarr",  
            inputSchema={
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "Search term for series title"
                    }
                },
                "required": ["term"],
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="add_radarr_movie",
            description="Add a movie to Radarr library and request download",
            inputSchema={
                "type": "object",
                "properties": {
                    "tmdbId": {
                        "type": "integer",
                        "description": "TMDB ID of the movie to add"
                    },
                    "title": {
                        "type": "string",
                        "description": "Movie title"
                    },
                    "year": {
                        "type": "integer",
                        "description": "Release year"
                    },
                    "qualityProfileId": {
                        "type": "integer",
                        "description": "Quality profile ID (optional, uses default if not provided)",
                        "default": 1
                    },
                    "rootFolderPath": {
                        "type": "string",
                        "description": "Root folder path (optional, uses default if not provided)"
                    },
                    "monitored": {
                        "type": "boolean",
                        "description": "Whether to monitor the movie",
                        "default": True
                    },
                    "searchForMovie": {
                        "type": "boolean", 
                        "description": "Whether to search for the movie immediately",
                        "default": True
                    }
                },
                "required": ["tmdbId", "title", "year"],
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="add_sonarr_series",
            description="Add a TV series to Sonarr library and request download",
            inputSchema={
                "type": "object",
                "properties": {
                    "tvdbId": {
                        "type": "integer",
                        "description": "TVDB ID of the series to add"
                    },
                    "title": {
                        "type": "string",
                        "description": "Series title"
                    },
                    "year": {
                        "type": "integer",
                        "description": "First air year"
                    },
                    "qualityProfileId": {
                        "type": "integer",
                        "description": "Quality profile ID (optional, uses default if not provided)",
                        "default": 1
                    },
                    "rootFolderPath": {
                        "type": "string",
                        "description": "Root folder path (optional, uses default if not provided)"
                    },
                    "monitored": {
                        "type": "boolean",
                        "description": "Whether to monitor the series",
                        "default": True
                    },
                    "searchForMissingEpisodes": {
                        "type": "boolean",
                        "description": "Whether to search for missing episodes immediately", 
                        "default": True
                    },
                    "seasonFolder": {
                        "type": "boolean",
                        "description": "Whether to use season folders",
                        "default": True
                    }
                },
                "required": ["tvdbId", "title", "year"],
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="delete_radarr_movie",
            description="Delete a movie from Radarr library",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "The movie ID to delete"
                    },
                    "deleteFiles": {
                        "type": "boolean",
                        "description": "Whether to delete the movie files from disk",
                        "default": False
                    },
                    "addImportExclusion": {
                        "type": "boolean",
                        "description": "Whether to add to import exclusion list to prevent re-import",
                        "default": False
                    }
                },
                "required": ["id"],
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="delete_sonarr_series",
            description="Delete a TV series from Sonarr library",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "The series ID to delete"
                    },
                    "deleteFiles": {
                        "type": "boolean",
                        "description": "Whether to delete the series files from disk",
                        "default": False
                    },
                    "addImportListExclusion": {
                        "type": "boolean",
                        "description": "Whether to add to import exclusion list to prevent re-import",
                        "default": False
                    }
                },
                "required": ["id"],
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="update_radarr_movie", 
            description="Update a movie's settings in Radarr",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "The movie ID to update"
                    },
                    "monitored": {
                        "type": "boolean",
                        "description": "Whether to monitor the movie"
                    },
                    "qualityProfileId": {
                        "type": "integer",
                        "description": "Quality profile ID"
                    },
                    "minimumAvailability": {
                        "type": "string",
                        "description": "Minimum availability (announced, inCinemas, released, preDB)",
                        "enum": ["announced", "inCinemas", "released", "preDB"]
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Array of tag IDs"
                    }
                },
                "required": ["id"],
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="update_sonarr_series",
            description="Update a TV series' settings in Sonarr", 
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "The series ID to update"
                    },
                    "monitored": {
                        "type": "boolean",
                        "description": "Whether to monitor the series"
                    },
                    "qualityProfileId": {
                        "type": "integer",
                        "description": "Quality profile ID"
                    },
                    "seriesType": {
                        "type": "string",
                        "description": "Series type",
                        "enum": ["standard", "daily", "anime"]
                    },
                    "seasonFolder": {
                        "type": "boolean",
                        "description": "Whether to use season folders"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Array of tag IDs"
                    }
                },
                "required": ["id"],
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="get_radarr_movie_by_id",
            description="Get detailed information about a specific movie by Radarr ID (use get_radarr_movies to find IDs)",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "The Radarr internal ID (not TMDB ID)"
                    }
                },
                "required": ["id"],
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="get_radarr_movie_by_tmdb_id",
            description="Get detailed information about a movie by TMDB ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "tmdbId": {
                        "type": "integer",
                        "description": "The TMDB ID of the movie"
                    }
                },
                "required": ["tmdbId"],
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="get_sonarr_series_by_id",
            description="Get detailed information about a specific TV series",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "The series ID"
                    }
                },
                "required": ["id"],
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="get_sonarr_episodes",
            description="Get episodes for a specific TV series",
            inputSchema={
                "type": "object",
                "properties": {
                    "seriesId": {
                        "type": "integer",
                        "description": "The series ID"
                    },
                    "seasonNumber": {
                        "type": "integer",
                        "description": "Filter by season number (optional)"
                    },
                    "includeImages": {
                        "type": "boolean",
                        "description": "Include episode images",
                        "default": False
                    }
                },
                "required": ["seriesId"],
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="monitor_sonarr_episodes",
            description="Bulk update episode monitoring status",
            inputSchema={
                "type": "object",
                "properties": {
                    "episodeIds": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Array of episode IDs to update"
                    },
                    "monitored": {
                        "type": "boolean",
                        "description": "Whether to monitor the episodes"
                    }
                },
                "required": ["episodeIds", "monitored"],
                "additionalProperties": False
            }
        ),
        types.Tool(
            name="get_sonarr_episode_files",
            description="Get episode files for a specific TV series",
            inputSchema={
                "type": "object",
                "properties": {
                    "seriesId": {
                        "type": "integer",
                        "description": "The series ID"
                    }
                },
                "required": ["seriesId"],
                "additionalProperties": False
            }
        )
    ]
    
    # Add extended tools
    extended_tools = get_extended_tools()
    all_tools = base_tools + extended_tools
    
    # Filter out write tools in read-only mode
    config = load_config()
    if config.get("readOnly", False):
        all_tools = [t for t in all_tools if t.name not in WRITE_TOOLS]
    
    return all_tools


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any] | None
) -> list[types.TextContent]:
    """Handle tool calls."""
    if arguments is None:
        arguments = {}
    
    config = load_config()
    
    # Block write operations in read-only mode
    if config.get("readOnly", False) and name in WRITE_TOOLS:
        return [types.TextContent(
            type="text",
            text=f"Error: '{name}' is blocked because the server is running in read-only mode."
        )]
    
    try:
        if name == "get_radarr_movies":
            movies = make_radarr_request(config, "movie")
            
            # Apply filters
            if arguments.get("monitored") is not None:
                movies = [m for m in movies if m.get("monitored") == arguments["monitored"]]
            
            if arguments.get("downloaded") is not None:
                downloaded_filter = arguments["downloaded"]
                movies = [m for m in movies if (m.get("hasFile", False)) == downloaded_filter]
            
            result = {
                "count": len(movies),
                "movies": [
                    {
                        "id": m.get("id"),
                        "title": m.get("title"),
                        "year": m.get("year"),
                        "tmdbId": m.get("tmdbId"),
                        "monitored": m.get("monitored"),
                        "hasFile": m.get("hasFile", False),
                        "status": m.get("status"),
                        "overview": m.get("overview", "")[:200] + "..." if len(m.get("overview", "")) > 200 else m.get("overview", "")
                    }
                    for m in movies  # Return all movies
                ]
            }
            
        elif name == "get_sonarr_series":
            series = make_sonarr_request(config, "series")
            
            # Apply filters  
            if arguments.get("monitored") is not None:
                series = [s for s in series if s.get("monitored") == arguments["monitored"]]
            
            if arguments.get("downloaded") is not None:
                downloaded_filter = arguments["downloaded"]
                series = [s for s in series if (s.get("statistics", {}).get("episodeFileCount", 0) > 0) == downloaded_filter]
            
            if not series:
                result = "No series found."
            else:
                lines = [f"{len(series)} series:"]
                for s in series:  # Return all series
                    title = s.get("title", "Unknown")
                    year = s.get("year", "Unknown")
                    ep_count = s.get("statistics", {}).get("episodeFileCount", 0)
                    total_eps = s.get("statistics", {}).get("episodeCount", 0)
                    lines.append(f"  {title} ({year}) - {ep_count}/{total_eps}")
                
                result = "\n".join(lines)
            
        elif name == "search_radarr_movies":
            term = arguments["term"]
            movies = make_radarr_request(config, "movie/lookup", {"term": term})
            
            if not movies:
                result = "No movies found in search."
            else:
                lines = [f"Found {len(movies)} movies in search:"]
                for m in movies[:20]:  # Limit to 20 results
                    title = m.get("title", "Unknown")
                    year = m.get("year", "Unknown")
                    tmdb_id = m.get("tmdbId")
                    lines.append(f"  {title} ({year}) - ID: {tmdb_id}")
                result = "\n".join(lines)
            
        elif name == "search_sonarr_series":
            term = arguments["term"]
            series = make_sonarr_request(config, "series/lookup", {"term": term})
            
            if not series:
                result = "No series found in search."
            else:
                lines = [f"Found {len(series)} series in search:"]
                for s in series[:20]:  # Limit to 20 results
                    title = s.get("title", "Unknown")
                    year = s.get("year", "Unknown")
                    tvdb_id = s.get("tvdbId")
                    lines.append(f"  {title} ({year}) - ID: {tvdb_id}")
                result = "\n".join(lines)
            
        elif name == "add_radarr_movie":
            tmdb_id = arguments["tmdbId"]
            title = arguments["title"]
            year = arguments["year"]
            
            # Get default quality profile and root folder if not provided
            quality_profile_id = arguments.get("qualityProfileId")
            root_folder_path = arguments.get("rootFolderPath")
            
            if not quality_profile_id:
                # Get first available quality profile
                profiles = make_radarr_request(config, "qualityprofile")
                quality_profile_id = profiles[0]["id"] if profiles else 1
                
            if not root_folder_path:
                # Get first available root folder
                root_folders = make_radarr_request(config, "rootfolder")
                root_folder_path = root_folders[0]["path"] if root_folders else "/movies"
            
            # Prepare movie data for adding
            movie_data = {
                "title": title,
                "year": year,
                "tmdbId": tmdb_id,
                "qualityProfileId": quality_profile_id,
                "rootFolderPath": root_folder_path,
                "monitored": arguments.get("monitored", True),
                "addOptions": {
                    "searchForMovie": arguments.get("searchForMovie", True),
                    "monitor": "movieOnly"
                }
            }
            
            # Add movie to Radarr
            added_movie = make_radarr_request(config, "movie", method="POST", json_data=movie_data)
            
            result = {
                "success": True,
                "message": f"Movie '{title} ({year})' has been added to Radarr",
                "movie": {
                    "id": added_movie.get("id"),
                    "title": added_movie.get("title"),
                    "year": added_movie.get("year"),
                    "tmdbId": added_movie.get("tmdbId"),
                    "monitored": added_movie.get("monitored"),
                    "hasFile": added_movie.get("hasFile", False),
                    "status": added_movie.get("status")
                }
            }
            
        elif name == "add_sonarr_series":
            tvdb_id = arguments["tvdbId"]
            title = arguments["title"]
            year = arguments["year"]
            
            # Get default quality profile and root folder if not provided
            quality_profile_id = arguments.get("qualityProfileId")
            root_folder_path = arguments.get("rootFolderPath")
            
            if not quality_profile_id:
                # Get first available quality profile
                profiles = make_sonarr_request(config, "qualityprofile")
                quality_profile_id = profiles[0]["id"] if profiles else 1
                
            if not root_folder_path:
                # Get first available root folder
                root_folders = make_sonarr_request(config, "rootfolder")
                root_folder_path = root_folders[0]["path"] if root_folders else "/tv"
            
            # Prepare series data for adding
            series_data = {
                "title": title,
                "year": year,
                "tvdbId": tvdb_id,
                "qualityProfileId": quality_profile_id,
                "rootFolderPath": root_folder_path,
                "monitored": arguments.get("monitored", True),
                "seasonFolder": arguments.get("seasonFolder", True),
                "addOptions": {
                    "searchForMissingEpisodes": arguments.get("searchForMissingEpisodes", True),
                    "monitor": "all"
                }
            }
            
            # Add series to Sonarr
            added_series = make_sonarr_request(config, "series", method="POST", json_data=series_data)
            
            result = {
                "success": True,
                "message": f"Series '{title} ({year})' has been added to Sonarr",
                "series": {
                    "id": added_series.get("id"),
                    "title": added_series.get("title"),
                    "year": added_series.get("year"),
                    "tvdbId": added_series.get("tvdbId"),
                    "monitored": added_series.get("monitored"),
                    "status": added_series.get("status"),
                    "seasonCount": len(added_series.get("seasons", []))
                }
            }
            
        elif name == "delete_radarr_movie":
            movie_id = arguments["id"]
            delete_files = arguments.get("deleteFiles", False)
            add_import_exclusion = arguments.get("addImportExclusion", False)
            
            # Delete movie from Radarr
            params = {
                "deleteFiles": delete_files,
                "addImportExclusion": add_import_exclusion
            }
            
            # Radarr uses DELETE method with query parameters
            base_url = get_radarr_url(config)
            api_key = config["radarrConfig"]["apiKey"]
            headers = {"X-Api-Key": api_key}
            url = f"{base_url}/movie/{movie_id}"
            
            try:
                response = requests.delete(url, headers=headers, params=params, timeout=30)
                response.raise_for_status()
                
                result = {
                    "success": True,
                    "message": f"Movie with ID {movie_id} has been deleted from Radarr",
                    "deleteFiles": delete_files,
                    "addImportExclusion": add_import_exclusion
                }
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to delete movie: {e}")
                raise
            
        elif name == "update_radarr_movie":
            movie_id = arguments["id"]
            
            # First get the existing movie to preserve fields
            existing_movie = make_radarr_request(config, f"movie/{movie_id}")
            
            # Update only the provided fields
            if "monitored" in arguments:
                existing_movie["monitored"] = arguments["monitored"]
            if "qualityProfileId" in arguments:
                existing_movie["qualityProfileId"] = arguments["qualityProfileId"]
            if "minimumAvailability" in arguments:
                existing_movie["minimumAvailability"] = arguments["minimumAvailability"]
            if "tags" in arguments:
                existing_movie["tags"] = arguments["tags"]
            
            # Update movie in Radarr
            updated_movie = make_radarr_request(config, f"movie/{movie_id}", method="PUT", json_data=existing_movie)
            
            result = {
                "success": True,
                "message": f"Movie '{updated_movie.get('title')}' has been updated",
                "movie": {
                    "id": updated_movie.get("id"),
                    "title": updated_movie.get("title"),
                    "year": updated_movie.get("year"),
                    "monitored": updated_movie.get("monitored"),
                    "qualityProfileId": updated_movie.get("qualityProfileId"),
                    "minimumAvailability": updated_movie.get("minimumAvailability"),
                    "tags": updated_movie.get("tags", [])
                }
            }
            
        elif name == "update_sonarr_series":
            series_id = arguments["id"]
            
            # First get the existing series to preserve fields
            existing_series = make_sonarr_request(config, f"series/{series_id}")
            
            # Update only the provided fields
            if "monitored" in arguments:
                existing_series["monitored"] = arguments["monitored"]
            if "qualityProfileId" in arguments:
                existing_series["qualityProfileId"] = arguments["qualityProfileId"]
            if "seriesType" in arguments:
                existing_series["seriesType"] = arguments["seriesType"]
            if "seasonFolder" in arguments:
                existing_series["seasonFolder"] = arguments["seasonFolder"]
            if "tags" in arguments:
                existing_series["tags"] = arguments["tags"]
            
            # Update series in Sonarr
            updated_series = make_sonarr_request(config, f"series/{series_id}", method="PUT", json_data=existing_series)
            
            result = {
                "success": True,
                "message": f"Series '{updated_series.get('title')}' has been updated",
                "series": {
                    "id": updated_series.get("id"),
                    "title": updated_series.get("title"),
                    "year": updated_series.get("year"),
                    "monitored": updated_series.get("monitored"),
                    "qualityProfileId": updated_series.get("qualityProfileId"),
                    "seriesType": updated_series.get("seriesType"),
                    "seasonFolder": updated_series.get("seasonFolder"),
                    "tags": updated_series.get("tags", [])
                }
            }
            
        elif name == "get_radarr_movie_by_id":
            movie_id = arguments["id"]
            movie = make_radarr_request(config, f"movie/{movie_id}")
            
            result = {
                "movie": {
                    "id": movie.get("id"),
                    "title": movie.get("title"),
                    "year": movie.get("year"),
                    "tmdbId": movie.get("tmdbId"),
                    "imdbId": movie.get("imdbId"),
                    "overview": movie.get("overview"),
                    "status": movie.get("status"),
                    "monitored": movie.get("monitored"),
                    "hasFile": movie.get("hasFile", False),
                    "qualityProfileId": movie.get("qualityProfileId"),
                    "minimumAvailability": movie.get("minimumAvailability"),
                    "rootFolderPath": movie.get("rootFolderPath"),
                    "path": movie.get("path"),
                    "runtime": movie.get("runtime"),
                    "genres": movie.get("genres", []),
                    "ratings": movie.get("ratings", {}),
                    "sizeOnDisk": movie.get("sizeOnDisk", 0),
                    "tags": movie.get("tags", [])
                }
            }
            
        elif name == "get_radarr_movie_by_tmdb_id":
            tmdb_id = arguments["tmdbId"]
            
            # Get all movies and find the one with matching TMDB ID
            all_movies = make_radarr_request(config, "movie")
            movie = None
            for m in all_movies:
                if m.get("tmdbId") == tmdb_id:
                    movie = m
                    break
            
            if not movie:
                result = f"No movie found with TMDB ID {tmdb_id} in your Radarr library."
            else:
                result = {
                    "movie": {
                        "id": movie.get("id"),
                        "title": movie.get("title"),
                        "year": movie.get("year"),
                        "tmdbId": movie.get("tmdbId"),
                        "imdbId": movie.get("imdbId"),
                        "overview": movie.get("overview"),
                        "status": movie.get("status"),
                        "monitored": movie.get("monitored"),
                        "hasFile": movie.get("hasFile", False),
                        "qualityProfileId": movie.get("qualityProfileId"),
                        "minimumAvailability": movie.get("minimumAvailability"),
                        "rootFolderPath": movie.get("rootFolderPath"),
                        "path": movie.get("path"),
                        "runtime": movie.get("runtime"),
                        "genres": movie.get("genres", []),
                        "ratings": movie.get("ratings", {}),
                        "sizeOnDisk": movie.get("sizeOnDisk", 0),
                        "tags": movie.get("tags", [])
                    }
                }
            
        elif name == "get_sonarr_series_by_id":
            series_id = arguments["id"]
            series = make_sonarr_request(config, f"series/{series_id}")
            
            result = {
                "series": {
                    "id": series.get("id"),
                    "title": series.get("title"),
                    "year": series.get("year"),
                    "tvdbId": series.get("tvdbId"),
                    "imdbId": series.get("imdbId"),
                    "overview": series.get("overview"),
                    "status": series.get("status"),
                    "monitored": series.get("monitored"),
                    "qualityProfileId": series.get("qualityProfileId"),
                    "seriesType": series.get("seriesType"),
                    "seasonFolder": series.get("seasonFolder"),
                    "rootFolderPath": series.get("rootFolderPath"),
                    "path": series.get("path"),
                    "runtime": series.get("runtime"),
                    "genres": series.get("genres", []),
                    "ratings": series.get("ratings", {}),
                    "seasonCount": len(series.get("seasons", [])),
                    "totalEpisodeCount": series.get("statistics", {}).get("episodeCount", 0),
                    "episodeFileCount": series.get("statistics", {}).get("episodeFileCount", 0),
                    "sizeOnDisk": series.get("statistics", {}).get("sizeOnDisk", 0),
                    "tags": series.get("tags", [])
                }
            }
            
        elif name == "get_sonarr_episodes":
            series_id = arguments["seriesId"]
            season_number = arguments.get("seasonNumber")
            include_images = arguments.get("includeImages", False)
            
            # Get episodes for the series
            params = {"seriesId": series_id}
            if season_number is not None:
                params["seasonNumber"] = season_number
            if include_images:
                params["includeImages"] = True
                
            episodes = make_sonarr_request(config, "episode", params=params)
            
            result = {
                "count": len(episodes),
                "episodes": [
                    {
                        "id": ep.get("id"),
                        "seriesId": ep.get("seriesId"),
                        "episodeNumber": ep.get("episodeNumber"),
                        "seasonNumber": ep.get("seasonNumber"),
                        "title": ep.get("title"),
                        "airDate": ep.get("airDate"),
                        "airDateUtc": ep.get("airDateUtc"),
                        "overview": ep.get("overview", "")[:200] + "..." if len(ep.get("overview", "")) > 200 else ep.get("overview", ""),
                        "hasFile": ep.get("hasFile", False),
                        "monitored": ep.get("monitored"),
                        "episodeFileId": ep.get("episodeFileId"),
                        "absoluteEpisodeNumber": ep.get("absoluteEpisodeNumber")
                    }
                    for ep in episodes
                ]
            }
            
        elif name == "monitor_sonarr_episodes":
            episode_ids = arguments["episodeIds"]
            monitored = arguments["monitored"]
            
            # Prepare the update data
            update_data = {
                "episodeIds": episode_ids,
                "monitored": monitored
            }
            
            # Update episodes monitoring status
            make_sonarr_request(config, "episode/monitor", method="PUT", json_data=update_data)
            
            result = {
                "success": True,
                "message": f"Updated monitoring status for {len(episode_ids)} episodes",
                "episodeIds": episode_ids,
                "monitored": monitored
            }
            
        elif name == "get_sonarr_episode_files":
            series_id = arguments["seriesId"]
            
            # Get episode files for the series
            episode_files = make_sonarr_request(config, "episodefile", params={"seriesId": series_id})
            
            result = {
                "count": len(episode_files),
                "episodeFiles": [
                    {
                        "id": ef.get("id"),
                        "seriesId": ef.get("seriesId"),
                        "seasonNumber": ef.get("seasonNumber"),
                        "relativePath": ef.get("relativePath"),
                        "path": ef.get("path"),
                        "size": ef.get("size", 0),
                        "dateAdded": ef.get("dateAdded"),
                        "quality": ef.get("quality", {}),
                        "mediaInfo": ef.get("mediaInfo", {}),
                        "originalFilePath": ef.get("originalFilePath")
                    }
                    for ef in episode_files
                ]
            }
            
        elif name == "delete_sonarr_series":
            series_id = arguments["id"]
            delete_files = arguments.get("deleteFiles", False)
            add_import_list_exclusion = arguments.get("addImportListExclusion", False)
            
            # Delete series from Sonarr
            params = {
                "deleteFiles": delete_files,
                "addImportListExclusion": add_import_list_exclusion
            }
            
            # Sonarr uses DELETE method with query parameters
            base_url = get_sonarr_url(config)
            api_key = config["sonarrConfig"]["apiKey"]
            headers = {"X-Api-Key": api_key}
            url = f"{base_url}/series/{series_id}"
            
            try:
                response = requests.delete(url, headers=headers, params=params, timeout=30)
                response.raise_for_status()
                
                result = {
                    "success": True,
                    "message": f"Series with ID {series_id} has been deleted from Sonarr",
                    "deleteFiles": delete_files,
                    "addImportListExclusion": add_import_list_exclusion
                }
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to delete series: {e}")
                raise
            
        # Extended tools handlers
        elif name == "get_download_queue":
            result = handle_download_queue(config, arguments["service"], 
                                         arguments.get("includeUnknownItems", False))
            
        elif name == "remove_from_queue":
            result = handle_remove_from_queue(config, arguments["service"], arguments["id"],
                                            arguments.get("removeFromClient", True),
                                            arguments.get("blocklist", False))
            
        elif name == "get_history":
            result = handle_get_history(config, arguments["service"],
                                      arguments.get("pageSize", 50),
                                      arguments.get("page", 1),
                                      arguments.get("eventType"))
            
        elif name == "manual_import":
            result = handle_manual_import(config, arguments["service"], arguments["path"],
                                        arguments.get("movieId"), arguments.get("seriesId"))
            
        elif name == "get_radarr_calendar":
            # If no dates provided, use sensible defaults
            from datetime import datetime, timedelta
            start = arguments.get("start")
            end = arguments.get("end")
            if not start:
                start = datetime.now().strftime("%Y-%m-%d")
            if not end:
                end = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
            
            result = handle_calendar(config, "radarr", start, end, arguments.get("unmonitored", False))
            
        elif name == "get_sonarr_calendar":
            # If no dates provided, use sensible defaults
            from datetime import datetime, timedelta
            start = arguments.get("start")
            end = arguments.get("end")
            if not start:
                start = datetime.now().strftime("%Y-%m-%d")
            if not end:
                end = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
                
            result = handle_calendar(config, "sonarr", start, end, arguments.get("unmonitored", False))
            
        elif name == "get_wanted_missing":
            result = handle_wanted(config, arguments["service"], missing=True,
                                 page_size=arguments.get("pageSize", 50),
                                 page=arguments.get("page", 1),
                                 sort_key=arguments.get("sortKey"),
                                 sort_dir=arguments.get("sortDir"))
            
        elif name == "get_wanted_cutoff":
            result = handle_wanted(config, arguments["service"], missing=False,
                                 page_size=arguments.get("pageSize", 50),
                                 page=arguments.get("page", 1))
            
        elif name == "get_system_status":
            result = handle_system_status(config, arguments["service"])
            
        elif name == "get_disk_space":
            result = handle_disk_space(config, arguments["service"])
            
        elif name == "execute_command":
            result = handle_execute_command(config, arguments["service"], arguments["command"],
                                          arguments.get("movieId"), arguments.get("seriesId"))
            
        elif name == "get_collections":
            result = handle_get_collections(config, arguments.get("tmdbId"))
            
        elif name == "refresh_monitored":
            result = handle_refresh_monitored(config, arguments["service"])
            
        else:
            raise ValueError(f"Unknown tool: {name}")
            
        # Return result - string if already formatted, otherwise format it
        if isinstance(result, str):
            return [types.TextContent(type="text", text=result)]
        else:
            formatted_text = format_response(result, name)
            return [types.TextContent(type="text", text=formatted_text)]
        
    except Exception as e:
        logger.error(f"Tool call failed: {e}")
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """List available resources."""
    return [
        types.Resource(
            uri="radarr://movies",
            name="Radarr Movies",
            description="List of movies in Radarr",
            mimeType="application/json",
        ),
        types.Resource(
            uri="sonarr://series", 
            name="Sonarr Series",
            description="List of TV series in Sonarr",
            mimeType="application/json",
        )
    ]


@server.read_resource()
async def handle_read_resource(uri: str) -> str:
    """Read a resource."""
    config = load_config()
    
    # Convert URI to string if it's not already
    uri_str = str(uri)
    
    try:
        if uri_str == "radarr://movies":
            movies = make_radarr_request(config, "movie")
            result = {
                "count": len(movies),
                "movies": [
                    {
                        "id": m.get("id"),
                        "title": m.get("title"),
                        "year": m.get("year"),
                        "monitored": m.get("monitored"),
                        "hasFile": m.get("hasFile", False),
                        "status": m.get("status")
                    }
                    for m in movies
                ]
            }
            import json
            return json.dumps(result, indent=2)
            
        elif uri_str == "sonarr://series":
            series = make_sonarr_request(config, "series")
            result = {
                "count": len(series),
                "series": [
                    {
                        "id": s.get("id"),
                        "title": s.get("title"),
                        "year": s.get("year"),
                        "monitored": s.get("monitored"),
                        "status": s.get("status"),
                        "episodeCount": s.get("statistics", {}).get("episodeCount", 0),
                        "episodeFileCount": s.get("statistics", {}).get("episodeFileCount", 0)
                    }
                    for s in series
                ]
            }
            import json
            return json.dumps(result, indent=2)
            
        else:
            raise ValueError(f"Unknown resource: {uri_str}")
            
    except Exception as e:
        logger.error(f"Resource read failed: {e}")
        return f"Error: {str(e)}"


async def main():
    """Main entry point for the MCP server."""
    parser = argparse.ArgumentParser(description="Radarr/Sonarr MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="Transport type (default: stdio, or set MCP_TRANSPORT env var)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "127.0.0.1"),
        help="Host to bind to for SSE transport (default: 127.0.0.1; set MCP_HOST or --host to expose externally)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8080")),
        help="Port to bind to for SSE transport (default: 8080)",
    )
    args = parser.parse_args()

    try:
        pkg_version = importlib.metadata.version("radarr-sonarr-mcp")
    except importlib.metadata.PackageNotFoundError:
        pkg_version = "0.0.0"

    init_options = InitializationOptions(
        server_name="radarr-sonarr-mcp",
        server_version=pkg_version,
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )

    if args.transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Mount, Route
        import uvicorn

        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await server.run(streams[0], streams[1], init_options)
            return Response()

        app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )

        logger.info(f"Starting SSE server on {args.host}:{args.port}")
        config = uvicorn.Config(app, host=args.host, port=args.port)
        uvicorn_server = uvicorn.Server(config)
        await uvicorn_server.serve()
    else:
        # Run the server using stdin/stdout streams
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    asyncio.run(main())