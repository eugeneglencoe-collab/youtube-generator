import os
import json
import yt_dlp
import google.generativeai as genai
from moviepy import VideoFileClip, TextClip, CompositeVideoClip
import cv2
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# --- CONFIGURATION ---
TARGET_CHANNEL_URL = "https://www.youtube.com/@AnymeTV" # Remplace bien par ton URL
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

def get_latest_video_and_transcript():
    print("[1] Recherche de la dernière vidéo et téléchargement des sous-titres...")
    ydl_opts = {
        'extract_flat': False, 
        'writesubtitles': True, 
        'subtitleslangs': ['fr', 'en'], 
        'skip_download': True,
        'quiet': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(TARGET_CHANNEL_URL, download=False)
        video = info['entries'][0]
        video_id = video['id']
        
        # Tentative de récupération des sous-titres via yt-dlp
        sub_file = f"{video_id}.fr.vtt"
        if not os.path.exists(sub_file):
            sub_file = f"{video_id}.en.vtt" # Fallback en anglais
            
        if os.path.exists(sub_file):
            with open(sub_file, 'r', encoding='utf-8') as f:
                text_content = f.read()
            return video_id, text_content
        else:
            print("⚠️ Aucun sous-titre trouvé via yt-dlp.")
            return video_id, "", []

def identify_viral_segment(transcript_text):
    print("[2] Analyse Gemini...")
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"Analyse ce texte et renvoie un JSON (start, end, title) pour un segment viral. Texte : {transcript_text[:10000]}"
    response = model.generate_content(prompt)
    try:
        return json.loads(response.text.replace("```json", "").replace("```", "").strip())
    except:
        return {"start": 10, "end": 40, "title": "Vidéo intéressante"}

def download_and_process_video(video_id, segment):
    print("[3] Téléchargement et traitement vidéo...")
    # Téléchargement simple du segment
    cmd = f'yt-dlp -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]" --download-sections "*{segment["start"]}-{segment["end"]}" -o raw_video.mp4 https://www.youtube.com/watch?v={video_id}'
    os.system(cmd)
    
    # Recadrage vertical simple (au centre)
    clip = VideoFileClip("raw_video.mp4")
    w, h = clip.size
    target_h = h
    target_w = int(h * 9/16)
    x1 = (w - target_w) // 2
    
    cropped = clip.crop(x1=x1, y1=0, x2=x1+target_w, y2=h)
    cropped.write_videofile("final_short.mp4", codec="libx264", audio_codec="aac")
    return "final_short.mp4"

# ... (Garde tes fonctions d'upload YouTube inchangées en bas) ...

if __name__ == "__main__":
    vid_id, text = get_latest_video_and_transcript()
    segment = identify_viral_segment(text)
    final_mp4 = download_and_process_video(vid_id, segment)
    # Puis l'upload...
