"""Youtube Downloader Module"""

from pathlib import Path
from typing import Optional
import re

from spotifysaver.cli.commands.download import customOptions
from spotifysaver.services import YoutubeMusicSearcher, LrclibAPI
from spotifysaver.metadata import NFOGenerator
from spotifysaver.downloader.youtube_downloader import YouTubeDownloader
from spotifysaver.downloader.image_downloader import ImageDownloader
from spotifysaver.models import Track, Album, Playlist
from spotifysaver.enums import AudioFormat, Bitrate
from spotifysaver.spotlog import get_logger


class YouTubeDownloaderForCLI(YouTubeDownloader):
    """Downloads tracks from YouTube Music and adds Spotify metadata.

    This class handles the complete download process including audio download,
    metadata injection, lyrics fetching, and file organization.

    Attributes:
        base_dir: Base directory for music downloads
        searcher: YouTube Music searcher instance
        lrc_client: LRC Lib API client for lyrics
        image_downloader: Image downloader instance
    """

    def __init__(self, base_dir: str = "Music"):
        """Initialize the YouTube downloader.

        Args:
            base_dir: Base directory where music will be downloaded
        """
        self.logger = get_logger(f"{self.__class__.__name__}")
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
        self.searcher = YoutubeMusicSearcher()
        self.lrc_client = LrclibAPI()
        self.image_downloader = ImageDownloader()


    def _normalize_match_text(self, value: str) -> str:
        value = str(value or "").lower()
        value = re.sub(r"\([^)]*\)|\[[^]]*]", "", value)
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return " ".join(value.split())

    def _audio_files_under(self, output_dir: Path):
        audio_extensions = {".m4a", ".mp3", ".flac", ".opus", ".ogg", ".aac", ".wav"}
        for file_path in output_dir.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in audio_extensions:
                yield file_path

    def _read_audio_tags_for_match(self, file_path: Path) -> tuple[str, str]:
        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(file_path, easy=True)
            if not audio or not audio.tags:
                return "", ""

            title_values = audio.tags.get("title", [])
            artist_values = audio.tags.get("artist", []) or audio.tags.get("albumartist", [])

            title = title_values[0] if title_values else ""
            artist = artist_values[0] if artist_values else ""
            return str(title), str(artist)
        except Exception:
            return "", ""

    def _audio_file_looks_complete(self, file_path: Path, track: Track) -> bool:
        if not file_path.exists() or not file_path.is_file():
            return False

        # Tiny files are almost always failed/partial downloads.
        if file_path.stat().st_size <= 100_000:
            return False

        expected_duration = getattr(track, "duration", None)
        if not expected_duration:
            return True

        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(file_path)
            actual_duration = getattr(getattr(audio, "info", None), "length", None)
            if not actual_duration:
                return False

            # Allow normal source differences/intros/outros, but reject obvious partial files.
            return abs(float(actual_duration) - float(expected_duration)) <= 15
        except Exception:
            return False

    def _find_existing_playlist_track_by_metadata(
        self,
        output_dir: Path,
        track: Track,
        skipped_tracks_to_review: list[Track],
    ) -> Optional[Path]:
        expected_title = self._normalize_match_text(track.name)
        expected_artists = [self._normalize_match_text(artist) for artist in (track.artists or [])]

        fallback_filename_match = None
        incomplete_filename_match = None

        for file_path in self._audio_files_under(output_dir):
            normalized_file_stem = self._normalize_match_text(file_path.stem)
            filename_title_matches = expected_title and expected_title in normalized_file_stem

            if not self._audio_file_looks_complete(file_path, track):
                if filename_title_matches:
                    incomplete_filename_match = incomplete_filename_match or file_path
                continue

            tag_title, tag_artist = self._read_audio_tags_for_match(file_path)
            normalized_tag_title = self._normalize_match_text(tag_title)
            normalized_tag_artist = self._normalize_match_text(tag_artist)

            title_matches = normalized_tag_title == expected_title
            artist_matches = not expected_artists or any(
                artist and artist in normalized_tag_artist for artist in expected_artists
            )

            if title_matches and artist_matches:
                if file_path.stem.lower() != self._sanitize_filename(track.name).lower():
                    skipped_tracks_to_review.append(track)
                return file_path

            if title_matches and not artist_matches:
                skipped_tracks_to_review.append(track)

            if filename_title_matches:
                fallback_filename_match = fallback_filename_match or file_path

        if incomplete_filename_match:
            skipped_tracks_to_review.append(track)
            print(f"Re-downloading incomplete existing file: {track.name} -> {incomplete_filename_match}")
            return None


    def download_track_cli(
        self,
        track: Track,
        output_format: AudioFormat = AudioFormat.M4A,
        bitrate: Bitrate = Bitrate.B128,
        album_artist: str = None,
        download_lyrics: bool = False,
        progress_callback: Optional[callable] = None
    ) -> tuple[Optional[Path], Optional[Track]]:
        """
        Download a single track with CLI progress support.

        Args:
            track: Track object to download
            output_format: Audio format enum
            bitrate: Audio bitrate enum
            album_artist: Artist name for file organization
            download_lyrics: Whether to download lyrics
            progress_callback: Optional function for progress reporting.
                            Example: lambda idx, total, name: print(f"{idx}/{total} {name}")

        Returns:
            tuple: (Downloaded file path, Updated track) or (None, None) on error
        """
        try:
            if progress_callback:
                progress_callback(1, 1, track.name)

            yt_url = self.searcher.search_track(track)
            if not yt_url:
                raise ValueError(f"No se encontró en YouTube Music: {track.name}")

            audio_path, updated_track = self.download_track(
                track=track,
                album_artist=album_artist,
                download_lyrics=download_lyrics,
                output_format=output_format,
                bitrate=bitrate,
            )

            if audio_path:
                self.logger.info(f"Track descargado exitosamente: {track.name}")
                return audio_path, updated_track
            else:
                self.logger.warning(f"No se pudo descargar el track: {track.name}")
                return None, None

        except Exception as e:
            self.logger.error(f"Error al descargar el track {track.name}: {str(e)}", exc_info=True)
            return None, None

    def download_album_cli(
        self,
        album: Album,
        download_lyrics: bool = False,
        output_format: AudioFormat = AudioFormat.M4A,
        bitrate: Bitrate = Bitrate.B128,
        nfo: bool = False,  # Generate NFO
        cover: bool = False,  # Download cover art
        progress_callback: Optional[callable] = None,  # Progress callback
    ) -> tuple[int, int]:  # Returns (success, total)
        """Download a complete album with progress support.

        Args:
            album: Album object to download
            download_lyrics: Whether to download lyrics
            output_format: Audio format enum
            bitrate: Audio bitrate enum
            nfo: Whether to generate NFO file
            cover: Whether to download cover art
            progress_callback: Function that receives (current_track, total_tracks, track_name).
                            Example: lambda idx, total, name: print(f"{idx}/{total} {name}")

        Returns:
            tuple: (successful_downloads, total_tracks)
        """
        if not album.tracks:
            self.logger.error("Álbum no contiene tracks.")
            return 0, 0

        success = 0
        for idx, track in enumerate(album.tracks, 1):
            try:
                if progress_callback:
                    progress_callback(idx, len(album.tracks), track.name)

                yt_url = self.searcher.search_track(track)
                if not yt_url:
                    raise ValueError(f"No se encontró en YouTube Music: {track.name}")

                audio_path, _ = self.download_track(
                    track=track,
                    album_artist=album.artists[0],
                    download_lyrics=download_lyrics,
                    output_format=output_format,
                    bitrate=bitrate,
                )
                if audio_path:
                    success += 1
            except Exception as e:
                self.logger.error(f"Error en track {track.name}: {str(e)}")

        # Generar metadatos solo si hay éxitos
        if success > 0:
            output_dir = self._get_album_dir(album)
            if nfo:
                NFOGenerator.generate(album, output_dir)
            if cover and album.cover_url:
                self._save_cover_album(album.cover_url, output_dir / "cover.jpg")

            # Guarda el cover del artista
            # self._save_artist_cover()

        return success, len(album.tracks)

    def download_playlist_cli(
        self,
        playlist: Playlist,
        output_format: AudioFormat = AudioFormat.M4A,
        bitrate: Bitrate = Bitrate.B128,
        download_lyrics: bool = False,
        cover: bool = False,
        progress_callback: Optional[callable] = None,
        custom_options = None
    ) -> tuple[int, int]:
        """Download a complete playlist with progress bar support.

        Args:
            custom_options:
            playlist: Playlist object to download
            output_format: Audio format enum
            bitrate: Audio bitrate enum
            download_lyrics: Whether to download lyrics
            cover: Whether to download playlist cover
            progress_callback: Function that receives (current_track, total_tracks, track_name).
                            Example: lambda idx, total, name: print(f"{idx}/{total} {name}")

        Returns:
            tuple: (successful_downloads, total_tracks)
        """
        if not playlist.name or not playlist.tracks:
            self.logger.error("Playlist inválida: sin nombre o tracks vacíos")
            return 0, 0

        custom_options = custom_options or {}
        override_output_dir = custom_options.get(customOptions.OPTION_OVERWRITE_OUTPUT_DIR)
        output_dir_name = override_output_dir or playlist.name

        output_dir = self.base_dir / output_dir_name
        output_dir.mkdir(parents=True, exist_ok=True)
        self.base_dir = self.base_dir / output_dir_name
        print("output_dir: " + output_dir.name)
        success = 0
        skipped_tracks_to_review = []

        for idx, track in enumerate(playlist.tracks, 1):
            try:
                override_force = custom_options.get(customOptions.OPTION_OVERWRITE, False)
                existing_file = None
                # if override_force:
                #     existing_file = False
                # else:
                existing_file = self._find_existing_playlist_track_by_metadata(
                    output_dir=output_dir,
                    track=track,
                    skipped_tracks_to_review=skipped_tracks_to_review,
                )

                if existing_file and not override_force:
                    print(f"Skip: {track.name}")
                    self.logger.info(f"Skipping existing track: {existing_file.name}")
                    success += 1
                    continue

                if progress_callback:
                    progress_callback(idx, len(playlist.tracks), track.name)

                _, updated_track = self.download_track(
                    track,
                    album_artist=track.album_artist.__str__(),
                    output_format=output_format,
                    bitrate=bitrate,
                    download_lyrics=download_lyrics,
                )
                if updated_track:
                    success += 1
                    newTrackName = self._sanitize_filename(track.name) + existing_file.suffix
                    # if existing_file and override_force and existing_file.name != newTrackName:
                    #     existing_file.unlink()
                    #     print(f"Overwrite delete: -> {existing_file.name}")

            except Exception as e:
                self.logger.error(f"Error en {track.name}: {str(e)}")

        if skipped_tracks_to_review:
            force_download_report_path = output_dir / "tracks_to_force_download_later.txt"
            unique_tracks = []
            seen_uris = set()

            for skipped_track in skipped_tracks_to_review:
                track_uri = getattr(skipped_track, "uri", None) or repr(skipped_track)
                if track_uri in seen_uris:
                    continue
                seen_uris.add(track_uri)
                unique_tracks.append(skipped_track)

            force_download_report_path.write_text(
                "\n".join(repr(skipped_track) for skipped_track in unique_tracks)
            )
            self.logger.info(f"Wrote force-download track report: {force_download_report_path}")

        if success > 0 and cover and playlist.cover_url:
            try:
                self._save_cover_album(playlist.cover_url, output_dir / "cover.jpg")

            except Exception as e:
                self.logger.error(f"Error downloading playlist cover: {str(e)}")

        return success, len(playlist.tracks)
