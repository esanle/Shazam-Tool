import os
import sys
import asyncio
from datetime import datetime
import logging
import argparse

from pydub import AudioSegment
from shazamio import Shazam
from yt_dlp import YoutubeDL

COARSE_SEGMENT_MS = 60_000    # 1-minute segments for initial scan
PROBE_MS = 12_000             # 12-second clips for binary search probes
MIN_SEARCH_RANGE_MS = 15_000  # stop binary search when range <= 15s

DOWNLOADS_DIR = 'downloads'

logger = logging.getLogger('shazam_tool')


def setup_logging(debug_mode=False):
    log_level = logging.DEBUG if debug_mode else logging.INFO
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    logger.handlers = []
    logger.setLevel(log_level)

    ensure_directory_exists('logs')

    file_handler = logging.FileHandler('logs/app.log')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_format = '%(message)s' if not debug_mode else log_format
    console_handler.setFormatter(logging.Formatter(console_format))
    logger.addHandler(console_handler)


def ensure_directory_exists(dir_path: str) -> None:
    os.makedirs(dir_path, exist_ok=True)


def remove_files(directory: str) -> None:
    ensure_directory_exists(directory)
    for file_name in os.listdir(directory):
        file_path = os.path.join(directory, file_name)
        try:
            os.remove(file_path)
        except OSError as e:
            logger.error(f"Error deleting file {file_path}: {e}")


def format_time(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds) // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def write_to_file(data: str, filename: str) -> None:
    if data != "Not found":
        try:
            with open(filename, "a", encoding="utf-8") as f:
                f.write(f"{data}\n")
        except OSError as e:
            print(f"Error writing to file {filename}: {e}")


def download_soundcloud(url: str, output_path: str = DOWNLOADS_DIR) -> None:
    ensure_directory_exists(output_path)
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        logger.info("✅ Successfully downloaded from SoundCloud!")
    except Exception as e:
        logger.error(f"❌ Failed to download from SoundCloud {url}: {e}")


def download_youtube(url: str, output_path: str = DOWNLOADS_DIR) -> None:
    ensure_directory_exists(output_path)
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Unknown Title')
            logger.info(f"✅ Successfully downloaded: {title}!")
    except Exception as e:
        logger.error(f"❌ Error downloading from YouTube {url}: {e}")


def download_from_url(url: str) -> None:
    logger.info("🚀 Starting download...")
    lower_url = url.lower()
    if 'soundcloud.com' in lower_url:
        logger.info("🎵 SoundCloud URL detected")
        download_soundcloud(url)
    elif 'youtube.com' in lower_url or 'youtu.be' in lower_url:
        logger.info("🎥 YouTube URL detected")
        download_youtube(url)
    else:
        logger.error("❌ Unsupported URL format.")


async def recognize_segment(file_path: str, max_retries: int = 2) -> tuple:
    """Returns (match_offset_ms, 'Artist - Title') or (None, 'Not found')."""
    if not os.path.exists(file_path):
        return (None, "Not found")

    shazam = Shazam()
    for attempt in range(max_retries):
        try:
            data = await shazam.recognize(file_path)
            if 'track' not in data:
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5)
                    continue
                return (None, "Not found")

            title = data['track']['title']
            subtitle = data['track']['subtitle']
            match_offset = 0
            if data.get('matches'):
                match_offset = int(data['matches'][0].get('offset', 0) * 1000)
            return (match_offset, f"{subtitle} - {title}")

        except Exception:
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
                continue
            return (None, "Not found")


async def recognize_clip(audio: AudioSegment, start_ms: int, duration_ms: int = PROBE_MS) -> str:
    """Extract a short clip from audio at start_ms and recognize it via Shazam.
    Returns the track name string, or 'Not found'."""
    end_ms = min(start_ms + duration_ms, len(audio))
    if end_ms - start_ms < 5000:
        return "Not found"
    clip = audio[start_ms:end_ms]
    probe_path = os.path.join("tmp", f"_probe_{start_ms}.mp3")
    clip.export(probe_path, format="mp3")
    _, track = await recognize_segment(probe_path)
    try:
        os.remove(probe_path)
    except OSError:
        pass
    return track


async def binary_search_transition(
    audio: AudioSegment, left_ms: int, right_ms: int,
    left_track: str, right_track: str,
) -> int:
    """Binary search to find the transition point between two tracks.

    left_ms  — a position where left_track is known to be playing
    right_ms — a position where right_track is known to be playing

    Returns estimated start time (ms) of right_track, accurate to ~15s.
    """
    best_boundary = right_ms

    for iteration in range(8):
        if right_ms - left_ms <= MIN_SEARCH_RANGE_MS:
            break

        mid_ms = (left_ms + right_ms) // 2
        result = await recognize_clip(audio, mid_ms)
        logger.debug(f"    Binary #{iteration + 1}: {format_time(mid_ms)} → {result}")

        if result == right_track:
            best_boundary = mid_ms
            right_ms = mid_ms
        elif result == left_track:
            left_ms = mid_ms + PROBE_MS
        else:
            # Unknown / mixing zone — try a second probe slightly ahead
            alt_ms = mid_ms + PROBE_MS
            if alt_ms < right_ms:
                alt_result = await recognize_clip(audio, alt_ms)
                logger.debug(f"    Binary #{iteration + 1}b: {format_time(alt_ms)} → {alt_result}")
                if alt_result == right_track:
                    best_boundary = alt_ms
                    right_ms = alt_ms
                elif alt_result == left_track:
                    left_ms = alt_ms + PROBE_MS
                else:
                    best_boundary = mid_ms
                    break
            else:
                best_boundary = mid_ms
                break

    return best_boundary


async def _process_audio_async(
    audio_file: str, output_filename: str, file_index: int, total_files: int,
) -> None:
    if total_files > 1:
        logger.info(f"\n[{file_index}/{total_files}] Processing: {audio_file}")
    else:
        logger.info(f"\nProcessing: {audio_file}")

    logger.info("1/4 📂 Loading audio...")
    audio = AudioSegment.from_file(audio_file, format="mp3")
    duration_ms = len(audio)
    logger.info(f"    Duration: {format_time(duration_ms)}")

    ensure_directory_exists("tmp")
    remove_files("tmp")

    # ── Phase 1: Coarse scan (60s segments) ──────────────────────────
    logger.info("2/4 🔍 Coarse scan (60s segments)...")
    num_segments = (duration_ms + COARSE_SEGMENT_MS - 1) // COARSE_SEGMENT_MS
    coarse_results = []

    for i in range(num_segments):
        start_ms = i * COARSE_SEGMENT_MS
        end_ms = min(start_ms + COARSE_SEGMENT_MS, duration_ms)
        segment = audio[start_ms:end_ms]
        seg_path = os.path.join("tmp", f"coarse_{i}.mp3")
        segment.export(seg_path, format="mp3")
        _, track = await recognize_segment(seg_path)
        coarse_results.append((start_ms, track))
        icon = "❌" if track == "Not found" else "✅"
        logger.info(f"  [{i + 1}/{num_segments}] {format_time(start_ms)} {icon} {track}")
        try:
            os.remove(seg_path)
        except OSError:
            pass

    # ── Phase 2: Build track runs (consecutive dedup, skip Not found) ─
    # Each run: (first_segment_start_ms, last_segment_start_ms, track_name)
    track_runs = []
    for start_ms, track in coarse_results:
        if track == "Not found":
            continue
        if track_runs and track_runs[-1][2] == track:
            track_runs[-1] = (track_runs[-1][0], start_ms, track)
        else:
            track_runs.append((start_ms, start_ms, track))

    if not track_runs:
        logger.warning("❌ No tracks identified!")
        remove_files("tmp")
        return

    logger.info(f"    Identified {len(track_runs)} unique track(s)")

    # ── Phase 3: Binary search to refine each boundary ───────────────
    logger.info("3/4 🎯 Refining boundaries (binary search, ~12s probes)...")
    refined = []

    for i, (first_ms, last_ms, track) in enumerate(track_runs):
        if i == 0:
            if first_ms == 0:
                refined.append((0, track))
                logger.info(f"  Track 1: {track} @ 00:00")
            else:
                boundary = await binary_search_transition(
                    audio, 0, first_ms + COARSE_SEGMENT_MS, "Not found", track,
                )
                refined.append((boundary, track))
                logger.info(f"  Track 1: {track} @ {format_time(boundary)}")
        else:
            prev_first, prev_last, prev_track = track_runs[i - 1]
            search_left = prev_last
            search_right = min(first_ms + COARSE_SEGMENT_MS, duration_ms)

            logger.info(f"  Boundary: {prev_track} → {track}")
            logger.info(f"    Search range: {format_time(search_left)} – {format_time(search_right)}")

            boundary = await binary_search_transition(
                audio, search_left, search_right, prev_track, track,
            )
            refined.append((boundary, track))
            logger.info(f"  Track {i + 1}: {track} @ {format_time(boundary)}")

    # ── Phase 4: Write results ───────────────────────────────────────
    logger.info("4/4 💾 Writing results...")
    for timestamp_ms, track in refined:
        ts = format_time(timestamp_ms)
        line = f"{ts} {track}"
        write_to_file(line, output_filename)
        logger.info(f"  ✅ {line}")

    remove_files("tmp")
    logger.info(f"✨ Done! {len(refined)} tracks with ~10-15s timestamp precision")


def process_audio_file(
    audio_file: str, output_filename: str, file_index: int, total_files: int,
) -> None:
    """Process audio: coarse 60s scan → binary search refinement → precise tracklist."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(
        _process_audio_async(audio_file, output_filename, file_index, total_files)
    )


def process_downloads() -> None:
    """Process all MP3 files in DOWNLOADS_DIR."""
    output_dir = "recognised-lists"
    ensure_directory_exists(output_dir)
    ensure_directory_exists(DOWNLOADS_DIR)

    mp3_files = [f for f in os.listdir(DOWNLOADS_DIR) if f.endswith('.mp3')]
    if not mp3_files:
        logger.warning(f"❌ No MP3 files found in '{DOWNLOADS_DIR}'.")
        return

    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    output_filename = os.path.join(output_dir, f"songs-{timestamp}.txt")

    total_files = len(mp3_files)
    logger.info(f"📝 Found {total_files} MP3 file(s) to process...")
    logger.info("🚀 Starting processing...")

    for idx, file_name in enumerate(mp3_files, start=1):
        full_path = os.path.join(DOWNLOADS_DIR, file_name)
        process_audio_file(full_path, output_filename, idx, total_files)

    logger.info(f"\n✨ All files processed!")
    logger.info(f"📋 Results saved to {output_filename}")


def print_usage():
    print("""
🎵 Shazam Tool 🎵

Usage: python shazam.py [command] [options]

Commands:
    scan           Scan downloads directory
    download <url> Download from YouTube/SoundCloud
    recognize <file> Recognize specific file

Options:
    --debug        Enable debug logging (shows binary search steps)
    """)


def main():
    parser = argparse.ArgumentParser(description='Shazam Tool', add_help=False)
    parser.add_argument('command', nargs='?', help='scan, download, or recognize')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('url_or_file', nargs='?', help='URL or file path')

    args, unknown = parser.parse_known_args()

    if not args.command:
        print_usage()
        sys.exit(1)

    setup_logging(args.debug)

    command = args.command
    output_dir = "recognised-lists"
    ensure_directory_exists(output_dir)
    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    output_filename = os.path.join(output_dir, f"songs-{timestamp}.txt")

    if command in ['download', 'recognize']:
        start_idx = 2
        if '--debug' in sys.argv:
            start_idx += 1
        url_or_file = ' '.join(sys.argv[start_idx:]) if len(sys.argv) > start_idx else None
    else:
        url_or_file = args.url_or_file

    if command == 'download':
        if not url_or_file:
            logger.error("Missing URL.")
            sys.exit(1)
        download_from_url(url_or_file)
        process_downloads()

    elif command in ['scan', 'scan-downloads']:
        process_downloads()

    elif command == 'recognize':
        if not url_or_file:
            logger.error("Missing file path.")
            sys.exit(1)

        audio_file = url_or_file
        if audio_file.startswith('http://') or audio_file.startswith('https://'):
            download_from_url(audio_file)
            mp3_files = [f for f in os.listdir(DOWNLOADS_DIR) if f.endswith('.mp3')]
            if not mp3_files:
                sys.exit(1)
            latest_file = max([os.path.join(DOWNLOADS_DIR, f) for f in mp3_files], key=os.path.getmtime)
            process_audio_file(latest_file, output_filename, 1, 1)
        else:
            if not os.path.exists(audio_file):
                logger.error(f"File not found: {audio_file}")
                sys.exit(1)
            process_audio_file(audio_file, output_filename, 1, 1)

        logger.info(f"\nResults saved to {output_filename}")

    else:
        logger.error(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
