"""Playlist download command module for SpotifySaver CLI.

This module handles the download process for complete Spotify playlists,
including progress tracking and optional metadata generation.
"""

import click
import json
from pathlib import Path

from spotifysaver.cli.commands.download.customOptions import OPTION_SKIP_PLAYLIST, OPTION_VALUES, \
    OPTION_DOWNLOAD_FULL_ALBUM_FROM_SONG
from spotifysaver.downloader import YouTubeDownloader, YouTubeDownloaderForCLI
from spotifysaver.services import SpotifyAPI, YoutubeMusicSearcher, ScoreMatchCalculator
from spotifysaver.cli.commands.download.album import process_album


def _safe_nsp_filename(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else "_" for ch in name).strip()


# Helper for safe music path parts (for m3u8, etc.)
def _safe_music_path_part(value: str) -> str:
    value = str(value or "").strip()
    for bad_char in '<>:"/\\|?*':
        value = value.replace(bad_char, "_")
    return " ".join(value.split()).strip(". ")


# Path and file helpers for fuzzy matching
def _normalize_path_match_text(value: str) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").replace("-", " ").split())


def _audio_files_under(path: Path):
    audio_extensions = {".m4a", ".mp3", ".flac", ".opus", ".ogg", ".aac", ".wav"}
    if not path.exists():
        return

    for file_path in path.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in audio_extensions:
            yield file_path


def _spotify_track_to_nsp_rule(track):
    if not getattr(track, "artists", None) or not getattr(track, "name", None):
        return None

    return {
        "all": [
            {"is": {"artist": track.artists[0]}},
            {"is": {"title": track.name}},
        ]
    }


# Helpers for m3u8/NSP playlist generation
def _track_to_m3u8_path(track, root_folder_name: str) -> str | None:
    if not getattr(track, "name", None):
        return None

    folder_artist = None
    if getattr(track, "album_artist", None):
        folder_artist = track.album_artist[0]
    elif getattr(track, "artists", None):
        folder_artist = track.artists[0]

    if not folder_artist:
        folder_artist = "Unknown Artist"

    track_artist = ", ".join(str(artist) for artist in (getattr(track, "artists", None) or [])) or "Unknown Artist"
    album_name = getattr(track, "album_name", None) or "Unknown Album"
    year = str(getattr(track, "release_date", "") or "Unknown")[:4]
    track_number = str(getattr(track, "number", None) or 0).zfill(2)

    return "/".join(
        [
            _safe_music_path_part(root_folder_name),
            _safe_music_path_part(folder_artist),
            f"{_safe_music_path_part(album_name)} ({_safe_music_path_part(year)})",
            f"{track_number} - {_safe_music_path_part(track_artist)} - {_safe_music_path_part(track.name)}.m4a",
        ]
    )


# Helper to resolve actual m3u8 path for a track, searching if needed
def _resolve_existing_m3u8_path(track, music_library_dir, root_folder_name: str) -> str | None:
    expected_relative_path = _track_to_m3u8_path(track, root_folder_name=root_folder_name)
    if not expected_relative_path:
        return None

    if not music_library_dir:
        return expected_relative_path

    music_library_dir = Path(music_library_dir)
    expected_absolute_path = music_library_dir / expected_relative_path
    if expected_absolute_path.exists():
        return expected_relative_path

    search_root = music_library_dir / _safe_music_path_part(root_folder_name)
    if not search_root.exists():
        search_root = music_library_dir

    expected_title = _normalize_path_match_text(getattr(track, "name", ""))
    expected_artists = [
        _normalize_path_match_text(artist)
        for artist in (getattr(track, "artists", None) or [])
    ]

    for file_path in _audio_files_under(search_root):
        normalized_file_text = _normalize_path_match_text(file_path.stem)
        title_matches = expected_title and expected_title in normalized_file_text
        artist_matches = not expected_artists or any(
            artist and artist in normalized_file_text for artist in expected_artists
        )

        if title_matches and artist_matches:
            return file_path.relative_to(music_library_dir).as_posix()

    return None


def _append_playlist_rules_and_paths(
    playlist,
    nsp_rules: list,
    m3u8_lines: list,
    root_folder_name: str,
    music_library_dir=None,
    missing_m3u8_tracks: list | None = None,
):
    m3u8_lines.append(f"# Spotify playlist: {playlist.name}")

    for track in playlist.tracks:
        rule = _spotify_track_to_nsp_rule(track)
        if rule:
            rule["_spotify_playlist"] = playlist.name
            nsp_rules.append(rule)

        m3u8_path = _resolve_existing_m3u8_path(
            track=track,
            music_library_dir=music_library_dir,
            root_folder_name=root_folder_name,
        )
        if m3u8_path:
            m3u8_lines.append(m3u8_path)
        elif missing_m3u8_tracks is not None:
            missing_m3u8_tracks.append(track)

    m3u8_lines.append("")


def generate_nsp_playlist_flow(
    spotify: SpotifyAPI,
    playlist_url: str | list[str],
    output_dir,
    merged_playlist_name: str = "MergedSpotifyPlaylists",
    m3u8_root_folder_name: str | None = None,
    music_library_dir=None,
) -> tuple[Path, Path]:
    playlist_urls = playlist_url if isinstance(playlist_url, list) else [playlist_url]
    playlists = [spotify.get_playlist(url) for url in playlist_urls]
    playlists = [playlist for playlist in playlists if playlist]

    if not playlists:
        raise ValueError("No Spotify playlists found for NSP/M3U8 generation")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    merged = len(playlists) > 1
    playlist_file_name = merged_playlist_name if merged else playlists[0].name
    root_folder_name = m3u8_root_folder_name or playlist_file_name

    nsp_rules = []
    m3u8_lines = ["#EXTM3U"]
    missing_m3u8_tracks = []

    for playlist in playlists:
        _append_playlist_rules_and_paths(
            playlist=playlist,
            nsp_rules=nsp_rules,
            m3u8_lines=m3u8_lines,
            root_folder_name=root_folder_name,
            music_library_dir=music_library_dir,
            missing_m3u8_tracks=missing_m3u8_tracks,
        )

    nsp_data = {
        "_comment": "Generated from Spotify playlist(s). _spotify_playlist fields show source playlist names.",
        "_spotify_playlists": [playlist.name for playlist in playlists],
        "any": nsp_rules,
    }

    base_name = _safe_nsp_filename(playlist_file_name)
    nsp_path = output_dir / f"{base_name}.nsp"
    m3u8_path = output_dir / f"{base_name}.m3u8"

    nsp_path.write_text(json.dumps(nsp_data, indent=2, ensure_ascii=False), encoding="utf-8")
    m3u8_path.write_text("\n".join(m3u8_lines), encoding="utf-8")

    click.secho(
        f"\n✔ Generated NSP smart playlist with {len(nsp_rules)} rule(s): {nsp_path}",
        fg="green",
    )
    click.secho(
        f"✔ Generated M3U8 playlist with {len(nsp_rules)} track path(s): {m3u8_path}",
        fg="green",
    )

    if missing_m3u8_tracks:
        missing_path = output_dir / f"{base_name}-missing-m3u8-tracks.txt"
        missing_path.write_text(
            "\n".join(repr(track) for track in missing_m3u8_tracks),
            encoding="utf-8",
        )
        click.secho(
            f"⚠ M3U8 skipped {len(missing_m3u8_tracks)} missing track(s). Report: {missing_path}",
            fg="yellow",
        )

    return nsp_path, m3u8_path


def _get_album_url_for_track(spotify: SpotifyAPI, track):
    """Resolve a playlist Track to its Spotify album URL using the track URI."""
    track_uri = getattr(track, "uri", None)
    if not track_uri:
        return None

    raw_track = None

    if hasattr(spotify, "client") and hasattr(spotify.client, "track"):
        raw_track = spotify.client.track(track_uri)
    elif hasattr(spotify, "sp") and hasattr(spotify.sp, "track"):
        raw_track = spotify.sp.track(track_uri)
    elif hasattr(spotify, "spotify") and hasattr(spotify.spotify, "track"):
        raw_track = spotify.spotify.track(track_uri)

    if not raw_track:
        return None

    album = raw_track.get("album") or {}
    external_urls = album.get("external_urls") or {}
    album_url = external_urls.get("spotify")
    if album_url:
        return album_url

    album_id = album.get("id")
    if album_id:
        return f"https://open.spotify.com/album/{album_id}"

    return None


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

    download_full_album_from_song = bool(
        custom_options.get(OPTION_DOWNLOAD_FULL_ALBUM_FROM_SONG, False)
    )

    if download_full_album_from_song:
        album_urls_by_album = {}
        missing_album_tracks = []

        for track in playlist.tracks:
            album_url = _get_album_url_for_track(spotify, track)
            if not album_url:
                missing_album_tracks.append(track)
                continue

            album_urls_by_album.setdefault(album_url, []).append(track)

        if missing_album_tracks:
            click.secho(
                f"\n⚠ Could not resolve album for {len(missing_album_tracks)} track(s).",
                fg="yellow",
            )
            for track in missing_album_tracks[:10]:
                click.echo(f"  - {track.name} / {track.album_name}")

        if not album_urls_by_album:
            click.secho("\n⚠ No albums resolved from playlist tracks.", fg="yellow")
            return

        click.secho(
            f"\nDownloading {len(album_urls_by_album)} unique album(s) from playlist tracks",
            fg="magenta",
        )

        for album_url, tracks_from_album in album_urls_by_album.items():
            sample_track = tracks_from_album[0]
            click.echo(
                f"\nAlbum from playlist track: {sample_track.album_name} "
                f"({len(tracks_from_album)} playlist track(s) matched)"
            )
            process_album(
                spotify,
                searcher,
                downloader,
                album_url,
                lyrics,
                nfo,
                cover,
                output_format,
                bitrate,
                False,
                dry_run,
                custom_options,
            )

        return

    for idx, track in enumerate(playlist.tracks):
        album_url = _get_album_url_for_track(spotify, track)
        if not album_url:
            continue

        album = spotify.get_album(album_url)
        if not album or not album.tracks:
            continue

        for album_track in album.tracks:
            if album_track.name == track.name:
                playlist.tracks[idx] = track.with_track_number(album_track.number)
                break

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
            selected_candidate = explanation.get("yt_title") or explanation.get("title") or "No candidate returned"
            video_id = explanation.get("yt_videoId") or explanation.get("videoId") or "N/A"
            total_score = explanation.get("total_score", "N/A")
            passed = explanation.get("passed", False)

            click.echo(f"    Selected candidate: {selected_candidate}")
            click.echo(f"    Video ID: {video_id}")
            click.echo(f"    Total score: {total_score} (passed: {passed})")

            if selected_candidate == "No candidate returned":
                click.echo(f"    Raw explanation: {explanation}")
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
