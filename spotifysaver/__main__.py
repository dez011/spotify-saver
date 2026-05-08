"""Main entry point for the SpotifySaver application.
This module serves as the entry point for the SpotifySaver command-line interface.
"""

from spotifysaver.cli import cli
from spotifysaver.cli.commands.download import customOptions
from spotifysaver.cli.commands.download.download import run_download


def run_programmatically():
    """
    Run SpotifySaver without CLI typing.
    Modify variables below instead of typing commands.
    """

    # ===== CONFIGURE THESE =====
    command = "download"  # options: download, inspect, init, etc.
    testing = True
    spotify_url = "https://open.spotify.com/playlist/3eA5dShYiEIkczx6jyGsHA?si=a35d0623174c4ab8"
    output_dir = None

    if testing:
        output_dir = "./musicTest"
    else:
        output_dir = "/Volumes/Disk1-14/DrivePool/Media/Plex/Music/Explicit"
    write_to_global_music = True
    overwrite_songs = True
    download_full_album = True

    options = {
        "output": output_dir,
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
    }
    if overwrite_songs:
        options["overwrite"] = True

    if write_to_global_music:
        options["overwrite_output_dir"] = "MyLikedSongs"
#     output_dir = "/Volumes/Disk1-14/DrivePool/Media/Plex/Music/Explicit"

    if download_full_album:
        options[customOptions.OPTION_DOWNLOAD_FULL_ALBUM_FROM_SONG] = True

    run_download(spotify_url, options)


if __name__ == "__main__":
    # Toggle this to switch between CLI and hardcoded mode
    USE_PROGRAMMATIC_MODE = True

    if USE_PROGRAMMATIC_MODE:
        run_programmatically()
    else:
        cli()
