# YouTube Transcript & MCQ Generator

A Flask web application that downloads YouTube videos, transcribes them using AssemblyAI, and generates multiple-choice questions using Groq Cloud API.

## Features

- 🎥 Download audio from YouTube videos using yt-dlp
- 📝 Transcribe audio using AssemblyAI
- ❓ Generate 5 MCQs from transcripts using Groq Cloud API
- 🎨 Clean, responsive web interface
- 🔧 Error handling and loading states
- 🧹 Automatic cleanup of temporary files
- 🐳 Docker support for easy deployment

## Prerequisites

- Python 3.11+
- AssemblyAI API key
- Groq Cloud API key
- ffmpeg (for audio processing)

## Local Development Setup

### 1. Clone and Install Dependencies

```bash
git clone <your-repo-url>
cd youtube-transcript-mcq
pip install -r requirements.txt
```

### 2. Install ffmpeg

**Ubuntu/Debian:**
```bash
sudo apt-get install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
Download from https://ffmpeg.org/download.html

### 3. Set Environment Variables

Create a `.env` file or set environment variables:

```bash
export ASSEMBLYAI_API_KEY="your_assemblyai_api_key_here"
export GROQ_API_KEY="your_groq_api_key_here"
```

### 4. Run the Application

```bash
python app.py
```

Visit `http://localhost:5000` in your browser.

## API Keys Setup

### AssemblyAI API Key
1. Go to https://www.assemblyai.com/
2. Sign up for a free account
3. Get your API key from the dashboard
4. Free tier includes 5 hours of transcription per month

### Groq Cloud API Key
1. Go to https://console.groq.com/
2. Sign up for an account
3. Create an API key
4. Free tier includes generous usage limits

## Docker Usage

### Build and Run Locally

```bash
docker build -t youtube-transcript-app .
docker run -p 5000:5000 \
  -e ASSEMBLYAI_API_KEY="your_key_here" \
  -e GROQ_API_KEY="your_key_here" \
  youtube-transcript-app
```

## Deployment on Render.com

### 1. Prepare Your Repository

Ensure these files are in your repository:
- `app.py`
- `requirements.txt`
- `Dockerfile`
- `templates/index.html`

### 2. Deploy to Render

1. Go to https://render.com/
2. Sign up/login and connect your GitHub repository
3. Create a new "Web Service"
4. Configure the service:
   - **Build Command:** `docker build -t app .`
   - **Start Command:** `docker run -p 5000:5000 app`
   - **Environment:** Docker
   - **Region:** Choose closest to you
   - **Instance Type:** Free tier is sufficient for testing

### 3. Set Environment Variables

In Render dashboard, add environment variables:
- `ASSEMBLYAI_API_KEY`: Your AssemblyAI API key
- `GROQ_API_KEY`: Your Groq API key

### 4. Deploy

Click "Deploy" and wait for the build to complete. Your app will be available at `https://your-app-name.onrender.com`

## Usage

1. Open the web application
2. Paste a YouTube video URL
3. Click "Generate Transcript & MCQs"
4. Wait for processing (may take 1-3 minutes)
5. View the transcript and generated MCQs

## File Structure

```
youtube-transcript-mcq/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker configuration
├── README.md            # This file
└── templates/
    └── index.html       # HTML template
```

## Error Handling

The application handles various errors gracefully:
- Invalid YouTube URLs
- Network failures
- API rate limits
- Audio processing errors
- Transcription failures

## Limitations

- Only supports YouTube videos
- Transcription is in English only
- Processing time depends on video length
- Free tier API limits apply

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is open source and available under the MIT License.

## Support

If you encounter issues:
1. Check your API keys are valid
2. Ensure ffmpeg is installed
3. Verify the YouTube URL is accessible
4. Check the application logs for detailed error messages

For deployment issues on Render:
1. Check the build logs
2. Verify environment variables are set
3. Monitor the application logs in Render dashboard