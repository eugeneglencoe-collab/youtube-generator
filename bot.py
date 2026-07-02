import os
import json
import yt_dlp
import google.generativeai as genai
from moviepy import VideoFileClip
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# --- CONFIGURATION ---
TARGET_CHANNEL_URL = "https://www.youtube.com/channel/UCGfI2yGzrs45oQjL8FnOhjg" 
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# Utiliser le fichier cookie pour s'authentifier
COOKIE_PATH = 'cookies.txt'

def get_latest_video_and_transcript():
    print("[1] Recherche de la dernière vidéo...")
    ydl_opts = {
        'extract_flat': 'in_playlist', 
        'playlist_items': '1', 
        'quiet': True,
        'cookiefile': COOKIE_PATH, # <--- Ajout ici
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    channel_videos_url = f"{TARGET_CHANNEL_URL}/videos"
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_videos_url, download=False)
        video_id = info['entries'][0]['id']
        
    print(f"[1] Vidéo détectée : {video_id}. Téléchargement des sous-titres...")
    
    for f in ['subtitle_file.fr.vtt', 'subtitle_file.en.vtt', 'subtitle_file.vtt']:
        if os.path.exists(f): os.remove(f)
        
    sub_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'subtitleslangs': ['fr', 'en'],
        'outtmpl': 'subtitle_file',
        'quiet': True,
        'cookiefile': COOKIE_PATH # <--- Ajout ici
    }
    with yt_dlp.YoutubeDL(sub_opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    
    text_content = ""
    for ext in ['.fr.vtt', '.en.vtt', '.vtt']:
        if os.path.exists(f"subtitle_file{ext}"):
            with open(f"subtitle_file{ext}", 'r', encoding='utf-8') as f:
                text_content = f.read()
            break
            
    return video_id, text_content

def identify_viral_segment(transcript_text):
    print("[2] Analyse Gemini...")
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"Analyse ce texte et renvoie uniquement un JSON (start, end, title) pour un segment viral de 30s. Texte : {transcript_text[:10000]}"
    response = model.generate_content(prompt)
    try:
        cleaned = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except:
        return {"start": 10, "end": 40, "title": "Vidéo virale"}

def download_and_process_video(video_id, segment):
    print("[3] Traitement vidéo...")
    # On ajoute aussi le cookie ici au cas où
    cmd = f'yt-dlp --cookies {COOKIE_PATH} -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]" --download-sections "*{segment["start"]}-{segment["end"]}" -o raw_video.mp4 https://www.youtube.com/watch?v={video_id}'
    os.system(cmd)
    
    clip = VideoFileClip("raw_video.mp4")
    w, h = clip.size
    target_w = int(h * 9/16)
    x1 = (w - target_w) // 2
    
    cropped = clip.crop(x1=x1, y1=0, x2=x1+target_w, y2=h)
    cropped.write_videofile("final_short.mp4", codec="libx264", audio_codec="aac")
    return "final_short.mp4"

def get_authenticated_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ.get("YT_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("YT_CLIENT_ID"),
        client_secret=os.environ.get("YT_CLIENT_SECRET")
    )
    if not creds.valid: creds.refresh(Request())
    return build('youtube', 'v3', credentials=creds)

def upload_short(youtube, file_path, metadata):
    print("[4] Upload sur YouTube...")
    body = {
        'snippet': {'title': metadata.get('title', 'Short généré par IA'), 'categoryId': '22'}, 
        'status': {'privacyStatus': 'public'}
    }
    media = MediaFileUpload(file_path, mimetype='video/mp4')
    response = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    print(f"✅ Succès : https://youtube.com/shorts/{response['id']}")

if __name__ == "__main__":
    vid_id, text = get_latest_video_and_transcript()
    segment = identify_viral_segment(text)
    final_mp4 = download_and_process_video(vid_id, segment)
    yt_service = get_authenticated_service()
    upload_short(yt_service, final_mp4, segment)
