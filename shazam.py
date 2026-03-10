import os
import sys
import asyncio
from datetime import datetime
import subprocess
import logging
import argparse
from concurrent.futures import ThreadPoolExecutor

from pydub import AudioSegment
from shazamio import Shazam
from yt_dlp import YoutubeDL

# Duration of each segment in milliseconds (1 minute)
SEGMENT_LENGTH = 60 * 1000

# Directory for downloaded files
DOWNLOADS_DIR = 'downloads'

# Logger setup 
logger = logging.getLogger('shazam_tool')

def setup_logging(debug_mode=False):
    """
    Configure logging based on debug mode.
    """
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
    minutes = total_seconds // 60
    seconds = total_seconds % 60
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


def segment_audio(audio_file: str, output_directory: str = "tmp", num_threads: int = 4) -> None:
    ensure_directory_exists(output_directory)
    try:
        audio = AudioSegment.from_file(audio_file, format="mp3")
        segments = [audio[i:i + SEGMENT_LENGTH] for i in range(0, len(audio), SEGMENT_LENGTH)]
        
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = []
            for idx, seg in enumerate(segments, start=1):
                segment_file_path = os.path.join(output_directory, f"{idx}.mp3")
                futures.append(executor.submit(seg.export, segment_file_path, format="mp3"))
            for future in futures:
                future.result()
    except Exception as e:
        logger.debug(f"Failed to segment audio file {audio_file}: {e}")


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
            # Shazam returns the offset within the submitted audio where match was found
            match_offset = data.get('timestamp', 0)
            result = f"{subtitle} - {title}"
            return (match_offset, result)

        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
                continue
            return (None, "Not found")


def process_audio_file(audio_file: str, output_filename: str, file_index: int, total_files: int) -> None:
    """Process audio: segment → recognize → precise timestamps via Shazam offset → consecutive dedup."""
    
    if total_files > 1:
        logger.info(f"\n[{file_index}/{total_files}] Processing: {audio_file}")
    else:
        logger.info(f"\nProcessing: {audio_file}")
    
    # Get audio duration for accurate timestamps
    try:
        audio = AudioSegment.from_file(audio_file, format="mp3")
        audio_duration_ms = len(audio)
    except:
        audio_duration_ms = 0
    
    last_track = None
    logger.info("1/4 🧹 Cleaning temporary files...")
    remove_files("tmp")

    logger.info("2/4 ✂️ Segmenting audio file...")
    segment_audio(audio_file, "tmp")

    logger.info("3/4 🔍 Recognizing segments...")
    tmp_files = sorted(os.listdir("tmp"), key=lambda x: int(os.path.splitext(x)[0]))
    total_segments = len(tmp_files)
    
    results = []  # List of (absolute_timestamp_ms, track_name)

    for idx, file_name in enumerate(tmp_files, start=1):
        segment_path = os.path.join("tmp", file_name)
        try:
            loop = asyncio.get_event_loop()
            match_offset_ms, track_name = loop.run_until_complete(recognize_segment(segment_path))
            
            if track_name == "Not found":
                logger.info(f"[{idx}/{total_segments}]: Not found")
                continue
            
            # Calculate absolute timestamp: segment start + Shazam's offset within segment
            segment_start_ms = (idx - 1) * SEGMENT_LENGTH
            
            # Shazam's offset is within the submitted 10-second sample, not the full segment
            # We add it to get the more precise timestamp
            absolute_timestamp_ms = segment_start_ms + match_offset_ms
            
            # Ensure we don't exceed audio length
            if audio_duration_ms > 0:
                absolute_timestamp_ms = min(absolute_timestamp_ms, audio_duration_ms)
            
            results.append((absolute_timestamp_ms, track_name))
            logger.info(f"[{idx}/{total_segments}]: {format_time(absolute_timestamp_ms)} {track_name}")
            
        except Exception as e:
            logger.debug(f"Error processing segment {file_name}: {e}")
            continue

    # 4th pass: Write results with consecutive deduplication
    logger.info("4/4 💾 Writing results (with consecutive dedup)...")
    
    for timestamp_ms, track_name in results:
        # Skip if same as previous track (consecutive dedup)
        if track_name == last_track:
            logger.debug(f"Skipping consecutive duplicate: {track_name}")
            continue
        
        last_track = track_name
        timestamp_str = format_time(timestamp_ms)
        output_line = f"{timestamp_str} {track_name}"
        write_to_file(output_line, output_filename)
        logger.info(f"✅ {output_line}")

    remove_files("tmp")
    logger.info(f"✅ Done! Found {len(results)} tracks (after dedup)")


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
    --debug        Enable debug logging
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

    # Handle URL/file arguments
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
