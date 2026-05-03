"""Playlist download command module for SpotifySaver CLI.

This module handles the download process for complete Spotify playlists,
including progress tracking and optional metadata generation.
"""

import click

from spotifysaver.cli.commands.download.customOptions import OPTION_SKIP_PLAYLIST, OPTION_VALUES
from spotifysaver.downloader import YouTubeDownloader, YouTubeDownloaderForCLI
from spotifysaver.services import SpotifyAPI, YoutubeMusicSearcher, ScoreMatchCalculator


def process_playlist(spotify: SpotifyAPI, searcher: YoutubeMusicSearcher, downloader: YouTubeDownloaderForCLI, url,
                     lyrics, nfo, cover, output_format, bitrate, dry_run=False, custom_options=None):
    """Process and download a complete Spotify playlist with progress tracking.

    Downloads all tracks from a Spotify playlist, showing a progress bar and
    handling optional features like lyrics and cover art. NFO generation for
    playlists is currently in development.

    Args:
        spotify: SpotifyAPI instance for fetching playlist data
        searcher: YoutubeMusicSearcher for finding YouTube matches
        downloader: YouTubeDownloader for downloading and processing files
        url: Spotify playlist URL
        lyrics: Whether to download synchronized lyrics
        nfo: Whether to generate metadata files (in development)
        cover: Whether to download playlist cover art
        output_format: Audio format for downloaded files
        custom_options: Custom options map for playlist behavior
    """
    if custom_options is None:
        custom_options = {}

    skip_playlist_option = custom_options.get(OPTION_SKIP_PLAYLIST, {})
    if isinstance(skip_playlist_option, dict):
        skip_playlist_names = skip_playlist_option.get(OPTION_VALUES, [])
    else:
        skip_playlist_names = skip_playlist_option or []

    playlist = spotify.get_playlist(url)
    click.secho(f"\nDownloading playlist: {playlist.name}", fg="magenta")

    if playlist.name in skip_playlist_names:
        click.secho(f"\nSkipping playlist by exact name match: {playlist.name}", fg="cyan")
        return

    # Dry run mode: explain matches without downloading
    if dry_run:
        scorer = ScoreMatchCalculator()
        output_dir = downloader.base_dir / playlist.name
        click.secho(f"\n🧪 Dry run for playlist: {playlist.name}", fg="magenta")

        for track in playlist.tracks:
            skipped_tracks_to_review = []
            existing_file = downloader._find_existing_playlist_track_by_metadata(
                output_dir=output_dir,
                track=track,
                skipped_tracks_to_review=skipped_tracks_to_review,
                skip_playlist_names=skip_playlist_names,
            )

            click.secho(f"\n🎵 Track: {track.name}", fg="yellow")

            if existing_file:
                click.secho(f"  → DRY RUN SKIP: existing valid file found", fg="cyan")
                click.echo(f"    File: {existing_file}")
                continue

            if skipped_tracks_to_review:
                click.secho(f"  → DRY RUN DOWNLOAD: existing match looked incomplete or needs review", fg="red")
            else:
                click.secho(f"  → DRY RUN DOWNLOAD: no existing valid match found", fg="green")

            result = searcher.search_track(track)
            explanation = scorer.explain_score(result, track, strict=True)
            click.echo(f"    Selected candidate: {explanation['yt_title']}")
            click.echo(f"    Video ID: {explanation['yt_videoId']}")
            click.echo(f"    Total score: {explanation['total_score']} (passed: {explanation['passed']})")
        return

    # Configure progress bar
    with click.progressbar(
        length=len(playlist.tracks),
        label="  Processing",
        fill_char="█",
        show_percent=True,
        item_show_func=lambda t: t.name[:25] + "..." if t else "",
    ) as bar:

        def update_progress(idx, total, name):
            bar.label = (
                f"  Downloading: {name[:20]}..."
                if len(name) > 20
                else f"  Downloading: {name}"
            )
            bar.update(1)

        # Delegate everything to the downloader
        success, total = downloader.download_playlist_cli(
            playlist,
            download_lyrics=lyrics,
            output_format=YouTubeDownloader.string_to_audio_format(output_format),
            bitrate=YouTubeDownloader.int_to_bitrate(bitrate),
            cover=cover,
            progress_callback=update_progress,
            custom_options=custom_options,
        )

    # Display results
    if success > 0:
        click.secho(f"\n✔ Downloaded {success}/{total} tracks", fg="green")
        if nfo:
            click.secho(
                f"\nGenerating NFO for playlist: method in development", fg="magenta"
            )
            # generate_nfo_for_playlist(downloader, playlist, cover)
    else:
        click.secho("\n⚠ No tracks downloaded", fg="yellow")


def generate_nfo_for_playlist(downloader, playlist, cover=False):
    """Generate NFO metadata file for a playlist (similar to albums).
    
    Creates a Jellyfin-compatible NFO file with playlist metadata and optionally
    downloads the playlist cover art. This function is currently in development.
    
    Args:
        downloader: YouTubeDownloader instance for file operations
        playlist: Playlist object with metadata
        cover: Whether to download playlist cover art
    """
    try:
        from spotifysaver.metadata import NFOGenerator

        playlist_dir = downloader.base_dir / playlist.name
        NFOGenerator.generate_playlist(playlist, playlist_dir)

        if cover and playlist.cover_url:
            cover_path = playlist_dir / "cover.jpg"
            if not cover_path.exists():
                downloader._save_cover_album(playlist.cover_url, cover_path)
                click.secho(f"✔ Saved playlist cover: {cover_path}", fg="green")

        click.secho(
            f"\n✔ Generated playlist metadata: {playlist_dir}/playlist.nfo", fg="green"
        )
    except Exception as e:
        click.secho(f"\n⚠ Failed to generate NFO: {str(e)}", fg="yellow")
