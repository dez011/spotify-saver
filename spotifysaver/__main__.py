"""Main entry point for the SpotifySaver application.
This module serves as the entry point for the SpotifySaver command-line interface.
"""

from spotifysaver.cli import cli
from spotifysaver.cli.commands.download.download import run_download


def run_programmatically():
    """
    Run SpotifySaver without CLI typing.
    Modify variables below instead of typing commands.
    """

    # ===== CONFIGURE THESE =====
    command = "download"  # options: download, inspect, init, etc.
    spotify_url = "https://open.spotify.com/playlist/3eA5dShYiEIkczx6jyGsHA?si=a35d0623174c4ab8"

    options = {
        "output": "./musicTest",
        "skip_playlist": {
            "values": [
                # "SomeOldPlaylist",
                # "Another Playlist",
                # "MyLikedSongs",
            ],
        },
        # "format": "mp3",
        # "quality": "320",
        # "dry_run": True,
        "overwrite": True,
    }



    run_download(spotify_url, options)


if __name__ == "__main__":
    # Toggle this to switch between CLI and hardcoded mode
    USE_PROGRAMMATIC_MODE = True

    if USE_PROGRAMMATIC_MODE:
        run_programmatically()
    else:
        cli()
