import os
import json
import re
import random  # NOUVEAU : Pour choisir une vidéo au hasard
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
HISTORY_FILE = "history.json" # NOUVEAU : Fichier de mémoire du bot

if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    print("❌ ERREUR : La variable d'environnement GEMINI_API_KEY n'est pas définie.")
    exit(1)

# --- FONCTIONS D'HISTORIQUE ---
def load_history():
    """Charge l'historique des vidéos déjà traitées."""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(history):
    """Sauvegarde l'historique mis à jour."""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=4)

# --- FONCTIONS PRINCIPALES ---
def get_random_video_and_transcript():
    print("[1] Recherche d'une vidéo dans la chaîne...")
    
    ydl_opts = {
        'extract_flat': 'in_playlist', 
        'playlist_items': '1:30', # NOUVEAU : Récupère les 30 dernières vidéos (au lieu de 1)
        'quiet': False,
        'cookiefile': 'cookies.txt',
        'extractor_args': {'youtube': ['player_client=android,ios,tv']},
        'js_runtimes': {'node': {}},
        'remote_components': ['ejs:github'],
    }
    
    channel_videos_url = f"{TARGET_CHANNEL_URL}/videos"
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_videos_url, download=False)
        # NOUVEAU : On filtre les vidéos valides et on en choisit une au hasard !
        valid_entries = [e for e in info['entries'] if e.get('id')]
        selected_entry = random.choice(valid_entries)
        video_id = selected_entry['id']
        video_title = selected_entry.get('title', 'Titre inconnu')
        
    print(f"[1] Vidéo sélectionnée au hasard : {video_title} ({video_id}). Téléchargement des sous-titres...")
    
    sub_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['fr', 'en'],
        'outtmpl': 'subtitle_file',
        'quiet': False,
        'cookiefile': 'cookies.txt',
        'extractor_args': {'youtube': ['player_client=android,ios,tv']},
        'js_runtimes': {'node': {}},
        'remote_components': ['ejs:github'],
        'ignoreerrors': True, 
    }
    
    with yt_dlp.YoutubeDL(sub_opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    
    text_content = ""
    for ext in ['.fr.vtt', '.en.vtt', '.vtt']:
        if os.path.exists(f"subtitle_file{ext}"):
            with open(f"subtitle_file{ext}", 'r', encoding='utf-8') as f:
                text_content = f.read()
            print(f"✅ Sous-titres chargés depuis subtitle_file{ext}")
            break
            
    if not text_content:
        print("⚠️ Aucun sous-titre trouvé, l'analyse risque d'échouer.")
            
    return video_id, text_content

def identify_viral_segment(transcript_text, video_id, history):
    print("[2] Analyse Gemini...")
    
    # NOUVEAU : On vérifie si la vidéo a déjà été utilisée
    past_segments = history.get(video_id, [])
    restriction_prompt = ""
    
    if past_segments:
        restriction_prompt = "⚠️ ATTENTION : Tu as déjà extrait des segments de cette vidéo par le passé. Tu DOIS ABSOLUMENT trouver un passage 100% NOUVEAU et ne pas utiliser les zones suivantes :\n"
        for seg in past_segments:
            restriction_prompt += f"- Interdit : de {seg['start']}s à {seg['end']}s\n"

    prompt = f"""
    Analyse ce texte de sous-titres vidéo et trouve le moment le plus captivant pour en faire un Short (durée : 15 à 60 secondes).
    {restriction_prompt}
    Tu DOIS répondre UNIQUEMENT par un objet JSON valide avec les clés : "start" (entier en secondes), "end" (entier en secondes) et "title" (titre accrocheur).
    Texte : {transcript_text[:10000]}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
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
        # Générer des valeurs par défaut un peu aléatoires pour éviter les doublons même en cas d'erreur
        random_start = random.randint(10, 60)
        return {"start": random_start, "end": random_start + 30, "title": "Moment Fort IA"}

def download_and_process_video(video_id, segment):
    print("[3] Téléchargement du segment...")
    
    raw_video = "raw_video.mp4"
    final_video = "final_short.mp4"
    
    if os.path.exists(raw_video): os.remove(raw_video)
    if os.path.exists(final_video): os.remove(final_video)

    start_sec = segment["start"]
    end_sec = segment["end"]
    
    cmd = f'yt-dlp --cookies cookies.txt --js-runtimes node --remote-components ejs:github --extractor-args "youtube:player_client=android,ios,tv" -f "bestvideo+bestaudio/best" --remux-video mp4 --download-sections "*{start_sec}-{end_sec}" -o {raw_video} https://www.youtube.com/watch?v={video_id}'
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
        # 1. Charger la mémoire
        history = load_history()
        
        # 2. Prendre une vidéo au hasard parmi les 30 dernières
        vid_id, text = get_random_video_and_transcript()
        
        # 3. Analyser (en évitant les passages déjà faits)
        segment = identify_viral_segment(text, vid_id, history)
        print(f"🎬 Segment identifié : {segment}")
        
        # 4. Traiter et uploader
        final_mp4 = download_and_process_video(vid_id, segment)
        yt_service = get_authenticated_service()
        upload_short(yt_service, final_mp4, segment)
        
        # 5. Mémoriser ce succès pour la prochaine fois !
        if vid_id not in history:
            history[vid_id] = []
        history[vid_id].append({"start": segment["start"], "end": segment["end"]})
        save_history(history)
        print("✅ Mémoire mise à jour avec succès.")
        
    except Exception as e:
        print(f"❌ Erreur générale lors de l'exécution : {e}")
