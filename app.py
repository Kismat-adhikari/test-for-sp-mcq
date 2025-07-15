import os
import tempfile
import subprocess
from flask import Flask, request, render_template, jsonify
import yt_dlp
import requests
import json
import time

app = Flask(__name__)

# Try to load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configuration
ASSEMBLYAI_API_KEY = os.environ.get('ASSEMBLYAI_API_KEY')

def download_audio(youtube_url, output_path):
    """Download audio from YouTube video using yt-dlp with multiple fallback strategies"""
    
    # Strategy 1: Standard download
    strategies = [
        {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            },
        },
        # Strategy 2: Lower quality fallback
        {
            'format': 'worstaudio/worst',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }],
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
        },
        # Strategy 3: Basic download
        {
            'format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }],
        }
    ]
    
    for i, strategy in enumerate(strategies):
        try:
            ydl_opts = {
                'outtmpl': output_path,
                'no_warnings': True,
                'ignoreerrors': True,
                **strategy
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_url])
            
            # Check if file was created
            expected_file = output_path + '.mp3'
            if os.path.exists(expected_file):
                return expected_file
                
        except Exception as e:
            if i == len(strategies) - 1:  # Last strategy failed
                raise Exception(f"All download strategies failed. Last error: {str(e)}")
            continue
    
    raise Exception("Failed to download audio with all strategies")

def upload_to_assemblyai(audio_file_path):
    """Upload audio file to AssemblyAI and get transcript"""
    try:
        # Upload file
        headers = {'authorization': ASSEMBLYAI_API_KEY}
        
        with open(audio_file_path, 'rb') as f:
            response = requests.post(
                'https://api.assemblyai.com/v2/upload',
                headers=headers,
                files={'audio': f}
            )
        
        if response.status_code != 200:
            raise Exception(f"Upload failed: {response.text}")
        
        upload_url = response.json()['upload_url']
        
        # Request transcription
        transcript_request = {
            'audio_url': upload_url,
            'language_code': 'en'
        }
        
        response = requests.post(
            'https://api.assemblyai.com/v2/transcript',
            json=transcript_request,
            headers=headers
        )
        
        if response.status_code != 200:
            raise Exception(f"Transcription request failed: {response.text}")
        
        transcript_id = response.json()['id']
        
        # Poll for completion
        while True:
            response = requests.get(
                f'https://api.assemblyai.com/v2/transcript/{transcript_id}',
                headers=headers
            )
            
            if response.status_code != 200:
                raise Exception(f"Transcript status check failed: {response.text}")
            
            transcript = response.json()
            
            if transcript['status'] == 'completed':
                return transcript['text']
            elif transcript['status'] == 'error':
                raise Exception(f"Transcription failed: {transcript['error']}")
            
            time.sleep(5)  # Wait 5 seconds before checking again
            
    except Exception as e:
        raise Exception(f"AssemblyAI error: {str(e)}")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'GET':
        return render_template('index.html')
    
    # Handle POST request
    youtube_url = request.form.get('youtube_url', '').strip()
    
    if not youtube_url:
        return render_template('index.html', error="Please enter a YouTube URL")
    
    if not ASSEMBLYAI_API_KEY:
        return render_template('index.html', error="AssemblyAI API key not configured")
    
    # Create temporary directory for audio file
    temp_dir = tempfile.mkdtemp()
    audio_file = None
    
    try:
        # Download audio
        audio_path = os.path.join(temp_dir, 'audio')
        audio_file = download_audio(youtube_url, audio_path)
        
        # Get transcript
        transcript = upload_to_assemblyai(audio_file)
        
        return render_template('index.html', 
                             transcript=transcript,
                             youtube_url=youtube_url)
        
    except Exception as e:
        return render_template('index.html', error=str(e))
    
    finally:
        # Clean up temporary files
        if audio_file and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
            except:
                pass
        
        try:
            os.rmdir(temp_dir)
        except:
            pass

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))