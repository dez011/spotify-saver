"""Main download command module for SpotifySaver CLI.

This module provides the primary download command that handles downloading
tracks, albums, or playlists from Spotify by finding matching content on
YouTube Music and applying Spotify metadata.
"""

from pathlib import Path

import json
def _parse_custom_options(ctx, param, value):
    if not value:
        return {}

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"custom options must be valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise click.BadParameter("custom options must be a JSON object/map")

    return parsed

import click

from spotifysaver.config import Config
from spotifysaver.services import SpotifyAPI, YoutubeMusicSearcher
from spotifysaver.downloader import YouTubeDownloaderForCLI
from spotifysaver.spotlog import LoggerConfig
from spotifysaver.cli.commands.download.album import process_album
from spotifysaver.cli.commands.download.playlist import process_playlist
from spotifysaver.cli.commands.download.track import process_track


def run_download(
    spotify_url: str,
    custom_options: dict | None = None,
):
    custom_options = custom_options or {}

    lyrics = custom_options.get("lyrics", False)
    nfo = custom_options.get("nfo", False)
    cover = custom_options.get("cover", False)
    output = custom_options.get("output", Config.OUTPUT_DIR)
    format = custom_options.get("format", "m4a")
    bitrate = custom_options.get("bitrate", 128)
    verbose = custom_options.get("verbose", False)
    explain = custom_options.get("explain", False)
    dry_run = custom_options.get("dry_run", False)

    LoggerConfig.setup(level="DEBUG" if verbose else "INFO")

    spotify = SpotifyAPI()
    searcher = YoutubeMusicSearcher()
    downloader = YouTubeDownloaderForCLI(base_dir=output)

    if "album" in spotify_url:
        process_album(
            spotify, searcher, downloader, spotify_url, lyrics, nfo, cover, format, bitrate, explain, dry_run
        )
    elif "playlist" in spotify_url:
        process_playlist(
            spotify,
            searcher,
            downloader,
            spotify_url,
            lyrics,
            nfo,
            cover,
            format,
            bitrate,
            dry_run=dry_run,
            custom_options=custom_options,
        )
    else:
        process_track(spotify, searcher, downloader, spotify_url, lyrics, format, bitrate, explain, dry_run)


@click.command("download")
@click.argument("spotify_url")
@click.option("--lyrics", is_flag=True, help="Download synced lyrics (.lrc)")
@click.option("--nfo", is_flag=True, help="Generate Jellyfin NFO file for albums")
@click.option("--cover", is_flag=True, help="Download album cover art")
@click.option("--output", type=Path, default=Config.OUTPUT_DIR, help="Output directory")#"Music", help="Output directory")
@click.option("--format", type=click.Choice(["m4a", "mp3", "opus"]), default="m4a")
@click.option("--bitrate", type=int, default=128, help="Audio bitrate in kbps")
@click.option("--verbose", is_flag=True, help="Show debug output")
@click.option("--explain", is_flag=True, help="Show score breakdown for each track without downloading (for error analysis)")
@click.option("--dry-run", is_flag=True, help="Simulate download without saving files")
@click.option(
    "--custom-options",
    "custom_options",
    callback=_parse_custom_options,
    default="{}",
    help="Custom options JSON map for advanced download behavior.",
)

def download(
    spotify_url: str,
    lyrics: bool,
    nfo: bool,
    cover: bool,
    output: Path,
    format: str,
    bitrate: int,
    verbose: bool,
    explain: bool,
    dry_run: bool,
    custom_options,
):
    """Download music from Spotify URLs via YouTube Music with metadata.

    This command downloads audio content from YouTube Music that matches
    Spotify tracks, albums, or playlists, then applies the original Spotify
    metadata to create properly organized music files.

    Args:
        spotify_url: Spotify URL for track, album, or playlist
        lyrics: Whether to download synchronized lyrics files
        nfo: Whether to generate Jellyfin-compatible metadata files
        cover: Whether to download album/playlist cover art
        output: Base directory for downloaded files
        format: Audio format for downloaded files
        bitrate: Audio bitrate in kbps (96, 128, 192, 256)
        verbose: Whether to show detailed debug information
        explain: Whether to show score breakdown for each track without downloading
    """
    download_options = dict(custom_options or {})
    download_options.update(
        {
            "lyrics": lyrics,
            "nfo": nfo,
            "cover": cover,
            "output": output,
            "format": format,
            "bitrate": bitrate,
            "verbose": verbose,
            "explain": explain,
            "dry_run": dry_run,
        }
    )

    try:
        run_download(spotify_url, download_options)

    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red", err=True)
        if verbose:
            import traceback

            traceback.print_exc()
        raise click.Abort()
