# Shazam Tool

Identify every track in a DJ mix — automatically.

Paste a YouTube or SoundCloud link, get a timestamped tracklist ready to drop in the comments. Built for the tracklist culture: the people who ID every song in a Boiler Room set, festival recordings, or radio shows so everyone can find that one track they fell in love with at 1:37:00.

## How It Works

1. **Coarse scan** — splits audio into 60-second segments and identifies each via Shazam
2. **Binary search refinement** — narrows down track transition points to ~10–15 second accuracy
3. **Deduplication** — consecutive duplicate detections are merged into single entries

## Requirements

- Python 3.11+
- ffmpeg

### macOS

```sh
brew install ffmpeg python@3.12
```

### Linux

```sh
sudo apt install ffmpeg python3
```

### Python dependencies

```sh
pip install shazamio pydub yt-dlp
```

## Usage

### Shell script (recommended)

```sh
./run_shazam.sh setup              # create venv, install deps
./run_shazam.sh download <url>     # download + identify
./run_shazam.sh scan               # identify all files in downloads/
./run_shazam.sh recognize <file>   # identify a single file
./run_shazam.sh help
```

### Direct Python

```sh
python shazam.py download <url>       # download from YouTube/SoundCloud + identify
python shazam.py scan                 # identify all MP3s in downloads/
python shazam.py recognize <file>     # identify a single local file
python shazam.py recognize <url>      # download then identify a single file
python shazam.py recognize <file> --debug   # verbose output (shows binary search steps)
```

The `--debug` flag works with any command and logs binary search probes and segment details.

## Output

Results are saved to `recognised-lists/songs-DDMMYY-HHMMSS.txt` — timestamps are YouTube-comment ready (clickable when pasted):

```
00:00 Karl Jenkins - Adiemus
01:30 Paperclip People - Throw (Slam's RTM Remix)
02:15 Richard Ulh - Bumping
04:24 Boogietraxx & Milton Shadow - The Hearing Test
08:00 Blaze & Bicep - Lovelee Dae (Bicep Remix)
```

Copy-paste directly into a YouTube comment and the timestamps become clickable links.

You can also import the tracklist into [TuneMyMusic](https://www.tunemymusic.com/) to create a playlist on Spotify, Apple Music, etc.

## Project Structure

```
shazam.py            # main script
run_shazam.sh        # convenience wrapper
downloads/           # downloaded audio (gitignored)
recognised-lists/    # output tracklists (gitignored)
logs/                # app.log for debugging (gitignored)
tmp/                 # temporary segments during processing (auto-cleaned)
```

## Why This Exists

You know when you're deep in a 3-hour festival set on YouTube and a track hits so hard you *need* to know what it is? You scroll to the comments hoping someone posted a tracklist... and nobody did.

This tool is for those moments. Point it at the video, let it run, and post the tracklist yourself. Be the hero in the comments.

Works great with:
- Boiler Room sets
- Festival recordings (Tomorrowland, Cercle, etc.)
- SoundCloud DJ mixes
- Radio show recordings (BBC Radio 1, Rinse FM, etc.)
- Any long-form audio with multiple tracks

## Contributing

Issues and PRs welcome.
