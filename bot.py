import os
import json
import time
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp
import cv2
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# --- CONFIGURATION INITIALE ---
# REMPLACE CETTE URL PAR LA CHAÎNE YOUTUBE QUE TU VEUX SURVEILLER ET REPURPOSER
TARGET_CHANNEL_URL = "https://www.youtube.com/@ChannelCible" 
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

# --- 1. IA & EXTRACTION DE TRANSCRIPTION ---
def get_latest_video_and_transcript():
    """Utilise yt-dlp pour trouver la dernière vidéo et extrait ses sous-titres."""
    print("[1] Recherche de la dernière vidéo...")
    ydl_opts = {'extract_flat': True, 'playlist_items': '1', 'quiet': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(TARGET_CHANNEL_URL, download=False)
        video_id = info['entries'][0]['id']
        
    print(f"[1] Vidéo trouvée : {video_id}. Extraction de la transcription...")
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['fr', 'en'])
        text_content = " ".join([t['text'] for t in transcript])
        return video_id, text_content, transcript
    except Exception as e:
        print(f"Erreur transcription: {e}")
        return None, None, None

def identify_viral_segment(transcript_text):
    """Demande à Gemini de trouver un passage viral de 15-30s."""
    print("[2] Analyse Gemini pour le segment viral...")
    model = genai.GenerativeModel('gemini-1.5-flash') # Rapide et économique
    prompt = f"""
    Analyse cette transcription vidéo. Trouve le passage le plus engageant et viral (durée estimée entre 15 et 30 secondes).
    Renvoie UNIQUEMENT un objet JSON valide (sans markdown) avec ce format exact :
    {{"start_text": "les premiers mots du segment", "end_text": "les derniers mots", "title": "Titre accrocheur", "description": "Description avec #shorts"}}
    
    Transcription : {transcript_text[:15000]} # Limité pour éviter de dépasser le contexte
    """
    response = model.generate_content(prompt)
    try:
        # Nettoyage de la réponse si Gemini inclut des balises markdown
        cleaned_json = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned_json)
        return data
    except Exception as e:
        print(f"Erreur parsing JSON Gemini: {e}\nRéponse brute: {response.text}")
        return None

# --- 2. TRAITEMENT VIDÉO (OPENCV & MOVIEPY) ---
def download_and_process_video(video_id, segment_data, transcript_data):
    """Télécharge la vidéo, crop intelligemment (9:16) et ajoute les sous-titres."""
    raw_video = "raw_video.mp4"
    cropped_video = "cropped_video.mp4"
    final_video = "final_short.mp4"

    # Trouver les timestamps précis à partir des textes
    start_time = 0
    end_time = 30 # Fallback
    for t in transcript_data:
        if segment_data['start_text'].lower()[:15] in t['text'].lower():
            start_time = t['start']
        if segment_data['end_text'].lower()[:15] in t['text'].lower():
            end_time = t['start'] + t['duration']
            break

    print(f"[3] Téléchargement du segment ({start_time}s - {end_time}s)...")
    # Télécharger en 1080p max pour éviter les fichiers trop lourds
    ydl_opts = {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'outtmpl': raw_video,
        'download_ranges': yt_dlp.utils.download_range_func(None, [(start_time, end_time)]),
        'quiet': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

    print("[4] Recadrage intelligent (Smart Cropping OpenCV)...")
    # Utilisation d'un modèle Haar basique pour la détection de visage
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    
    cap = cv2.VideoCapture(raw_video)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    
    target_width = int(height * (9/16)) # Format 9:16 vertical
    out = cv2.VideoWriter(cropped_video, cv2.VideoWriter_fourcc(*'mp4v'), fps, (target_width, height))

    center_x = width // 2
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)
        
        # Lissage des mouvements : Si un visage est détecté, ajuster doucement le centre
        if len(faces) > 0:
            (x, y, w, h) = faces[0]
            face_center = x + (w // 2)
            # Lissage exponentiel (0.1) pour éviter les saccades
            center_x = int(center_x * 0.9 + face_center * 0.1) 
            
        # Limites du recadrage
        start_x = max(0, center_x - (target_width // 2))
        if start_x + target_width > width:
            start_x = width - target_width
            
        cropped_frame = frame[:, start_x:start_x+target_width]
        out.write(cropped_frame)

    cap.release()
    out.release()

    print("[5] Génération des sous-titres dynamiques (MoviePy)...")
    clip = VideoFileClip(cropped_video)
    
    # Création simplifiée de sous-titres centraux (approximation de durée)
    text_clip = TextClip(
        segment_data['title'], 
        fontsize=60, color='white', font='Arial-Bold',
        stroke_color='black', stroke_width=4,
        size=(target_width * 0.9, None), method='caption'
    ).set_position(('center', 'center')).set_duration(clip.duration)
    
    final_clip = CompositeVideoClip([clip, text_clip])
    final_clip.write_videofile(final_video, codec="libx264", audio_codec="aac", fps=30, preset="ultrafast")
    
    return final_video

# --- 3. AUTHENTIFICATION OAUTH2 & UPLOAD YOUTUBE ---
def get_authenticated_service():
    """Gère l'authentification OAuth2 et rafraîchit le token automatiquement."""
    print("[6] Authentification YouTube Data v3...")
    
    # Ces secrets doivent être injectés via GitHub Secrets
    client_id = os.environ.get("YT_CLIENT_ID")
    client_secret = os.environ.get("YT_CLIENT_SECRET")
    refresh_token = os.environ.get("YT_REFRESH_TOKEN")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )

    if not creds.valid:
        # Rafraîchissement automatique garanti à chaque exécution si nécessaire
        creds.refresh(Request())
        
    return build('youtube', 'v3', credentials=creds)

def upload_short(youtube, file_path, metadata):
    """Publie la vidéo en tant que YouTube Short."""
    print("[7] Upload de la vidéo sur YouTube...")
    body = {
        'snippet': {
            'title': metadata['title'][:100],
            'description': metadata['description'],
            'categoryId': '22' # People & Blogs
        },
        'status': {
            'privacyStatus': 'public', 
            'selfDeclaredMadeForKids': False
        }
    }
    
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True, mimetype='video/mp4')
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    
    response = request.execute()
    print(f"✅ Succès ! Short publié : https://youtube.com/shorts/{response['id']}")

# --- MAIN WORKFLOW ---
if __name__ == "__main__":
    vid_id, text, transcript = get_latest_video_and_transcript()
    if vid_id and text:
        segment = identify_viral_segment(text)
        if segment:
            final_mp4 = download_and_process_video(vid_id, segment, transcript)
            yt_service = get_authenticated_service()
            upload_short(yt_service, final_mp4, segment)
        else:
            print("Échec de la génération du segment par Gemini.")
