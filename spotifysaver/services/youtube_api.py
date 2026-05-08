"""YouTube Music Searcher Service"""

from functools import lru_cache
from typing import List, Dict, Optional, Tuple

from ytmusicapi import YTMusic

from spotifysaver.models.track import Track
from spotifysaver.spotlog import get_logger
from spotifysaver.services.score_match_calculator import ScoreMatchCalculator
from spotifysaver.services.errors.errors import (
    YouTubeAPIError,
    AlbumNotFoundError,
    InvalidResultError,
)


class YoutubeMusicSearcher:
    """YouTube Music search service for finding tracks.
    
    This class provides functionality to search for tracks on YouTube Music
    using various strategies and scoring algorithms to find the best matches
    for Spotify tracks.
    
    Attributes:
        ytmusic: YTMusic API client instance
        max_retries: Maximum number of retry attempts for failed searches
    """
    
    def __init__(self):
        """Initialize the YouTube Music searcher.
        
        Sets up the YTMusic client and configures retry behavior.
        """
        self.ytmusic = YTMusic()
        self.scorer = ScoreMatchCalculator()
        self.max_retries = 3
        self.logger = get_logger(f"{self.__class__.__name__}")

    @staticmethod
    def _similar(a: str, b: str) -> float:
        """Calculate similarity between strings (0-1) using SequenceMatcher.
        
        Args:
            a: First string to compare
            b: Second string to compare
            
        Returns:
            float: Similarity ratio between 0.0 and 1.0
        """
        from difflib import SequenceMatcher

        return SequenceMatcher(None, a, b).ratio()

    @staticmethod
    def _normalize(text: str) -> str:
        """Consistent text normalization for comparison.
        
        Removes common words and characters that might interfere with matching.
        
        Args:
            text: Text to normalize
            
        Returns:
            str: Normalized text string
        """
        text = (
            text.lower()
            .replace("official", "")
            .replace("video", "")
            .translate(str.maketrans("", "", "()[]-"))
        )
        return " ".join([w for w in text.split() if w not in {"lyrics", "audio"}])

    @staticmethod
    def _result_text(result: Dict) -> str:
        artist_names = " ".join(
            artist.get("name", "") for artist in result.get("artists", []) if isinstance(artist, dict)
        )
        album_name = ""
        album = result.get("album")
        if isinstance(album, dict):
            album_name = album.get("name", "")

        return " ".join(
            str(value or "")
            for value in [
                result.get("title", ""),
                artist_names,
                album_name,
            ]
        ).lower()

    @staticmethod
    def _looks_clean_result(result: Dict) -> bool:
        text = YoutubeMusicSearcher._result_text(result)
        clean_terms = (
            "clean",
            "clean version",
            "radio edit",
            "edited",
            "censored",
            "censor",
            "no explicit",
        )
        return any(term in text for term in clean_terms)

    @staticmethod
    def _looks_explicit_result(result: Dict) -> bool:
        text = YoutubeMusicSearcher._result_text(result)
        explicit_terms = (
            "explicit",
            "uncensored",
            "dirty",
            "dirty version",
            "album version",
        )
        return any(term in text for term in explicit_terms)

    @staticmethod
    def _track_prefers_clean(track: Track) -> bool:
        track_text = f"{track.name or ''} {track.album_name or ''}".lower()
        return any(term in track_text for term in ("clean", "radio edit", "edited", "censored"))

    def _score_version_preference(self, score: float, result: Dict, track: Track) -> float:
        """Adjust score so clean and explicit variants are searched, but preferred intentionally."""
        prefers_clean = self._track_prefers_clean(track)
        looks_clean = self._looks_clean_result(result)
        looks_explicit = self._looks_explicit_result(result)

        adjusted_score = score
        if prefers_clean:
            if looks_clean:
                adjusted_score += 15
            if looks_explicit:
                adjusted_score -= 25
        else:
            # Default behavior: prefer explicit/uncensored versions and avoid clean/radio edits.
            if looks_explicit:
                adjusted_score += 15
            if looks_clean:
                adjusted_score -= 35

        return adjusted_score

    def _dedupe_results(self, results: List[Dict]) -> List[Dict]:
        deduped = []
        seen = set()

        for result in results:
            video_id = result.get("videoId")
            dedupe_key = video_id or f"{result.get('title')}::{self._result_text(result)}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            deduped.append(result)

        return deduped

    def _search_song_variants(
        self,
        base_query: str,
        limit_per_query: int,
        ignore_spelling: bool,
    ) -> List[Dict]:
        """Search base, explicit, and clean variants so scoring can choose the correct version."""
        queries = [
            base_query,
            f"{base_query} explicit",
            f"{base_query} uncensored",
            f"{base_query} clean",
            f"{base_query} radio edit",
        ]

        combined_results = []
        for query in queries:
            results = self.ytmusic.search(
                query=query,
                filter="songs",
                limit=limit_per_query,
                ignore_spelling=ignore_spelling,
            )
            self.logger.debug(f"Song variant search query='{query}' results={results}")
            combined_results.extend(results or [])

        return self._dedupe_results(combined_results)

    def _search_with_fallback(self, track: Track) -> Optional[str]:
        """Prioritized search strategy with multiple fallback methods.

        Tries different search strategies in order of reliability until
        a match is found.

        Args:
            track: Track object to search for

        Returns:
            str: YouTube Music URL if found, None otherwise
        """
        search_strategies = [
            self._search_exact_match,
            self._search_album_context,
            self._search_fuzzy_match,
        ]

        for strategy in search_strategies:
            if url := strategy(track):
                self.logger.info(
                    f"Found track: {track.name} by {track.artists[0]} using {strategy.__name__}"
                )
                return url
        self.logger.warning(f"No results found for {track.name} by {track.artists[0]}")
        return None

    def _search_exact_match(self, track: Track) -> Optional[str]:
        """Exact search with song filter.

        Args:
            track: Track object to search for

        Returns:
            str: YouTube Music URL if found, None otherwise
        """
        query = self._normalize(f"{track.artists[0]} {track.name} {track.album_name}")
        results = self._search_song_variants(
            base_query=query,
            limit_per_query=5,
            ignore_spelling=True,
        )
        self.logger.debug(f"Exact match combined search results: {results}")
        return self._process_results(results, track, strict=True)

    def _search_album_context(self, track: Track) -> Optional[str]:
        """Search for the album with detailed error handling.

        Args:
            track: Track object to search for

        Returns:
            str: YouTube Music URL if found, None otherwise

        Raises:
            AlbumNotFoundError: If the album cannot be found
            InvalidResultError: If the API returns invalid data
        """
        try:
            # Búsqueda del álbum
            album_results = self.ytmusic.search(
                query=self._normalize(f"{track.artists[0]} {track.name} {track.album_name}"),
                filter="albums",
                limit=1
            )

            if not album_results:
                raise AlbumNotFoundError(f"Album '{track.album_name}' not found")

            # Verificación de tipo
            if (
                not isinstance(album_results[0], dict)
                or "browseId" not in album_results[0]
            ):
                raise InvalidResultError("Invalid album search result format")

            # Obtención de tracks
            album_tracks = self.ytmusic.get_album(album_results[0]["browseId"]).get(
                "tracks", []
            )

            if not album_tracks:
                raise AlbumNotFoundError(
                    f"No tracks found in album '{track.album_name}'"
                )

            return self._process_results(album_tracks, track, strict=False)

        except YouTubeAPIError:
            raise
        except Exception as e:
            raise InvalidResultError(f"Unexpected error in album search: {str(e)}")

    def _search_fuzzy_match(self, track: Track) -> Optional[str]:
        """More flexible search when exact searches fail.

        Args:
            track: Track object to search for

        Returns:
            str: YouTube Music URL if found, None otherwise
        """
        results = self._search_song_variants(
            base_query=self._normalize(f"{track.artists[0]} {track.name} {track.album_name}"),
            limit_per_query=10,
            ignore_spelling=False,
        )
        return self._process_results(results, track, strict=False)

    def _process_results(
        self, results: List[Dict], track: Track, strict: bool
    ) -> Optional[str]:
        """Evaluate and select the best result.

        Args:
            results: List of search results from YouTube Music
            track: Original track to match against
            strict: Whether to use strict matching criteria

        Returns:
            str: YouTube Music URL of the best match, None if no valid matches
        """
        if not results:
            self.logger.warning(f"No results found for {track.name} by {track.artists[0]}")
            return None

        scored_results = []
        for result in results:
            base_score = self.scorer._calculate_match_score(result, track, strict)
            adjusted_score = self._score_version_preference(base_score, result, track)
            self.logger.debug(
                f"Score for {result.get('title', 'Unknown')} is {base_score}; adjusted version score is {adjusted_score}"
            )
            if adjusted_score > 0:
                scored_results.append((adjusted_score, result))

        if not scored_results:
            self.logger.warning(f"No valid matches found for {track.name} by {track.artists[0]}")
            return None

        scored_results.sort(reverse=True, key=lambda x: x[0])
        best_match = scored_results[0][1]
        self.logger.info(
            f"Best match for {track.name} by {track.artists[0]}: {best_match.get('title', 'Unknown')} with score {scored_results[0][0]}"
        )
        return f"https://music.youtube.com/watch?v={best_match['videoId']}"

    def search_raw(self, track: Track) -> List[Dict]:
        """Return raw YouTube Music search results for a given track."""
        query = f"{track.artists[0]} {track.name} {track.album_name or ''}"
        return self.ytmusic.search(query, filter="songs")

    @lru_cache(maxsize=100)
    def search_track(self, track: Track) -> Optional[str]:
        """Search for a track with elegant error handling.
        
        Main entry point for track searching with retry logic and caching.
        
        Args:
            track: Track object to search for
            
        Returns:
            str: YouTube Music URL if found, None if not found after all attempts
        """
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                return self._search_with_fallback(track)

            except AlbumNotFoundError as e:
                self.logger.warning(f"Attempt {attempt}: {str(e)}")
                last_error = e
            except InvalidResultError as e:
                self.logger.error(f"Attempt {attempt}: Invalid API response - {str(e)}")
                last_error = e
            except Exception as e:
                self.logger.error(f"Attempt {attempt}: Unexpected error - {str(e)}")
                last_error = e

        self.logger.error(f"All attempts failed for '{track.name}'")
        if last_error:
            self.logger.info(f"Last error details: {str(last_error)}")
        return None
