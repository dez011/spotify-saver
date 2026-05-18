"""Main entry point for the SpotifySaver application.
This module serves as the entry point for the SpotifySaver command-line interface.
"""

from spotifysaver.cli import cli
from spotifysaver.cli.commands.download import customOptions
from spotifysaver.cli.commands.download.download import run_download
from spotifysaver.cli.commands.download.playlist import generate_nsp_playlist_flow
from spotifysaver.services import SpotifyAPI


def run_programmatically():
    """
    Run SpotifySaver without CLI typing.
    Modify variables below instead of typing commands.
    """

    # ===== CONFIGURE THESE =====
    myLiked = "https://open.spotify.com/playlist/3eA5dShYiEIkczx6jyGsHA?si=a35d0623174c4ab8"
    japanese_kidsSongs = 'https://open.spotify.com/playlist/3fW5PULDGc41NYr6XrhuKU?si=sEOvVBh-Q6ezyX9g830Hjg&pi=9A0ef4HsTY6cB'
    mix90s00s = "https://open.spotify.com/playlist/3bWsQvhklcGg0BGW1OJw3K?si=58dd380d74174334"
    mixMex = 'https://open.spotify.com/playlist/37i9dQZF1DXbdrcAZnP3Cy?si=V5Swm6SeR0K1_a8X-wzYqQ&pi=I9LmuZAUSaC_5'
    # corridoMix = "https://open.spotify.com/playlist/1wGxIEQHkMv6ZJCh1Nw4uc?si=2f4cdd40b14b4aa6"
    # anpanmix = "https://open.spotify.com/playlist/06R4Lr3NLcZoL6pDYE77Zi?si=46bb7d1f66c34757"
    # disneyMix = "https://open.spotify.com/playlist/7iwn94y55JHOD1Wk87hfuY?si=e19323260ca44d22"
    hypeRunningRapMix = "https://open.spotify.com/playlist/2Dj4kbD9PqKAD1h0ChpXpb?si=333cd83fc65f4f18"
    japaneseClassics = "https://open.spotify.com/playlist/6z0WMXQyfzlcUJZv5oxKb2?si=1cc0986cfa3b4b6c"


    command = "download"  # options: download, inspect, init, etc.

    testing = False
    spotify_url = hypeRunningRapMix
    spotify_playlist_urls = [
        # corridoMix,
        # mix90s,
        # myLiked,
        # anpanmix,
        # disneyMix
    ]
    write_to_global_music = True
    overwrite_songs = False #false skips dups
    download_full_album = False
    generate_nsp_smart_playlist = False
    output_dir = None
    nsp_output_dir = None

    if testing:
        output_dir = "./musicTest"
        nsp_output_dir = "./smart-playlists"
    else:
        output_dir = "/Volumes/Disk1-14/DrivePool/Media/Plex/Music"
        nsp_output_dir = '/Volumes/Disk1-14/DrivePool/Media/Plex/Music/-Config'


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

    if write_to_global_music: #customOptions.OPTION_OVERWRITE_OUTPUT_DIR
        options["overwrite_output_dir"] = "MyLikedSongs"

    if download_full_album:
        options[customOptions.OPTION_DOWNLOAD_FULL_ALBUM_FROM_SONG] = True

    if generate_nsp_smart_playlist:
        generate_nsp_playlist_flow(
            spotify=SpotifyAPI(),
            playlist_url=spotify_playlist_urls,
            output_dir=nsp_output_dir,
            merged_playlist_name="AnpanDisney",
            m3u8_root_folder_name="MyLikedSongs",
        )
        return

    run_download(spotify_url, options)


if __name__ == "__main__":
    # Toggle this to switch between CLI and hardcoded mode
    USE_PROGRAMMATIC_MODE = True

    if USE_PROGRAMMATIC_MODE:
        run_programmatically()
    else:
        cli()
