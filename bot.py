import os
import json
import re
import yt_dlp
from google import genai
from moviepy.editor import VideoFileClip, vfx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# --- CONFIGURATION ---
TARGET_CHANNEL_URL = "https://www.youtube.com/channel/UCGfI2yGzrs45oQjL8FnOhjg" 
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    print("❌ ERREUR : La variable d'environnement GEMINI_API_KEY n'est pas définie.")
    exit(1)

def get_latest_video_and_transcript():
    print("[1] Recherche de la dernière vidéo...")
    
    ydl_opts = {
        'extract_flat': 'in_playlist', 
        'playlist_items': '1', 
        'quiet': False,
        'extractor_args': {'youtube': ['player_client=ios,android,web']},
        'js_runtimes': {'node': {}}, # 🔴 Correction ici : format dictionnaire requis
    }
    
    channel_videos_url = f"{TARGET_CHANNEL_URL}/videos"
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_videos_url, download=False)
        video_id = info['entries'][0]['id']
        
    print(f"[1] Vidéo détectée : {video_id}. Téléchargement des sous-titres...")
    
    sub_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['fr', 'en'],
        'outtmpl': 'subtitle_file',
        'quiet': False,
        'extractor_args': {'youtube': ['player_client=ios,android,web']},
        'js_runtimes': {'node': {}}, # 🔴 Correction ici également
    }
    
    with yt_dlp.YoutubeDL(sub_opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    
    text_content = ""
    for ext in ['.fr.vtt', '.en.vtt', '.vtt']:
        if os.path.exists(f"subtitle_file{ext}"):
            with open(f"subtitle_file{ext}", 'r', encoding='utf-8') as f:
                text_content = f.read()
            break
            
    if not text_content:
        print("⚠️ Aucun sous-titre trouvé, l'analyse risque d'échouer.")
            
    return video_id, text_content

def identify_viral_segment(transcript_text):
    print("[2] Analyse Gemini...")
    
    prompt = f"""
    Analyse ce texte de sous-titres vidéo et trouve le moment le plus captivant pour en faire un Short (durée : 15 à 60 secondes).
    Tu DOIS répondre UNIQUEMENT par un objet JSON valide avec les clés : "start" (entier en secondes), "end" (entier en secondes) et "title" (titre accrocheur).
    Texte : {transcript_text[:10000]}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt
        )
        
        match = re.search(r'\{.*?\}', response.text, re.DOTALL)
        if match:
            segment = json.loads(match.group(0))
            segment["start"] = int(segment.get("start", 10))
            segment["end"] = int(segment.get("end", 40))
            return segment
        else:
            raise ValueError("Aucun JSON trouvé dans la réponse.")
    except Exception as e:
        print(f"⚠️ Erreur de parsing Gemini ({e}), utilisation des valeurs par défaut.")
        return {"start": 10, "end": 40, "title": "Vidéo virale"}

def download_and_process_video(video_id, segment):
    print("[3] Téléchargement du segment...")
    
    raw_video = "raw_video.mp4"
    final_video = "final_short.mp4"
    
    if os.path.exists(raw_video): os.remove(raw_video)
    if os.path.exists(final_video): os.remove(final_video)

    start_sec = segment["start"]
    end_sec = segment["end"]
    
    # La commande CLI reste inchangée car --js-runtimes node y est correct
    cmd = f'yt-dlp --js-runtimes node --extractor-args "youtube:player_client=ios,android,web" -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]" --download-sections "*{start_sec}-{end_sec}" -o {raw_video} https://www.youtube.com/watch?v={video_id}'
    os.system(cmd)
    
    print("[3] Rognage de la vidéo (Format Short 9:16)...")
    clip = VideoFileClip(raw_video)
    w, h = clip.size
    target_w = int(h * 9/16)
    x1 = (w - target_w) // 2
    
    cropped = clip.fx(vfx.crop, x1=x1, y1=0, x2=x1+target_w, y2=h)
    
    cropped.write_videofile(final_video, codec="libx264", audio_codec="aac", logger=None)
    
    clip.close()
    cropped.close()
    
    return final_video

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
        'snippet': {
            'title': metadata.get('title', 'Short généré par IA'), 
            'categoryId': '22',
            'description': '#shorts #ia'
        }, 
        'status': {'privacyStatus': 'public'}
    }
    media = MediaFileUpload(file_path, mimetype='video/mp4')
    response = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    print(f"✅ Succès : https://youtube.com/shorts/{response['id']}")

if __name__ == "__main__":
    try:
        vid_id, text = get_latest_video_and_transcript()
        segment = identify_viral_segment(text)
        print(f"🎬 Segment identifié : {segment}")
        
        final_mp4 = download_and_process_video(vid_id, segment)
        
        yt_service = get_authenticated_service()
        upload_short(yt_service, final_mp4, segment)
    except Exception as e:
        print(f"❌ Erreur générale lors de l'exécution : {e}")
