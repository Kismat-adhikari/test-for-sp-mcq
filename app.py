import os
import tempfile
import subprocess
from flask import Flask, request, render_template, jsonify
import yt_dlp
import requests
import json
import time
import shutil
import signal
import sys

app = Flask(__name__)

# Try to load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configuration
ASSEMBLYAI_API_KEY = os.environ.get('ASSEMBLYAI_API_KEY')
PORT = int(os.environ.get('PORT', 5000))

# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    print('Shutting down gracefully...')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def download_audio(youtube_url, output_path):
    """Download audio from YouTube video with Render-optimized settings"""
    
    # Check if ffmpeg is available
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        raise Exception("ffmpeg not found. Please install ffmpeg.")
    
    print(f"Using ffmpeg at: {ffmpeg_path}")
    
    # Render-optimized strategies (lower quality for faster processing)
    strategies = [
        {
            'format': 'bestaudio[filesize<50M]/bestaudio[ext=m4a]/bestaudio/best[filesize<50M]',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',  # Lower quality for faster processing
            }],
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            },
            'extractor_retries': 5, # Increase retries
            'fragment_retries': 5, # Increase retries
            'retries': 5, # Increase general retries
            'geo_bypass': True, # Attempt to bypass geo-restrictions
            'geo_bypass_country': 'US', # Specify a country for geo-bypass
        },
        {
            'format': 'worstaudio[filesize<30M]/worstaudio/worst[filesize<30M]',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '96',  # Even lower quality
            }],
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            },
        }
    ]
    
    for i, strategy in enumerate(strategies):
        try:
            print(f"Trying strategy {i+1} (Render-optimized)...")
            
            ydl_opts = {
                'outtmpl': output_path + '.%(ext)s',
                'no_warnings': False,
                'ignoreerrors': True, # Set to True to allow yt-dlp to continue on some errors
                'verbose': True,  # Enable verbose logging for debugging
                'extract_flat': False,
                'no_check_certificate': True,
                'prefer_insecure': True,
                'socket_timeout': 30,  # Timeout for network operations
                'ffmpeg_location': ffmpeg_path,
                **strategy
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info first with timeout
                try:
                    info = ydl.extract_info(youtube_url, download=False)
                    duration = info.get('duration', 0)
                    
                    # Skip very long videos (> 30 minutes) to avoid timeouts
                    if duration and duration > 1800:
                        raise Exception("Video is too long (>30 minutes). Please use a shorter video.")
                    
                    print(f"Video title: {info.get('title', 'Unknown')}")
                    print(f"Duration: {duration} seconds")
                    
                except Exception as e:
                    print(f"Failed to extract info: {e}")
                    if i == len(strategies) - 1:
                        raise Exception(f"Cannot extract video info: {str(e)}")
                    continue
                
                # Download with timeout
                ydl.download([youtube_url])
            
            # Check for created files
            possible_extensions = ['.mp3', '.m4a', '.webm', '.mp4', '.wav']
            for ext in possible_extensions:
                expected_file = output_path + ext
                if os.path.exists(expected_file):
                    # Check file size
                    file_size = os.path.getsize(expected_file)
                    print(f"Successfully downloaded: {expected_file} ({file_size} bytes)")
                    
                    # Skip files that are too large (>100MB)
                    if file_size > 100 * 1024 * 1024:
                        os.remove(expected_file)
                        raise Exception("Downloaded file is too large (>100MB)")
                    
                    return expected_file
                
        except Exception as e:
            print(f"Strategy {i+1} failed: {str(e)}")
            if i == len(strategies) - 1:
                raise Exception(f"All download strategies failed. Last error: {str(e)}")
            continue
    
    raise Exception("Failed to download audio with all strategies")

def upload_to_assemblyai(audio_file_path):
    """Upload audio file to AssemblyAI with timeout handling"""
    try:
        print(f"Uploading file: {audio_file_path}")
        file_size = os.path.getsize(audio_file_path)
        print(f"File size: {file_size} bytes")
        
        # Skip files that are too large for free tier
        if file_size > 200 * 1024 * 1024:  # 200MB limit
            raise Exception("Audio file is too large (>200MB)")
        
        # Upload file with timeout
        headers = {'authorization': ASSEMBLYAI_API_KEY}
        
        with open(audio_file_path, 'rb') as f:
            response = requests.post(
                'https://api.assemblyai.com/v2/upload',
                headers=headers,
                files={'audio': f},
                timeout=180  # 3 minute timeout
            )
        
        if response.status_code != 200:
            raise Exception(f"Upload failed: {response.text}")
        
        upload_url = response.json()['upload_url']
        print(f"Upload successful")
        
        # Request transcription
        transcript_request = {
            'audio_url': upload_url,
            'language_code': 'en'
        }
        
        response = requests.post(
            'https://api.assemblyai.com/v2/transcript',
            json=transcript_request,
            headers=headers,
            timeout=30
        )
        
        if response.status_code != 200:
            raise Exception(f"Transcription request failed: {response.text}")
        
        transcript_id = response.json()['id']
        print(f"Transcription started: {transcript_id}")
        
        # Poll for completion with timeout
        max_wait_time = 600  # 10 minutes max
        start_time = time.time()
        
        while True:
            if time.time() - start_time > max_wait_time:
                raise Exception("Transcription timed out")
            
            response = requests.get(
                f'https://api.assemblyai.com/v2/transcript/{transcript_id}',
                headers=headers,
                timeout=30
            )
            
            if response.status_code != 200:
                raise Exception(f"Transcript status check failed: {response.text}")
            
            transcript = response.json()
            status = transcript['status']
            print(f"Transcription status: {status}")
            
            if status == 'completed':
                return transcript['text']
            elif status == 'error':
                raise Exception(f"Transcription failed: {transcript.get('error', 'Unknown error')}")
            
            time.sleep(10)  # Check every 10 seconds
            
    except Exception as e:
        raise Exception(f"AssemblyAI error: {str(e)}")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'GET':
        return render_template('index.html')
    
    youtube_url = request.form.get('youtube_url', '').strip()
    
    if not youtube_url:
        return render_template('index.html', error="Please enter a YouTube URL")
    
    if not ASSEMBLYAI_API_KEY:
        return render_template('index.html', error="AssemblyAI API key not configured")
    
    if not ('youtube.com' in youtube_url or 'youtu.be' in youtube_url):
        return render_template('index.html', error="Please enter a valid YouTube URL")
    
    temp_dir = tempfile.mkdtemp()
    audio_file = None
    
    try:
        print(f"Processing URL: {youtube_url}")
        
        audio_path = os.path.join(temp_dir, 'audio')
        audio_file = download_audio(youtube_url, audio_path)
        
        transcript = upload_to_assemblyai(audio_file)
        
        return render_template('index.html', 
                             transcript=transcript,
                             youtube_url=youtube_url)
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return render_template('index.html', error=str(e))
    
    finally:
        # Cleanup
        if audio_file and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
            except:
                pass
        
        try:
            shutil.rmtree(temp_dir)
        except:
            pass

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "port": PORT})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=PORT)