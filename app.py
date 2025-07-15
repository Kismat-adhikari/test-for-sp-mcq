import os
import tempfile
import subprocess
import shutil
import signal
import sys
import time
import logging
from urllib.parse import urlparse, parse_qs

from flask import Flask, request, render_template, jsonify
import yt_dlp
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Try to load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configuration
ASSEMBLYAI_API_KEY = os.environ.get('ASSEMBLYAI_API_KEY')
PORT = int(os.environ.get('PORT', 5000))
MAX_VIDEO_DURATION = 1800  # 30 minutes
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
UPLOAD_TIMEOUT = 180  # 3 minutes
TRANSCRIPTION_TIMEOUT = 600  # 10 minutes

class YouTubeTranscriberError(Exception):
    """Custom exception for YouTube transcriber errors"""
    pass

class VideoUnavailableError(YouTubeTranscriberError):
    """Raised when video is unavailable"""
    pass

class VideoTooLongError(YouTubeTranscriberError):
    """Raised when video exceeds maximum duration"""
    pass

class DownloadError(YouTubeTranscriberError):
    """Raised when download fails"""
    pass

class TranscriptionError(YouTubeTranscriberError):
    """Raised when transcription fails"""
    pass

def signal_handler(sig, frame):
    """Handle graceful shutdown"""
    logger.info('Shutting down gracefully...')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def extract_video_id(url):
    """Extract video ID from YouTube URL"""
    if 'youtu.be' in url:
        return url.split('/')[-1].split('?')[0]
    elif 'youtube.com' in url:
        parsed = urlparse(url)
        if parsed.path == '/watch':
            return parse_qs(parsed.query).get('v', [None])[0]
        elif parsed.path.startswith('/embed/'):
            return parsed.path.split('/')[2]
    return None

def is_valid_youtube_url(url):
    """Check if URL is a valid YouTube URL"""
    return any(domain in url.lower() for domain in ['youtube.com', 'youtu.be']) and extract_video_id(url) is not None

def check_ffmpeg():
    """Check if ffmpeg is available"""
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        raise YouTubeTranscriberError("FFmpeg not found. Please install FFmpeg.")
    logger.info(f"Using ffmpeg at: {ffmpeg_path}")
    return ffmpeg_path

def validate_video_info(youtube_url):
    """Validate video accessibility and get basic info"""
    logger.info(f"Validating video: {youtube_url}")
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'socket_timeout': 15,
        'no_check_certificate': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            
            if info is None:
                raise VideoUnavailableError("Video is unavailable or cannot be accessed")
            
            duration = info.get('duration', 0)
            title = info.get('title', 'Unknown')
            
            logger.info(f"Video found: {title} ({duration}s)")
            
            if duration and duration > MAX_VIDEO_DURATION:
                raise VideoTooLongError(f"Video is too long ({duration//60}:{duration%60:02d}). Maximum allowed: {MAX_VIDEO_DURATION//60} minutes")
            
            return {
                'title': title,
                'duration': duration,
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count', 0)
            }
            
    except yt_dlp.utils.ExtractorError as e:
        error_msg = str(e).lower()
        if any(phrase in error_msg for phrase in ['video unavailable', 'content isn\'t available', 'private video']):
            raise VideoUnavailableError("Video is unavailable, private, or restricted")
        elif 'sign in to confirm your age' in error_msg:
            raise VideoUnavailableError("Video requires age verification")
        elif 'video has been removed' in error_msg:
            raise VideoUnavailableError("Video has been removed")
        else:
            raise VideoUnavailableError(f"Cannot access video: {str(e)}")
    except Exception as e:
        raise YouTubeTranscriberError(f"Validation failed: {str(e)}")

def download_audio(youtube_url, output_path):
    """Download audio from YouTube video with multiple fallback strategies"""
    logger.info(f"Starting audio download: {youtube_url}")
    
    ffmpeg_path = check_ffmpeg()
    
    # Multiple download strategies with decreasing quality
    strategies = [
        {
            'name': 'High Quality Audio',
            'format': 'bestaudio[filesize<50M]/bestaudio[ext=m4a]/bestaudio',
            'quality': '192'
        },
        {
            'name': 'Medium Quality Audio',
            'format': 'bestaudio[filesize<30M]/bestaudio',
            'quality': '128'
        },
        {
            'name': 'Low Quality Audio',
            'format': 'worstaudio[filesize<20M]/worstaudio',
            'quality': '96'
        },
        {
            'name': 'Fallback - Any Audio',
            'format': 'best[filesize<50M]/best',
            'quality': '64'
        }
    ]
    
    for i, strategy in enumerate(strategies):
        try:
            logger.info(f"Attempting strategy {i+1}: {strategy['name']}")
            
            ydl_opts = {
                'format': strategy['format'],
                'outtmpl': output_path + '.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': strategy['quality'],
                }],
                'ffmpeg_location': ffmpeg_path,
                'no_warnings': False,
                'verbose': False,
                'extract_flat': False,
                'no_check_certificate': True,
                'socket_timeout': 30,
                'retries': 3,
                'fragment_retries': 3,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                },
                'geo_bypass': True,
                'geo_bypass_country': 'US',
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_url])
            
            # Find the downloaded file
            possible_extensions = ['.mp3', '.m4a', '.webm', '.mp4', '.wav', '.opus']
            for ext in possible_extensions:
                expected_file = output_path + ext
                if os.path.exists(expected_file):
                    file_size = os.path.getsize(expected_file)
                    logger.info(f"Download successful: {expected_file} ({file_size} bytes)")
                    
                    if file_size > MAX_FILE_SIZE:
                        os.remove(expected_file)
                        raise DownloadError(f"Downloaded file is too large ({file_size//1024//1024}MB). Maximum: {MAX_FILE_SIZE//1024//1024}MB")
                    
                    if file_size < 1024:  # Less than 1KB
                        os.remove(expected_file)
                        raise DownloadError("Downloaded file is too small (likely empty)")
                    
                    return expected_file
            
            raise DownloadError("No output file found after download")
            
        except yt_dlp.utils.ExtractorError as e:
            logger.warning(f"Strategy {i+1} failed with ExtractorError: {str(e)}")
            if i == len(strategies) - 1:
                raise DownloadError(f"All download strategies failed: {str(e)}")
            continue
        except Exception as e:
            logger.warning(f"Strategy {i+1} failed: {str(e)}")
            if i == len(strategies) - 1:
                raise DownloadError(f"All download strategies failed: {str(e)}")
            continue
    
    raise DownloadError("Failed to download audio with all strategies")

def upload_to_assemblyai(audio_file_path):
    """Upload audio file to AssemblyAI and get transcription"""
    logger.info(f"Uploading to AssemblyAI: {audio_file_path}")
    
    if not ASSEMBLYAI_API_KEY:
        raise TranscriptionError("AssemblyAI API key not configured")
    
    file_size = os.path.getsize(audio_file_path)
    logger.info(f"File size: {file_size} bytes")
    
    if file_size > 200 * 1024 * 1024:  # 200MB AssemblyAI limit
        raise TranscriptionError("Audio file is too large for transcription (>200MB)")
    
    headers = {'authorization': ASSEMBLYAI_API_KEY}
    
    try:
        # Upload file
        with open(audio_file_path, 'rb') as f:
            upload_response = requests.post(
                'https://api.assemblyai.com/v2/upload',
                headers=headers,
                files={'audio': f},
                timeout=UPLOAD_TIMEOUT
            )
        
        if upload_response.status_code != 200:
            raise TranscriptionError(f"Upload failed: {upload_response.text}")
        
        upload_url = upload_response.json()['upload_url']
        logger.info("Upload to AssemblyAI successful")
        
        # Request transcription
        transcript_request = {
            'audio_url': upload_url,
            'language_code': 'en',
            'punctuate': True,
            'format_text': True
        }
        
        transcript_response = requests.post(
            'https://api.assemblyai.com/v2/transcript',
            json=transcript_request,
            headers=headers,
            timeout=30
        )
        
        if transcript_response.status_code != 200:
            raise TranscriptionError(f"Transcription request failed: {transcript_response.text}")
        
        transcript_id = transcript_response.json()['id']
        logger.info(f"Transcription started: {transcript_id}")
        
        # Poll for completion
        start_time = time.time()
        while True:
            if time.time() - start_time > TRANSCRIPTION_TIMEOUT:
                raise TranscriptionError("Transcription timed out")
            
            status_response = requests.get(
                f'https://api.assemblyai.com/v2/transcript/{transcript_id}',
                headers=headers,
                timeout=30
            )
            
            if status_response.status_code != 200:
                raise TranscriptionError(f"Status check failed: {status_response.text}")
            
            transcript = status_response.json()
            status = transcript['status']
            
            logger.info(f"Transcription status: {status}")
            
            if status == 'completed':
                return transcript['text']
            elif status == 'error':
                error_msg = transcript.get('error', 'Unknown error')
                raise TranscriptionError(f"Transcription failed: {error_msg}")
            
            time.sleep(5)  # Check every 5 seconds
            
    except requests.exceptions.RequestException as e:
        raise TranscriptionError(f"Network error: {str(e)}")
    except Exception as e:
        raise TranscriptionError(f"Transcription error: {str(e)}")

def cleanup_temp_files(temp_dir, audio_file=None):
    """Clean up temporary files"""
    if audio_file and os.path.exists(audio_file):
        try:
            os.remove(audio_file)
            logger.info(f"Cleaned up audio file: {audio_file}")
        except Exception as e:
            logger.warning(f"Failed to remove audio file: {e}")
    
    if temp_dir and os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir)
            logger.info(f"Cleaned up temp directory: {temp_dir}")
        except Exception as e:
            logger.warning(f"Failed to remove temp directory: {e}")

@app.route('/', methods=['GET', 'POST'])
def index():
    """Main page and transcription handler"""
    if request.method == 'GET':
        return render_template('index.html')
    
    # Handle POST request for transcription
    youtube_url = request.form.get('youtube_url', '').strip()
    
    if not youtube_url:
        return render_template('index.html', error='Please enter a YouTube URL')
    
    if not is_valid_youtube_url(youtube_url):
        return render_template('index.html', error='Please enter a valid YouTube URL')
    
    temp_dir = None
    audio_file = None
    
    try:
        # Validate video
        video_info = validate_video_info(youtube_url)
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        audio_path = os.path.join(temp_dir, 'audio')
        
        # Download audio
        audio_file = download_audio(youtube_url, audio_path)
        
        # Transcribe
        transcript = upload_to_assemblyai(audio_file)
        
        return render_template('index.html', 
                             transcript=transcript,
                             video_info=video_info,
                             youtube_url=youtube_url)
        
    except VideoUnavailableError as e:
        logger.error(f"Video unavailable: {str(e)}")
        return render_template('index.html', error=str(e))
    except VideoTooLongError as e:
        logger.error(f"Video too long: {str(e)}")
        return render_template('index.html', error=str(e))
    except DownloadError as e:
        logger.error(f"Download failed: {str(e)}")
        return render_template('index.html', error=f'Download failed: {str(e)}')
    except TranscriptionError as e:
        logger.error(f"Transcription failed: {str(e)}")
        return render_template('index.html', error=f'Transcription failed: {str(e)}')
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return render_template('index.html', error='An unexpected error occurred. Please try again.')
    
    finally:
        cleanup_temp_files(temp_dir, audio_file)

@app.route('/api/transcribe', methods=['POST'])
def api_transcribe():
    """API endpoint for transcription (returns JSON)"""
    youtube_url = request.json.get('youtube_url', '').strip() if request.is_json else request.form.get('youtube_url', '').strip()
    
    if not youtube_url:
        return jsonify({'error': 'Please enter a YouTube URL'}), 400
    
    if not is_valid_youtube_url(youtube_url):
        return jsonify({'error': 'Please enter a valid YouTube URL'}), 400
    
    temp_dir = None
    audio_file = None
    
    try:
        # Validate video
        video_info = validate_video_info(youtube_url)
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        audio_path = os.path.join(temp_dir, 'audio')
        
        # Download audio
        audio_file = download_audio(youtube_url, audio_path)
        
        # Transcribe
        transcript = upload_to_assemblyai(audio_file)
        
        return jsonify({
            'success': True,
            'transcript': transcript,
            'video_info': video_info
        })
        
    except VideoUnavailableError as e:
        logger.error(f"Video unavailable: {str(e)}")
        return jsonify({'error': str(e)}), 400
    except VideoTooLongError as e:
        logger.error(f"Video too long: {str(e)}")
        return jsonify({'error': str(e)}), 400
    except DownloadError as e:
        logger.error(f"Download failed: {str(e)}")
        return jsonify({'error': f'Download failed: {str(e)}'}), 500
    except TranscriptionError as e:
        logger.error(f"Transcription failed: {str(e)}")
        return jsonify({'error': f'Transcription failed: {str(e)}'}), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred. Please try again.'}), 500
    
    finally:
        cleanup_temp_files(temp_dir, audio_file)

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'port': PORT,
        'assemblyai_configured': bool(ASSEMBLYAI_API_KEY),
        'ffmpeg_available': shutil.which('ffmpeg') is not None
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    logger.info(f"Starting YouTube Transcriber on port {PORT}")
    logger.info(f"AssemblyAI API key configured: {bool(ASSEMBLYAI_API_KEY)}")
    logger.info(f"FFmpeg available: {shutil.which('ffmpeg') is not None}")
    
    app.run(debug=False, host='0.0.0.0', port=PORT)