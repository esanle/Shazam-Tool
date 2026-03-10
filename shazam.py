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
# Binary search precision: 5 seconds
BINARY_SEARCH_STEP = 5 * 1000

# Directory for downloaded files
DOWNLOADS_DIR = 'downloads'

# Logger setup 
logger = logging.getLogger('shazam_tool')

def setup_logging(debug_mode=False):
    """
    Configure logging based on debug mode.
    When debug mode is enabled, detailed logs are written to both console and file.
    """
    log_level = logging.DEBUG if debug_mode else logging.INFO
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Reset handlers if they exist
    logger.handlers = []
    logger.setLevel(log_level)
    
    # Ensure logs directory exists
    ensure_directory_exists('logs')
    
    # File handler - always logs at DEBUG level to app.log
    file_handler = logging.FileHandler('logs/app.log')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(file_handler)
    
    # Console handler - level depends on debug_mode
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    
    # Use simpler format for console if not in debug mode
    if not debug_mode:
        console_format = '%(message)s'
    else:
        console_format = log_format
        
    console_handler.setFormatter(logging.Formatter(console_format))
    logger.addHandler(console_handler)
    
    if debug_mode:
        logger.debug("Debug mode enabled - detailed logging activated")


def ensure_directory_exists(dir_path: str) -> None:
    """
    Checks if directory exists, creates it if it doesn't.
    """
    os.makedirs(dir_path, exist_ok=True)
    logger.debug(f"Ensured directory exists: {dir_path}")


def remove_files(directory: str) -> None:
    """
    Removes all files in specified directory. If directory doesn't exist,
    it will be created.
    """
    ensure_directory_exists(directory)
    file_count = 0
    for file_name in os.listdir(directory):
        file_path = os.path.join(directory, file_name)
        try:
            os.remove(file_path)
            file_count += 1
        except OSError as e:
            logger.error(f"Error deleting file {file_path}: {e}")
    logger.debug(f"Removed {file_count} files from {directory}")


def format_time(milliseconds: int) -> str:
    """
    Convert milliseconds to mm:ss format.
    """
    total_seconds = milliseconds // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def write_to_file(data: str, filename: str) -> None:
    """
    Appends text string to specified file if data != 'Not found'.
    """
    if data != "Not found":
        try:
            with open(filename, "a", encoding="utf-8") as f:
                f.write(f"{data}\n")
        except OSError as e:
            print(f"Error writing to file {filename}: {e}")


def download_soundcloud(url: str, output_path: str = DOWNLOADS_DIR) -> None:
    """
    Download audio from a SoundCloud URL using yt-dlp.
    """
    ensure_directory_exists(output_path)
    logger.debug(f"Attempting to download from SoundCloud: {url}")
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        logger.info("✅ Successfully downloaded from SoundCloud!")
    except Exception as e:
        logger.error(f"❌ Failed to download from SoundCloud {url}: {e}")


def download_youtube(url: str, output_path: str = DOWNLOADS_DIR) -> None:
    """
    Download the audio track from a YouTube video and convert to mp3 using yt-dlp.
    """
    ensure_directory_exists(output_path)
    logger.debug(f"Attempting to download from YouTube: {url}")
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Unknown Title')
            logger.info(f"✅ Successfully downloaded: {title}!")
    except Exception as e:
        logger.error(f"❌ Error downloading from YouTube {url}: {e}")


def download_from_url(url: str) -> None:
    """
    Determines if URL is YouTube or SoundCloud and calls appropriate download function.
    """
    logger.info("🚀 Starting download...")
    lower_url = url.lower()
    logger.debug(f"Processing URL: {url}")
    if 'soundcloud.com' in lower_url:
        logger.info("🎵 SoundCloud URL detected")
        download_soundcloud(url)
    elif 'youtube.com' in lower_url or 'youtu.be' in lower_url:
        logger.info("🎥 YouTube URL detected")
        download_youtube(url)
    else:
        logger.error("❌ Unsupported URL format. Please provide a YouTube or SoundCloud link.")


def segment_audio(audio_file: str, output_directory: str = "tmp", num_threads: int = 4) -> None:
    """
    Segments MP3 file into chunks of SEGMENT_LENGTH duration (in milliseconds)
    using parallel processing.
    """
    ensure_directory_exists(output_directory)
    logger.debug(f"Segmenting audio file: {audio_file} with {num_threads} threads")
    try:
        audio = AudioSegment.from_file(audio_file, format="mp3")
        segments = [audio[i:i + SEGMENT_LENGTH] for i in range(0, len(audio), SEGMENT_LENGTH)]
        total_segments = len(segments)
        logger.debug(f"Created {total_segments} segments of {SEGMENT_LENGTH}ms each")

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = []
            for idx, seg in enumerate(segments, start=1):
                segment_file_path = os.path.join(output_directory, f"{idx}.mp3")
                futures.append(
                    executor.submit(seg.export, segment_file_path, format="mp3")
                )

            for future in futures:
                future.result()

    except Exception as e:
        logger.debug(f"Failed to segment audio file {audio_file}: {e}")


def extract_segment(audio_file: str, start_ms: int, duration_ms: int, output_path: str) -> None:
    """
    Extract a segment from an audio file.
    """
    try:
        audio = AudioSegment.from_file(audio_file, format="mp3")
        # Handle case where start is beyond audio length
        if start_ms >= len(audio):
            logger.debug(f"Start position {start_ms}ms is beyond audio length {len(audio)}ms")
            return
        # Handle case where end is beyond audio length
        end_ms = min(start_ms + duration_ms, len(audio))
        segment = audio[start_ms:end_ms]
        segment.export(output_path, format="mp3")
        logger.debug(f"Extracted segment {start_ms}ms-{end_ms}ms to {output_path}")
    except Exception as e:
        logger.debug(f"Error extracting segment: {e}")


async def recognize_segment(file_path: str, max_retries: int = 3) -> tuple:
    """
    Uses Shazam to recognize a segment with retry logic.
    Returns (match_offset_ms, 'Artist - Title') or (None, 'Not found').
    """
    if not os.path.exists(file_path):
        return (None, "Not found")
    
    shazam = Shazam()
    logger.debug(f"Attempting to recognize: {file_path} (max retries: {max_retries})")
    for attempt in range(max_retries):
        try:
            logger.debug(f"Recognition attempt {attempt+1}/{max_retries}")
            data = await shazam.recognize(file_path)
            if 'track' not in data:
                logger.debug(f"No track data found in attempt {attempt+1}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                logger.debug("Recognition failed after all attempts")
                return (None, "Not found")

            title = data['track']['title']
            subtitle = data['track']['subtitle']
            match_offset = data.get('timestamp', 0)
            result = f"{subtitle} - {title}"
            logger.debug(f"Recognition successful: {result} at offset {match_offset}ms")
            return (match_offset, result)

        except Exception as e:
            logger.debug(f"Error in recognition attempt {attempt+1}: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
                continue
            logger.debug("Recognition failed after all attempts due to exception")
            return (None, "Not found")


async def get_name(file_path: str, max_retries: int = 3) -> tuple:
    """
    Uses Shazam to recognize the song with retry logic and error handling.
    Returns either ('mm:ss', 'Artist - Title') or (None, 'Not found') if it fails.
    """
    return await recognize_segment(file_path, max_retries)


def binary_search_start_time(audio_file: str, segment_start_ms: int, target_track: str) -> int:
    """
    Use binary search to find the exact start time of a track within a segment.
    
    Args:
        audio_file: Path to the full audio file
        segment_start_ms: The start of the minute segment (ms)
        target_track: The track name to find
    
    Returns:
        The estimated start time in milliseconds
    """
    logger.debug(f"Starting binary search for '{target_track}' from {format_time(segment_start_ms)}")
    
    # Binary search range: from segment_start to segment_start + SEGMENT_LENGTH
    low = segment_start_ms
    high = segment_start_ms + SEGMENT_LENGTH
    
    # Also check if the track was actually in the PREVIOUS segment
    # Sometimes Shazam matches late, so check the boundary
    boundary_check_ms = max(0, segment_start_ms - BINARY_SEARCH_STEP)
    
    # Quick check: is the track at the very beginning of the segment?
    check_path = "tmp/binary_start.mp3"
    extract_segment(audio_file, segment_start_ms, BINARY_SEARCH_STEP, check_path)
    loop = asyncio.get_event_loop()
    offset, result = loop.run_until_complete(recognize_segment(check_path))
    
    if result == target_track:
        logger.debug(f"Track found at segment start {format_time(segment_start_ms)}")
        return segment_start_ms
    
    # If not found at start, binary search within the segment
    # But first, let's check if it's in the previous segment boundary
    if segment_start_ms > 0:
        check_path_prev = "tmp/binary_prev.mp3"
        extract_segment(audio_file, boundary_check_ms, BINARY_SEARCH_STEP, check_path_prev)
        offset, result = loop.run_until_complete(recognize_segment(check_path_prev))
        if result == target_track:
            logger.debug(f"Track found at previous boundary {format_time(boundary_check_ms)}")
            return boundary_check_ms
    
    # Binary search: look for the transition point
    # We check at BINARY_SEARCH_STEP intervals
    while high - low > BINARY_SEARCH_STEP:
        mid = (low + high) // 2
        mid_rounded = (mid // BINARY_SEARCH_STEP) * BINARY_SEARCH_STEP
        
        check_path = f"tmp/binary_{mid_rounded}.mp3"
        extract_segment(audio_file, mid_rounded, BINARY_SEARCH_STEP, check_path)
        offset, result = loop.run_until_complete(recognize_segment(check_path))
        
        if result == target_track:
            # Found it! The track is in this section
            # Narrow down to find exact start
            high = mid_rounded + BINARY_SEARCH_STEP
            low = max(low, mid_rounded - BINARY_SEARCH_STEP)
        else:
            # Track not in this section, search later
            low = mid
    
    # Return the earliest point where we found the track
    # Check a few points around the result
    for check_ms in range(max(segment_start_ms, low - BINARY_SEARCH_STEP), high + BINARY_SEARCH_STEP, BINARY_SEARCH_STEP):
        check_path = f"tmp/binary_final_{check_ms}.mp3"
        extract_segment(audio_file, check_ms, BINARY_SEARCH_STEP, check_path)
        offset, result = loop.run_until_complete(recognize_segment(check_path))
        if result == target_track:
            logger.debug(f"Binary search found track start at {format_time(check_ms)}")
            return check_ms
    
    # Fallback: return original segment start
    logger.debug(f"Binary search inconclusive, using segment start {format_time(segment_start_ms)}")
    return segment_start_ms


def process_audio_file(audio_file: str, output_filename: str, file_index: int, total_files: int) -> None:
    """
    Processes a single audio file: segments it, recognizes each segment,
    uses binary search for precise timestamps, excludes consecutive duplicate tracks, and saves results.
    """
    # If there are multiple files, display the file index
    if total_files > 2:
        logger.info(f"\n[{file_index}/{total_files}] Processing file: {audio_file}")
    else:
        logger.info(f"\nProcessing file: {audio_file}")
    
    logger.debug(f"Starting processing for {audio_file}")
    
    # Track for consecutive deduplication
    last_track = None
    
    logger.info("1/5 🧹 Cleaning temporary files...")
    remove_files("tmp")

    logger.info("2/5 ✂️ Segmenting audio file...")
    segment_audio(audio_file, "tmp")

    logger.info("3/5 🔍 Recognizing segments...")
    tmp_files = sorted(os.listdir("tmp"), key=lambda x: int(os.path.splitext(x)[0]))
    total_segments = len(tmp_files)
    logger.debug(f"Found {total_segments} segments to process")

    # First pass: collect all recognized tracks with rough timestamps
    rough_results = []  # List of (segment_idx, track_name)
    
    for idx, file_name in enumerate(tmp_files, start=1):
        segment_path = os.path.join("tmp", file_name)
        try:
            loop = asyncio.get_event_loop()
            match_offset_ms, track_name = loop.run_until_complete(recognize_segment(segment_path))

            timestamp_ms = (idx - 1) * SEGMENT_LENGTH
            timestamp_str = format_time(timestamp_ms)

            progress_str = f"[{idx}/{total_segments}]: {track_name}" if track_name != "Not found" else f"[{idx}/{total_segments}]: Not found"
            logger.info(progress_str)

            if track_name != "Not found":
                rough_results.append((idx, track_name, timestamp_ms))
                logger.debug(f"Collected: segment {idx}, track '{track_name}' at {timestamp_str}")
        except Exception as e:
            logger.debug(f"Error processing segment {file_name}: {e}")
            continue

    # Second pass: binary search for precise timestamps and write results
    if rough_results:
        logger.info("4/5 🎯 Binary searching for precise timestamps...")
        
        for seg_idx, track_name, rough_timestamp in rough_results:
            # Use binary search to find precise start time
            precise_start = binary_search_start_time(audio_file, rough_timestamp, track_name)
            timestamp_str = format_time(precise_start)
            
            output_line = f"{timestamp_str} {track_name}"
            
            # Consecutive deduplication: skip if same as last track
            if track_name == last_track:
                logger.debug(f"Skipping consecutive duplicate: {track_name}")
                continue
            
            last_track = track_name
            write_to_file(output_line, output_filename)
            logger.info(f"✅ {output_line}")

    logger.info("🧹 Cleaning temporary files...")
    remove_files("tmp")
    logger.info(f"✅ Successfully processed file: {audio_file}")
    logger.debug(f"Found {len(rough_results)} tracks in {audio_file}")


def process_downloads() -> None:
    """
    Process all MP3 files in DOWNLOADS_DIR: recognize each and save results to a new file.
    Output format: mm:ss artist - title (one per line, no headers)
    """
    output_dir = "recognised-lists"
    ensure_directory_exists(output_dir)
    ensure_directory_exists(DOWNLOADS_DIR)

    mp3_files = [f for f in os.listdir(DOWNLOADS_DIR) if f.endswith('.mp3')]
    if not mp3_files:
        logger.warning(f"❌ No MP3 files found in '{DOWNLOADS_DIR}' directory.")
        return

    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    output_filename = os.path.join(output_dir, f"songs-{timestamp}.txt")
    logger.debug(f"Created output file: {output_filename}")

    total_files = len(mp3_files)
    logger.info(f"📝 Found {total_files} MP3 file(s) to process...")
    logger.info("🚀 Starting processing...")

    for idx, file_name in enumerate(mp3_files, start=1):
        full_path = os.path.join(DOWNLOADS_DIR, file_name)
        logger.debug(f"Processing file {idx}/{total_files}: {full_path}")
        process_audio_file(full_path, output_filename, idx, total_files)

    logger.info(f"\n5/5 ✨ All files successfully processed!")
    logger.info(f"📋 Results saved to {output_filename}")


def print_usage() -> None:
    """
    Displays script usage instructions.
    """
    print("""
🎵 Shazam Tool 🎵

Usage: python shazam.py [command] [options]

Commands:
    🔍 scan                       Scan downloads directory and recognize all MP3
    ⬇️  download <url>            Download and process audio from YouTube or SoundCloud
    🎯 recognize <file_or_url>    Recognize specific audio file or download and recognize from URL

Options:
    --debug                       Enable debug mode with detailed logging

Examples:
    python shazam.py scan
    python shazam.py scan --debug
    python shazam.py download https://www.youtube.com/watch?v=...
    python shazam.py download https://soundcloud.com/... --debug
    python shazam.py recognize path/to/audio.mp3
    python shazam.py recognize https://soundcloud.com/... 
    """)


def main() -> None:
    parser = argparse.ArgumentParser(description='Shazam Tool', add_help=False)
    parser.add_argument('command', nargs='?', help='scan, download, or recognize')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode with detailed logging')
    parser.add_argument('url_or_file', nargs='?', help='URL or file path, depending on command')
    
    # Parse known args to avoid error with unrecognized args
    args, unknown = parser.parse_known_args()
    
    if not args.command:
        print_usage()
        sys.exit(1)
    
    # Set up logging based on debug flag
    setup_logging(args.debug)
    
    command = args.command
    output_dir = "recognised-lists"
    ensure_directory_exists(output_dir)

    # Generate default output filename
    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    output_filename = os.path.join(output_dir, f"songs-{timestamp}.txt")

    # Special handling for download and recognize commands to support unquoted URLs
    if command == 'download' or command == 'recognize':
        # Determine the URL/file by reconstructing from sys.argv
        # Skip 'python', 'shazam.py', 'command', and potentially '--debug'
        start_idx = 2  # Skip program name and command
        if '--debug' in sys.argv:
            # If --debug is immediately after command, adjust accordingly
            if sys.argv.index('--debug') == start_idx:
                start_idx += 1
        
        # If we still have arguments left, reconstruct them
        if len(sys.argv) > start_idx:
            # Join all remaining arguments to handle spaces in URLs or file paths
            url_or_file = ' '.join(sys.argv[start_idx:])
        else:
            url_or_file = None
    else:
        # For other commands, use argparse result
        url_or_file = args.url_or_file

    if command == 'download':
        if not url_or_file:
            logger.error("Missing URL. Usage: python shazam.py download <url> [--debug]")
            sys.exit(1)

        download_from_url(url_or_file)
        process_downloads()

    elif command in ['scan', 'scan-downloads']:
        logger.info(f"Scanning '{DOWNLOADS_DIR}' directory for MP3 files...")
        process_downloads()
        return
    
    elif command == 'recognize':
        if not url_or_file:
            logger.error("Missing file path. Usage: python shazam.py recognize <file_path> [--debug]")
            sys.exit(1)

        audio_file = url_or_file
        
        # Check if the input is a URL
        if audio_file.startswith('http://') or audio_file.startswith('https://'):
            logger.info(f"URL detected: {audio_file}")
            # Download from URL first
            download_from_url(audio_file)
            # Find the downloaded file in the downloads directory
            mp3_files = [f for f in os.listdir(DOWNLOADS_DIR) if f.endswith('.mp3')]
            if not mp3_files:
                logger.error(f"No MP3 files found in '{DOWNLOADS_DIR}' directory after download.")
                sys.exit(1)
            # Process only the most recently downloaded file 
            # (assuming it's the one we just downloaded)
            latest_file = max([os.path.join(DOWNLOADS_DIR, f) for f in mp3_files], 
                              key=os.path.getmtime)
                
            process_audio_file(latest_file, output_filename, 1, 1)
            logger.info(f"\nResults saved to {output_filename}")
            return
        
        # Handle local file
        if not os.path.exists(audio_file):
            logger.error(f"Error: File '{audio_file}' not found.")
            sys.exit(1)

        # Since we're processing a single file, pass file_index=1 and total_files=1
        process_audio_file(audio_file, output_filename, 1, 1)
        logger.info(f"\nResults saved to {output_filename}")
        return

    else:
        logger.error(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
