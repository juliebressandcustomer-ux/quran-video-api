#!/usr/bin/env python3
"""
API Flask pour n8n - Génération de vidéos Coran
Compatible avec https://alquran.cloud/api
Usage: python3 api_n8n.py
"""

from flask import Flask, request, send_file, jsonify
from werkzeug.utils import secure_filename
import os
import subprocess
import re
import math
from pathlib import Path
import json
import uuid
from datetime import datetime
import threading
import requests
from urllib.parse import urlparse
import sys
import time
from collections import deque
import builtins

# ============================================
# RATE LIMITING POUR RAILWAY (CRITIQUE!)
# ============================================
class RateLimitedPrint:
    """Limite les print() à 15/sec pour éviter Railway rate limit de 500/sec"""
    def __init__(self, max_per_second=15):
        self.max_per_second = max_per_second
        self.timestamps = deque(maxlen=max_per_second)
        self.original_print = builtins.print  # Use builtins module
        self.dropped = 0
        self.last_report = time.time()
        
    def __call__(self, *args, **kwargs):
        now = time.time()
        
        # Nettoyer les timestamps de plus d'1 seconde
        while self.timestamps and now - self.timestamps[0] > 1.0:
            self.timestamps.popleft()
        
        # Si on est sous la limite, log normalement
        if len(self.timestamps) < self.max_per_second:
            self.timestamps.append(now)
            self.original_print(*args, **kwargs, file=sys.stderr)
            
            # Reporter les messages droppés toutes les 5 secondes
            if self.dropped > 0 and now - self.last_report > 5.0:
                self.original_print(f"⚠️ {self.dropped} logs supprimés (Railway rate limit)", file=sys.stderr)
                self.dropped = 0
                self.last_report = now
        else:
            self.dropped += 1

# Remplacer print() globalement
print = RateLimitedPrint(max_per_second=15)

# ============================================
# SANITIZATION DES NOMS DE FICHIERS
# ============================================
def sanitize_filename(filename):
    """
    Nettoie un nom de fichier pour le rendre URL-safe
    - Remplace espaces par underscores
    - Remplace : par -
    - Supprime caractères invalides
    - Limite la longueur à 100 caractères
    """
    # Enlever .mp4 si présent
    if filename.endswith('.mp4'):
        filename = filename[:-4]
    
    # Remplacer les caractères problématiques
    filename = filename.replace(' ', '_')
    filename = filename.replace(':', '-')
    filename = filename.replace('/', '-')
    filename = filename.replace('\\', '-')
    
    # Garder seulement: lettres, chiffres, -, _, .
    filename = re.sub(r'[^a-zA-Z0-9\-_.]', '', filename)
    
    # Limiter la longueur
    if len(filename) > 100:
        filename = filename[:100]
    
    return filename
from unicodedata import normalize
import random
import glob

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['TEMP_FOLDER'] = 'temp'
app.config['BACKGROUNDS_FOLDER'] = 'backgrounds'  # Fonds par défaut

# Créer les dossiers
for folder in [app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER'], 
               app.config['TEMP_FOLDER'], app.config['BACKGROUNDS_FOLDER']]:
    Path(folder).mkdir(exist_ok=True)

# Configuration par défaut
DEFAULT_CONFIG = {
    "font_name": "KFGQPC Uthman Taha Naskh Regular",
    "font_size": 150,
    "alignment": 5,
    "outline": 5,
    "shadow": 3,
    "words_per_segment": 4,
    "min_segments": 1,
    "max_segments": 50,
    "crf": 23,  # Qualité équilibrée pour Full HD
    "preset": "fast",  # Fast = bon équilibre qualité/vitesse/RAM pour Full HD
    "audio_bitrate": "128k",
    "clean_text": True,
    "aggressive_clean": False,
    
    # 🌙 Mode Jour/Nuit
    "night_mode": False,  # False = jour (texte blanc), True = nuit (texte noir)
    
    # ✨ TRANSITIONS AUTOMATIQUES (NOUVEAU)
    "transitions_enabled": True,  # Activer les transitions
    "text_animation": "auto",  # Options: auto, fade, slide_up, slide_down, zoom_in, blur_in, none
    "text_animation_duration": 0.4,  # Durée animation d'entrée (secondes)
    "text_exit_animation": True,  # Animation de sortie
    "video_transitions": False,  # Transitions vidéo entre segments (plus lourd)
    "video_transition_style": "crossfade",  # Options: crossfade, fade_black, zoom, none
    "transition_duration": 0.5,  # Durée transitions vidéo (secondes)
    
    # 🔄 TRANSITIONS ENTRE RÉPÉTITIONS BACKGROUND (NOUVEAU)
    "loop_transition": True,  # Transition entre chaque loop du background
    "loop_transition_duration": 1.0,  # Durée du crossfade entre loops (secondes)
    
    # ✨ Effets de Fade (anciens - compatibilité)
    "fade_in": True,  # Fade in au début de chaque segment
    "fade_out": True,  # Fade out à la fin de chaque segment
    "fade_duration": 0.3,  # Durée du fade en secondes
    
    # 🎙️ Réciter
    "reciter": "ar.alafasy",  # Par défaut: Mishary Al-Afasy
    "reciter_name": "",  # Nom à afficher (ex: "Mishary Al-Afasy")
    "show_reciter": True,  # Afficher le nom du récitateur
    "reciter_duration": 3,  # Durée d'affichage en secondes
    "reciter_font": "",  # Police du récitateur (vide = même que verset)
    "reciter_font_size": 0,  # Taille police récitateur (0 = auto 40% du verset)
    "reciter_position": "below",  # Position: "below" (sous le verset) ou "above" (au-dessus)
    "reciter_spacing": 80,  # Espacement vertical par rapport au verset (en pixels)
    
    # 📱 Résolution
    "resolution": "1080p",  # Options: 1080p, 720p, vertical, square, 4k
}

# Stockage des jobs
jobs = {}

def clean_quran_text(text):
    """
    Nettoie le texte coranique SANS supprimer les signes coraniques
    Préserve : diacritiques, symboles de pause, Rub el Hizb, etc.
    """
    # 1. Normalisation Unicode (NFC pour préserver TOUS les diacritiques)
    text = normalize('NFC', text)
    
    # 2. NE PAS nettoyer les espaces multiples si c'est voulu dans le Coran
    # On garde juste un nettoyage minimal
    
    # 3. Supprimer UNIQUEMENT les caractères invisibles problématiques
    # (zero-width spaces, etc.) mais PAS les signes coraniques
    text = re.sub(r'[\u200B-\u200D\uFEFF]', '', text)  # Zero-width uniquement
    
    # 4. Trim seulement au début et fin
    text = text.strip()
    
    return text

def clean_quran_text_aggressive(text):
    """
    Nettoyage agressif - SUPPRIME les signes de pause et symboles
    À utiliser UNIQUEMENT si vous voulez un texte simplifié
    """
    # Normalisation
    text = normalize('NFC', text)
    
    # Supprimer les symboles coraniques spéciaux
    # ۞ (U+06DE) - Rub el Hizb
    # ۖ (U+06D6) - Small High Seen
    # ۗ (U+06D7) - Small High Qaf
    # ۘ (U+06D8) - Small High Meem initial form
    # ۙ (U+06D9) - Small High Lam Alef
    # ۚ (U+06DA) - Small High Jeem
    # ۛ (U+06DB) - Small High Three Dots
    # ۜ (U+06DC) - Small High Seen with Tash
    quran_symbols = r'[\u06D6-\u06ED\u06DE]'
    text = re.sub(quran_symbols, '', text)
    
    # Nettoyer espaces multiples
    text = re.sub(r'\s+', ' ', text)
    
    # Caractères invisibles
    text = re.sub(r'[\u200B-\u200D\uFEFF]', '', text)
    
    text = text.strip()
    return text

def remove_diacritics(text):
    """
    Supprime tous les diacritiques (harakat, tanwin, shadda, etc.)
    ATTENTION : À utiliser UNIQUEMENT si vous voulez un texte sans signes
    """
    # Plage Unicode des diacritiques arabes
    diacritics_pattern = r'[\u064B-\u065F\u0670\u06D6-\u06ED]'
    return re.sub(diacritics_pattern, '', text)

def get_best_available_font(preferred_font, fallback_fonts):
    """
    Retourne directement la police demandée par l'utilisateur
    ffmpeg fera son propre fallback si nécessaire
    """
    print(f"🔤 Police demandée: {preferred_font}")
    return preferred_font

def download_file(url, destination):
    """Télécharge un fichier depuis une URL"""
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        with open(destination, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return True
    except Exception as e:
        print(f"Erreur téléchargement {url}: {e}")
        return False

def get_audio_duration(path):
    """Récupère la durée d'un fichier audio"""
    cmd = ["ffprobe", "-v", "error", "-show_entries", 
           "format=duration", "-of", "default=nw=1:nk=1", path]
    try:
        return float(subprocess.check_output(cmd).decode().strip())
    except:
        return 0.0

def ass_time(t):
    """Convertit un temps en secondes au format ASS"""
    cs = int(round(t * 100))
    h = cs // (3600 * 100)
    cs -= h * 3600 * 100
    m = cs // (60 * 100)
    cs -= m * 60 * 100
    s = cs // 100
    cs -= s * 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def create_segments(text, config):
    """Découpe le texte en segments"""
    text = text.strip(" ,،")
    words = [w for w in re.split(r"\s+", text) if w]
    
    if not words:
        return []
    
    wps = config['words_per_segment']
    segments = []
    
    # Découpage simple selon words_per_segment
    for i in range(0, len(words), wps):
        segments.append(" ".join(words[i:i+wps]))
    
    # Ne réajuster QUE si les segments sont trop nombreux (pour éviter des sous-titres illisibles)
    # On retire les limites min pour respecter le choix de l'utilisateur
    if len(segments) > config['max_segments'] and len(words) > 0:
        wps = math.ceil(len(words) / config['max_segments'])
        segments = []
        for i in range(0, len(words), wps):
            segments.append(" ".join(words[i:i+wps]))
    
    return segments

def generate_text_animation_effect(animation_type, duration, total_duration, exit_animation=True, screen_height=1080):
    """
    Génère les tags ASS pour différents types d'animations
    
    Tags ASS utilisables:
    - \\fad(in, out) : fade in/out
    - \\move(x1,y1,x2,y2,t1,t2) : mouvement
    - \\fscx, \\fscy : échelle X/Y
    - \\blur : flou
    - \\t : transition temporelle
    """
    
    in_ms = int(duration * 1000)
    out_ms = int(duration * 1000) if exit_animation else 0
    
    # Position centrale (960 = centre horizontal pour 1920, 540 = centre vertical pour 1080)
    center_x = screen_height * 16 // 9 // 2 if screen_height < 1920 else 960
    center_y = screen_height // 2
    
    if animation_type == 'fade':
        # Fade classique
        return f"{{\\fad({in_ms},{out_ms})}}"
    
    elif animation_type == 'slide_up':
        # Glisse vers le haut
        offset = 100
        start_y = center_y + offset
        return f"{{\\move({center_x},{start_y},{center_x},{center_y},0,{in_ms})\\fad({in_ms},{out_ms})}}"
    
    elif animation_type == 'slide_down':
        # Glisse vers le bas
        offset = 100
        start_y = center_y - offset
        return f"{{\\move({center_x},{start_y},{center_x},{center_y},0,{in_ms})\\fad({in_ms},{out_ms})}}"
    
    elif animation_type == 'zoom_in':
        # Zoom depuis petit vers taille normale
        return f"{{\\fad({in_ms},{out_ms})\\t(0,{in_ms},\\fscx120\\fscy120)\\t(0,{in_ms},\\fscx100\\fscy100)}}"
    
    elif animation_type == 'blur_in':
        # Flou qui devient net
        return f"{{\\fad({in_ms},{out_ms})\\blur10\\t(0,{in_ms},\\blur0)}}"
    
    else:  # none
        return ""

def generate_ass(text, audio_path, output_ass, config):
    """Génère le fichier ASS avec nettoyage du texte et détection de police"""
    
    # Nettoyer le texte selon les options
    if config.get('aggressive_clean', False):
        text = clean_quran_text_aggressive(text)
        print(f"🧹 Nettoyage agressif (symboles supprimés): {text[:50]}...")
    elif config.get('clean_text', True):
        text = clean_quran_text(text)
        print(f"✨ Nettoyage minimal (symboles préservés): {text[:50]}...")
    else:
        print(f"📝 Texte brut (aucun nettoyage): {text[:50]}...")
    
    # Supprimer les diacritiques si demandé
    if config.get('remove_diacritics', False):
        text = remove_diacritics(text)
        print(f"🔤 Diacritiques supprimés")
    
    segments = create_segments(text, config)
    
    if not segments:
        return False
    
    duration = get_audio_duration(audio_path)
    usable = max(duration, 0.1)
    
    weights = [max(len(s.replace(" ", "")), 1) for s in segments]
    total = sum(weights)
    
    # Utiliser directement la police demandée par l'utilisateur
    font = config.get('font_name', DEFAULT_CONFIG['font_name'])
    
    # Mode Jour/Nuit
    night_mode = config.get('night_mode', False)
    if night_mode:
        # Mode Nuit: Texte noir sur fond clair
        primary_color = "&H00000000"  # Noir
        outline_color = "&H00FFFFFF"  # Blanc
        print(f"🌙 Mode NUIT activé: texte noir")
    else:
        # Mode Jour: Texte blanc sur fond sombre
        primary_color = "&H00FFFFFF"  # Blanc
        outline_color = "&H00101010"  # Noir/gris foncé
        print(f"☀️  Mode JOUR activé: texte blanc")
    
    print(f"🔤 Police utilisée: {font}")
    
    # Effets de fade
    fade_in = config.get('fade_in', True)
    fade_out = config.get('fade_out', True)
    fade_duration = config.get('fade_duration', 0.3)
    
    if fade_in or fade_out:
        print(f"✨ Fade activé - In: {fade_in}, Out: {fade_out}, Durée: {fade_duration}s")
    
    # Configuration du récitateur
    reciter_name = config.get('reciter_name', '')
    show_reciter = config.get('show_reciter', True) and reciter_name
    reciter_duration = config.get('reciter_duration', 3)
    
    if show_reciter:
        print(f"🎙️  Récitateur affiché: {reciter_name} (pendant {reciter_duration}s)")
    
    # Adapter la résolution pour PlayRes
    resolution = config.get('resolution', '1080p')
    if resolution == 'vertical':
        play_res_x = 1080  # Full HD vertical
        play_res_y = 1920
    elif resolution == 'square':
        play_res_x = 1080  # Full HD carré
        play_res_y = 1080
    elif resolution == '4k':
        play_res_x = 3840  # 4K complet
        play_res_y = 2160
    elif resolution == '720p':
        play_res_x = 1280
        play_res_y = 720
    else:  # 1080p
        play_res_x = 1920
        play_res_y = 1080
    
    # Créer le style pour le récitateur (petit, orange, position ajustable)
    reciter_style = ""
    if show_reciter:
        # Police du récitateur (peut être différente du verset)
        reciter_font = config.get('reciter_font', '') or font
        
        # Taille de police du récitateur
        if config.get('reciter_font_size', 0) > 0:
            reciter_font_size = int(config['reciter_font_size'])
        else:
            reciter_font_size = int(config['font_size'] * 0.4)  # 40% de la taille du verset par défaut
        
        # Position du récitateur
        reciter_position = config.get('reciter_position', 'below')
        reciter_spacing = config.get('reciter_spacing', 80)
        
        # Orange: &H0000A5FF (format BGR en hexa)
        if reciter_position == 'above':
            # Au-dessus du verset
            # Alignment 8 = haut centre
            alignment = 8
            # Distance depuis le haut = centre - taille verset - espacement
            reciter_margin_v = int(play_res_y / 2 - config['font_size'] - reciter_spacing)
        else:
            # En dessous du verset (par défaut)
            # Alignment 2 = bas centre
            alignment = 2
            # Distance depuis le bas = hauteur - (centre + espacement)
            reciter_margin_v = int(play_res_y - (play_res_y / 2 + reciter_spacing))
        
        print(f"📍 Position récitateur: {reciter_position}, MarginV: {reciter_margin_v}, Alignment: {alignment}")
        
        reciter_style = f"\nStyle: Reciter,{reciter_font},{reciter_font_size},&H0000A5FF,&H000000FF,{outline_color},&H00000000,0,0,0,0,100,100,0,0,1,{config['outline']},{config['shadow']},{alignment},80,80,{reciter_margin_v},1"
    
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Verse,{font},{config['font_size']},{primary_color},&H000000FF,{outline_color},&H00000000,0,0,0,0,100,100,0,0,1,{config['outline']},{config['shadow']},{config['alignment']},80,80,40,1{reciter_style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    events = []
    t = 0.0
    for seg, w in zip(segments, weights):
        segdur = usable * (w / total)
        start = t
        end = min(t + segdur, usable)
        if end - start < 0.35:
            end = min(start + 0.35, usable)
        events.append((start, end, seg))
        t = end
    
    if events:
        start_last = events[-1][0]
        events[-1] = (start_last, usable, events[-1][2])
    
    lines = []
    
    # Ajouter le nom du récitateur au début (si activé)
    if show_reciter:
        reciter_fade_in_ms = int(fade_duration * 1000) if fade_in else 0
        reciter_fade_out_ms = int(fade_duration * 1000) if fade_out else 0
        reciter_fade = f"{{\\fad({reciter_fade_in_ms},{reciter_fade_out_ms})}}"
        
        reciter_line = f"Dialogue: 0,{ass_time(0)},{ass_time(reciter_duration)},Reciter,,0,0,0,,{reciter_fade}{reciter_name}"
        lines.append(reciter_line)
        print(f"✅ Ligne récitateur ajoutée: 0s -> {reciter_duration}s")
    
    # Ajouter les versets
    for start, end, seg in events:
        # 🎨 NOUVELLES ANIMATIONS
        transitions_enabled = config.get('transitions_enabled', True)
        
        if transitions_enabled:
            text_animation = config.get('text_animation', 'auto')
            text_exit = config.get('text_exit_animation', True)
            anim_duration = config.get('text_animation_duration', 0.4)
            
            # Choisir l'animation
            if text_animation == 'auto':
                # Alterner les animations
                animations = ['fade', 'slide_up', 'zoom_in', 'blur_in']
                current_anim = animations[events.index((start, end, seg)) % len(animations)]
            else:
                current_anim = text_animation
            
            # Générer l'effet d'animation
            fade_effect = generate_text_animation_effect(
                current_anim, 
                anim_duration, 
                end - start,
                text_exit,
                play_res_y
            )
        else:
            # Mode ancien (compatibilité)
            fade_in = config.get('fade_in', True)
            fade_out = config.get('fade_out', True)
            fade_duration = config.get('fade_duration', 0.3)
            
            if fade_in or fade_out:
                fade_in_ms = int(fade_duration * 1000) if fade_in else 0
                fade_out_ms = int(fade_duration * 1000) if fade_out else 0
                fade_effect = f"{{\\fad({fade_in_ms},{fade_out_ms})}}"
            else:
                fade_effect = ""
        
        # Ajouter la ligne avec effet
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Verse,,0,0,0,,{fade_effect}{seg}")
    
    with open(output_ass, 'w', encoding='utf-8') as f:
        f.write(header + "\n".join(lines) + "\n")
    
    print(f"📝 {len(segments)} segments créés")
    return True
    
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Verse,{config['font_name']},{config['font_size']},&H00FFFFFF,&H000000FF,&H00101010,&H00000000,0,0,0,0,100,100,0,0,1,{config['outline']},{config['shadow']},{config['alignment']},80,80,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    events = []
    t = 0.0
    for seg, w in zip(segments, weights):
        segdur = usable * (w / total)
        start = t
        end = min(t + segdur, usable)
        if end - start < 0.35:
            end = min(start + 0.35, usable)
        events.append((start, end, seg))
        t = end
    
    if events:
        start_last = events[-1][0]
        events[-1] = (start_last, usable, events[-1][2])
    
    lines = []
    for start, end, seg in events:
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Verse,,0,0,0,,{seg}")
    
    with open(output_ass, 'w', encoding='utf-8') as f:
        f.write(header + "\n".join(lines) + "\n")
    
    return True

def generate_video(background_video, audio_file, ass_file, output_video, config):
    """Génère la vidéo finale avec ffmpeg avec transitions entre répétitions du background"""
    
    # Obtenir les durées
    audio_duration = get_audio_duration(audio_file)
    video_duration = get_audio_duration(background_video)
    
    print(f"⏱️  Audio: {audio_duration:.1f}s | Background: {video_duration:.1f}s")
    
    # Définir les résolutions
    resolution = config.get('resolution', '1080p')
    
    resolutions = {
        '1080p': {'width': 1920, 'height': 1080, 'name': '1080p (16:9 YouTube)'},
        '720p': {'width': 1280, 'height': 720, 'name': '720p (16:9 Standard)'},
        'vertical': {'width': 1080, 'height': 1920, 'name': 'Vertical Full HD (9:16 TikTok/Reels/Shorts)'},
        'square': {'width': 1080, 'height': 1080, 'name': 'Carré Full HD (1:1 Instagram)'},
        '4k': {'width': 3840, 'height': 2160, 'name': '4K (16:9 Ultra HD)'}
    }
    
    if resolution not in resolutions:
        resolution = '1080p'
    
    res = resolutions[resolution]
    width = res['width']
    height = res['height']
    
    print(f"📐 Résolution: {res['name']} ({width}x{height})")
    
    # 🔄 NOUVEAU : Gestion des transitions entre loops
    loop_transition = config.get('loop_transition', True)
    loop_transition_duration = config.get('loop_transition_duration', 1.0)
    
    # Construire le filtre vidéo
    if video_duration < audio_duration:
        # Background plus court → LOOP avec transitions
        loops_needed = int(audio_duration / video_duration) + 1
        print(f"🔄 Background loop activé: {loops_needed} répétitions")
        
        if loop_transition and loops_needed > 1:
            # ✨ AVEC TRANSITIONS ENTRE LOOPS
            print(f"✨ Crossfade entre loops activé: {loop_transition_duration}s")
            
            # Créer un filtre avec xfade entre chaque répétition
            # Strategy: Concaténer les vidéos avec crossfade
            video_filter = create_loop_with_transitions(
                loops_needed, 
                video_duration, 
                audio_duration,
                width, 
                height, 
                ass_file,
                loop_transition_duration
            )
            
            cmd = [
                "ffmpeg", "-stream_loop", str(loops_needed), "-i", background_video, "-i", audio_file,
                "-filter_complex", f"[1:a]apad=pad_dur=1[a];{video_filter}",
                "-map", "[v]", "-map", "[a]",
                "-t", str(audio_duration),
                "-c:v", "libx264", 
                "-crf", str(config['crf']),
                "-preset", config['preset'],
                "-c:a", "aac", 
                "-b:a", config['audio_bitrate'],
                "-y", output_video
            ]
        else:
            # SANS TRANSITIONS (ancien comportement)
            video_filter = f"[0:v]loop={loops_needed}:size=1:start=0,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,ass={ass_file}:fontsdir=[v]"
            
            cmd = [
                "ffmpeg", "-stream_loop", str(loops_needed), "-i", background_video, "-i", audio_file,
                "-filter_complex", f"[1:a]apad=pad_dur=1[a];{video_filter}",
                "-map", "[v]", "-map", "[a]",
                "-t", str(audio_duration),
                "-c:v", "libx264", 
                "-crf", str(config['crf']),
                "-preset", config['preset'],
                "-c:a", "aac", 
                "-b:a", config['audio_bitrate'],
                "-y", output_video
            ]
    else:
        # Background plus long ou égal → Normal (pas de loop)
        print(f"✅ Background suffisamment long")
        
        video_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,ass={ass_file}:fontsdir=."
        
        cmd = [
            "ffmpeg", "-i", background_video, "-i", audio_file,
            "-filter_complex", "[1:a]apad=pad_dur=1[a]",
            "-vf", video_filter,
            "-map", "0:v", "-map", "[a]",
            "-t", str(audio_duration),
            "-c:v", "libx264", 
            "-crf", str(config['crf']),
            "-preset", config['preset'],
            "-c:a", "aac", 
            "-b:a", config['audio_bitrate'],
            "-y", output_video
        ]
    
    try:
        # Optimisations FFmpeg
        memory_opts = [
            "-max_muxing_queue_size", "1024",
            "-bufsize", "3M",
            "-maxrate", "4M",
            "-threads", "2",
            "-movflags", "+faststart"
        ]
        
        subprocess.run(cmd + memory_opts, 
                      check=True, 
                      stderr=subprocess.DEVNULL, 
                      stdout=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Erreur ffmpeg: {e}")
        return False

def create_loop_with_transitions(loops_needed, video_duration, total_duration, width, height, ass_file, transition_duration):
    """
    Crée un filtre ffmpeg complexe avec crossfade entre chaque répétition
    
    Exemple pour 3 loops:
    [0:v] split=3 [v1][v2][v3]
    [v1] trim, setpts [v1trim]
    [v2] trim, setpts [v2trim]
    [v3] trim, setpts [v3trim]
    [v1trim][v2trim] xfade=transition=fade:duration=1:offset=9 [vx1]
    [vx1][v3trim] xfade=transition=fade:duration=1:offset=19 [vx2]
    [vx2] scale, pad, ass [v]
    """
    
    # Pour simplifier avec stream_loop, on utilise une approche différente
    # On applique juste un fade au début et à la fin de chaque cycle
    
    # Calculer le point de jonction (où finit un loop et commence le suivant)
    # On applique un crossfade sur les X dernières secondes de chaque loop
    
    offset = video_duration - transition_duration
    
    # Filtre simplifié : on ajoute un fade in/out aux points de jonction
    # C'est une approximation car faire un vrai crossfade avec stream_loop est complexe
    
    # Solution simple : ajouter des fades périodiques
    fade_filter = ""
    for i in range(1, loops_needed):
        loop_start = i * video_duration
        if i == 1:
            fade_filter = f"fade=t=out:st={loop_start - transition_duration}:d={transition_duration}:alpha=0,fade=t=in:st={loop_start}:d={transition_duration}:alpha=1"
        else:
            fade_filter += f",fade=t=out:st={loop_start - transition_duration}:d={transition_duration}:alpha=0,fade=t=in:st={loop_start}:d={transition_duration}:alpha=1"
    
    # Combiner avec scale et sous-titres
    if fade_filter:
        video_filter = f"[0:v]loop={loops_needed}:size=1:start=0,{fade_filter},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,ass={ass_file}:fontsdir=[v]"
    else:
        video_filter = f"[0:v]loop={loops_needed}:size=1:start=0,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,ass={ass_file}:fontsdir=[v]"
    
    return video_filter

def process_video_job(job_id, verse_text, audio_path, background_path, config, output_name):
    """Traite une vidéo en arrière-plan"""
    job = jobs[job_id]
    
    try:
        # Mise à jour: génération ASS
        job['status'] = 'generating_subtitles'
        job['progress'] = 30
        
        ass_path = Path(app.config['TEMP_FOLDER']) / f"{job_id}.ass"
        if not generate_ass(verse_text, audio_path, str(ass_path), config):
            job['status'] = 'error'
            job['error'] = 'Erreur génération des sous-titres'
            return
        
        # Mise à jour: génération vidéo
        job['status'] = 'generating_video'
        job['progress'] = 60
        
        output_path = Path(app.config['OUTPUT_FOLDER']) / f"{output_name}.mp4"
        if not generate_video(background_path, audio_path, str(ass_path), str(output_path), config):
            job['status'] = 'error'
            job['error'] = 'Erreur génération de la vidéo'
            return
        
        # Terminé
        job['status'] = 'completed'
        job['progress'] = 100
        job['output_path'] = str(output_path)
        job['download_url'] = f"/api/download/{output_name}.mp4"
        job['finished_at'] = datetime.now().isoformat()
        
        print(f"✅ Vidéo {job_id} générée: {output_path}")
        
    except Exception as e:
        job['status'] = 'error'
        job['error'] = str(e)
        print(f"❌ Erreur job {job_id}: {e}")

@app.route('/api/generate', methods=['POST'])
def api_generate():
    """
    API endpoint pour n8n
    
    Body JSON:
    {
        "verse_text": "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ",
        "audio_url": "https://cdn.islamic.network/quran/audio/128/ar.alafasy/1.mp3",
        "background": "default",  // ou URL
        "output_name": "al_fatiha_1",  // optionnel
        "config": {  // optionnel
            "quality": "fast",
            "font_size": 72,
            "words_per_segment": 4
        }
    }
    
    Response:
    {
        "success": true,
        "job_id": "abc123",
        "status": "processing",
        "status_url": "/api/status/abc123",
        "estimated_time": 120  // secondes
    }
    """
    try:
        data = request.get_json()
        
        # Validation
        if not data:
            return jsonify({'error': 'Body JSON requis'}), 400
        
        verse_text = data.get('verse_text', '').strip()
        audio_url = data.get('audio_url', '').strip()
        
        if not verse_text:
            return jsonify({'error': 'verse_text requis'}), 400
        if not audio_url:
            return jsonify({'error': 'audio_url requis'}), 400
        
        # Générer un job ID
        job_id = str(uuid.uuid4())[:8]
        job_folder = Path(app.config['UPLOAD_FOLDER']) / job_id
        job_folder.mkdir(exist_ok=True)
        
        # Configuration
        config = DEFAULT_CONFIG.copy()
        custom_config = data.get('config', {})
        
        # DEBUG: Afficher la config reçue
        print(f"📦 Config reçue de n8n:")
        print(f"   - reciter_name: {custom_config.get('reciter_name', 'NON DÉFINI')}")
        print(f"   - show_reciter: {custom_config.get('show_reciter', 'NON DÉFINI')}")
        print(f"   - resolution: {custom_config.get('resolution', 'NON DÉFINI')}")
        print(f"   - font_size: {custom_config.get('font_size', 'NON DÉFINI')}")
        
        # Merger TOUTE la config custom avec les defaults
        config.update(custom_config)
        
        # Gérer les presets de qualité
        if 'quality' in custom_config:
            quality = custom_config['quality']
            if quality == 'draft':
                config['crf'] = 28
                config['preset'] = 'ultrafast'
            elif quality == 'fast':
                config['crf'] = 23
                config['preset'] = 'fast'
            elif quality == 'standard':
                config['crf'] = 21
                config['preset'] = 'medium'
            elif quality == 'hq':
                config['crf'] = 18
                config['preset'] = 'slow'
        
        # S'assurer que font_size et words_per_segment sont des entiers
        if 'font_size' in config:
            config['font_size'] = int(config['font_size'])
        if 'words_per_segment' in config:
            config['words_per_segment'] = int(config['words_per_segment'])
        
        print(f"✅ Config finale mergée:")
        print(f"   - resolution: {config.get('resolution')}")
        print(f"   - reciter_name: {config.get('reciter_name')}")
        print(f"   - show_reciter: {config.get('show_reciter')}")
        
        # Télécharger l'audio
        print(f"📥 Téléchargement audio: {audio_url}")
        audio_path = job_folder / "audio.mp3"
        if not download_file(audio_url, str(audio_path)):
            return jsonify({'error': 'Erreur téléchargement audio'}), 500
        
        # Gérer le background
        background_input = data.get('background', 'default')
        
        if background_input == 'default':
            # Utiliser le fond par défaut
            default_bg = Path(app.config['BACKGROUNDS_FOLDER']) / "default.mp4"
            if not default_bg.exists():
                return jsonify({'error': 'Fond par défaut introuvable. Placez un fichier default.mp4 dans backgrounds/'}), 500
            background_path = str(default_bg)
        elif background_input.startswith('http'):
            # Télécharger depuis URL
            print(f"📥 Téléchargement background: {background_input}")
            background_path = job_folder / "background.mp4"
            if not download_file(background_input, str(background_path)):
                return jsonify({'error': 'Erreur téléchargement background'}), 500
            background_path = str(background_path)
        else:
            # Fichier local dans backgrounds/
            local_bg = Path(app.config['BACKGROUNDS_FOLDER']) / background_input
            
            # 🎲 Si c'est un dossier, choisir une vidéo aléatoire dedans
            if local_bg.is_dir():
                # Chercher tous les fichiers vidéo dans le dossier
                video_files = list(local_bg.glob('*.mp4')) + list(local_bg.glob('*.mov')) + \
                             list(local_bg.glob('*.avi')) + list(local_bg.glob('*.mkv'))
                
                if not video_files:
                    return jsonify({'error': f'Aucune vidéo trouvée dans le dossier {background_input}'}), 404
                
                # Choisir aléatoirement
                background_path = str(random.choice(video_files))
                print(f"🎲 Vidéo choisie aléatoirement: {Path(background_path).name}")
            
            # Si c'est un fichier direct
            elif local_bg.exists():
                background_path = str(local_bg)
            
            # Ni fichier ni dossier trouvé
            else:
                return jsonify({'error': f'Fond {background_input} introuvable dans backgrounds/ (ni fichier ni dossier)'}), 404
        
        # Nom de sortie
        output_name = sanitize_filename(data.get('output_name', job_id))
        
        # Créer le job
        jobs[job_id] = {
            'id': job_id,
            'status': 'downloading',
            'progress': 0,
            'verse_text': verse_text[:50] + '...' if len(verse_text) > 50 else verse_text,
            'started_at': datetime.now().isoformat(),
            'finished_at': None,
            'output_path': None,
            'download_url': None,
            'error': None
        }
        
        # Lancer le traitement en arrière-plan
        thread = threading.Thread(
            target=process_video_job,
            args=(job_id, verse_text, str(audio_path), background_path, config, output_name)
        )
        thread.daemon = True
        thread.start()
        
        print(f"🚀 Job {job_id} démarré")
        
        return jsonify({
            'success': True,
            'job_id': job_id,
            'status': 'processing',
            'status_url': f"/api/status/{job_id}",
            'estimated_time': 120  # 2 minutes en mode fast
        }), 202
    
    except Exception as e:
        print(f"❌ Erreur API: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/status/<job_id>', methods=['GET'])
def api_status(job_id):
    """
    Vérifie le statut d'un job
    
    Response:
    {
        "job_id": "abc123",
        "status": "completed",  // downloading, generating_subtitles, generating_video, completed, error
        "progress": 100,
        "download_url": "/api/download/abc123.mp4",
        "started_at": "2024-01-09T10:30:00",
        "finished_at": "2024-01-09T10:32:15"
    }
    """
    if job_id not in jobs:
        return jsonify({'error': 'Job introuvable'}), 404
    
    return jsonify(jobs[job_id])

@app.route('/api/download/<filename>', methods=['GET'])
def api_download(filename):
    """Télécharge une vidéo générée avec option de suppression automatique"""
    file_path = Path(app.config['OUTPUT_FOLDER']) / filename
    
    if not file_path.exists():
        return jsonify({'error': 'Fichier introuvable'}), 404
    
    # Option de suppression automatique après téléchargement
    auto_delete = request.args.get('delete', 'false').lower() == 'true'
    
    response = send_file(
        str(file_path),
        as_attachment=True,
        download_name=filename,
        mimetype='video/mp4'
    )
    
    # Supprimer après envoi si demandé
    if auto_delete:
        @response.call_on_close
        def delete_file():
            try:
                if file_path.exists():
                    file_path.unlink()
                    print(f"🗑️  Fichier supprimé: {filename}")
            except Exception as e:
                print(f"❌ Erreur suppression {filename}: {e}")
    
    return response

@app.route('/api/delete/<filename>', methods=['DELETE'])
def api_delete_file(filename):
    """Supprime un fichier spécifique"""
    file_path = Path(app.config['OUTPUT_FOLDER']) / filename
    
    if not file_path.exists():
        return jsonify({'error': 'Fichier introuvable'}), 404
    
    try:
        file_path.unlink()
        print(f"🗑️  Fichier supprimé: {filename}")
        
        return jsonify({
            'success': True,
            'message': f'Fichier {filename} supprimé',
            'deleted': True
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cleanup', methods=['POST'])
def api_cleanup():
    """Supprime les vidéos anciennes ou toutes les vidéos"""
    import time
    
    data = request.json or {}
    max_age_minutes = data.get('max_age_minutes', None)
    delete_all = data.get('delete_all', False)
    
    output_folder = Path(app.config['OUTPUT_FOLDER'])
    deleted_files = []
    current_time = time.time()
    
    for file_path in output_folder.glob('*.mp4'):
        should_delete = False
        
        if delete_all:
            should_delete = True
        elif max_age_minutes:
            file_age = current_time - file_path.stat().st_mtime
            if file_age > (max_age_minutes * 60):
                should_delete = True
        
        if should_delete:
            try:
                file_path.unlink()
                deleted_files.append(file_path.name)
                print(f"🗑️  Supprimé: {file_path.name}")
            except Exception as e:
                print(f"❌ Erreur suppression {file_path.name}: {e}")
    
    return jsonify({
        'success': True,
        'deleted_count': len(deleted_files),
        'deleted_files': deleted_files
    })

@app.route('/api/storage', methods=['GET'])
def api_storage():
    """Info sur l'espace disque et les fichiers"""
    import shutil
    
    total, used, free = shutil.disk_usage("/app")
    
    output_folder = Path(app.config['OUTPUT_FOLDER'])
    files = list(output_folder.glob('*.mp4'))
    
    file_info = []
    total_size = 0
    
    for f in files:
        size = f.stat().st_size
        total_size += size
        file_info.append({
            'name': f.name,
            'size_mb': round(size / (2**20), 2),
            'age_minutes': round((time.time() - f.stat().st_mtime) / 60, 1)
        })
    
    # Trier par âge (plus vieux en premier)
    file_info.sort(key=lambda x: x['age_minutes'], reverse=True)
    
    return jsonify({
        'disk': {
            'total_gb': round(total / (2**30), 2),
            'used_gb': round(used / (2**30), 2),
            'free_gb': round(free / (2**30), 2),
            'free_percent': round((free / total) * 100, 1)
        },
        'files': file_info,
        'total_files': len(files),
        'total_size_mb': round(total_size / (2**20), 2)
    })

@app.route('/api/alquran/ayah', methods=['POST'])
def api_alquran_ayah():
    """
    Endpoint spécifique pour AlQuran Cloud API
    Récupère automatiquement le verset et l'audio depuis AlQuran Cloud
    
    Body JSON:
    {
        "surah": 1,
        "ayah": 1,
        "reciter": "ar.alafasy",  // optionnel, défaut: ar.alafasy
        "background": "default",
        "output_name": "surah_1_ayah_1"  // optionnel
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Body JSON requis'}), 400
        
        surah = data.get('surah')
        ayah = data.get('ayah')
        reciter = data.get('reciter', 'ar.alafasy')
        
        if not surah or not ayah:
            return jsonify({'error': 'surah et ayah requis'}), 400
        
        # Récupérer le texte du verset depuis AlQuran Cloud
        text_url = f"https://api.alquran.cloud/v1/ayah/{surah}:{ayah}"
        print(f"📖 Récupération texte: {text_url}")
        
        try:
            text_response = requests.get(text_url, timeout=10)
            text_response.raise_for_status()
            text_data = text_response.json()
            
            if text_data['code'] != 200:
                return jsonify({'error': 'Erreur API AlQuran Cloud (texte)'}), 500
            
            verse_text = text_data['data']['text']
        except Exception as e:
            return jsonify({'error': f'Erreur récupération texte: {str(e)}'}), 500
        
        # Construire l'URL audio
        audio_url = f"https://cdn.islamic.network/quran/audio/128/{reciter}/{surah}_{ayah}.mp3"
        
        # Nom de sortie
        output_name = sanitize_filename(data.get('output_name', f"surah_{surah}_ayah_{ayah}"))
        
        # Appeler l'endpoint de génération standard
        generation_data = {
            'verse_text': verse_text,
            'audio_url': audio_url,
            'background': data.get('background', 'default'),
            'output_name': output_name,
            'config': data.get('config', {})
        }
        
        # Rediriger vers l'endpoint de génération
        return api_generate_internal(generation_data)
    
    except Exception as e:
        print(f"❌ Erreur API AlQuran: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def api_generate_internal(data):
    """Version interne de api_generate pour réutilisation"""
    verse_text = data['verse_text']
    audio_url = data['audio_url']
    
    job_id = str(uuid.uuid4())[:8]
    job_folder = Path(app.config['UPLOAD_FOLDER']) / job_id
    job_folder.mkdir(exist_ok=True)
    
    config = DEFAULT_CONFIG.copy()
    custom_config = data.get('config', {})
    
    if 'quality' in custom_config:
        quality = custom_config['quality']
        if quality == 'draft':
            config['crf'] = 28
            config['preset'] = 'ultrafast'
        elif quality == 'fast':
            config['crf'] = 23
            config['preset'] = 'fast'
        elif quality == 'standard':
            config['crf'] = 21
            config['preset'] = 'medium'
        elif quality == 'hq':
            config['crf'] = 18
            config['preset'] = 'slow'
    
    if 'font_size' in custom_config:
        config['font_size'] = int(custom_config['font_size'])
    if 'words_per_segment' in custom_config:
        config['words_per_segment'] = int(custom_config['words_per_segment'])
    
    print(f"📥 Téléchargement audio: {audio_url}")
    audio_path = job_folder / "audio.mp3"
    if not download_file(audio_url, str(audio_path)):
        return jsonify({'error': 'Erreur téléchargement audio'}), 500
    
    background_input = data.get('background', 'default')
    
    if background_input == 'default':
        default_bg = Path(app.config['BACKGROUNDS_FOLDER']) / "default.mp4"
        if not default_bg.exists():
            return jsonify({'error': 'Fond par défaut introuvable'}), 500
        background_path = str(default_bg)
    elif background_input.startswith('http'):
        print(f"📥 Téléchargement background: {background_input}")
        background_path = job_folder / "background.mp4"
        if not download_file(background_input, str(background_path)):
            return jsonify({'error': 'Erreur téléchargement background'}), 500
        background_path = str(background_path)
    else:
        local_bg = Path(app.config['BACKGROUNDS_FOLDER']) / background_input
        
        # 🎲 Si c'est un dossier, choisir une vidéo aléatoire dedans
        if local_bg.is_dir():
            # Chercher tous les fichiers vidéo dans le dossier
            video_files = list(local_bg.glob('*.mp4')) + list(local_bg.glob('*.mov')) + \
                         list(local_bg.glob('*.avi')) + list(local_bg.glob('*.mkv'))
            
            if not video_files:
                return jsonify({'error': f'Aucune vidéo trouvée dans le dossier {background_input}'}), 404
            
            # Choisir aléatoirement
            background_path = str(random.choice(video_files))
            print(f"🎲 Vidéo choisie aléatoirement: {Path(background_path).name}")
        
        # Si c'est un fichier direct
        elif local_bg.exists():
            background_path = str(local_bg)
        
        # Ni fichier ni dossier trouvé
        else:
            return jsonify({'error': f'Fond {background_input} introuvable (ni fichier ni dossier)'}), 404

    
    output_name = sanitize_filename(data.get('output_name', job_id))
    
    jobs[job_id] = {
        'id': job_id,
        'status': 'downloading',
        'progress': 0,
        'verse_text': verse_text[:50] + '...' if len(verse_text) > 50 else verse_text,
        'started_at': datetime.now().isoformat(),
        'finished_at': None,
        'output_path': None,
        'download_url': None,
        'error': None
    }
    
    thread = threading.Thread(
        target=process_video_job,
        args=(job_id, verse_text, str(audio_path), background_path, config, output_name)
    )
    thread.daemon = True
    thread.start()
    
    print(f"🚀 Job {job_id} démarré")
    
    return jsonify({
        'success': True,
        'job_id': job_id,
        'status': 'processing',
        'status_url': f"/api/status/{job_id}",
        'estimated_time': 120
    }), 202

@app.route('/api/health', methods=['GET'])
def health():
    """Health check pour n8n"""
    return jsonify({
        'status': 'healthy',
        'version': '1.0',
        'jobs_count': len(jobs)
    })

@app.route('/api/docs', methods=['GET'])
def docs():
    """Documentation de l'API"""
    return jsonify({
        'endpoints': {
            '/api/generate': {
                'method': 'POST',
                'description': 'Génère une vidéo avec texte et audio custom',
                'body': {
                    'verse_text': 'string (requis)',
                    'audio_url': 'string URL (requis)',
                    'background': 'string: "default", URL, ou nom fichier (optionnel)',
                    'output_name': 'string (optionnel)',
                    'config': {
                        'quality': 'draft|fast|standard|hq',
                        'font_size': 'number',
                        'words_per_segment': 'number'
                    }
                }
            },
            '/api/alquran/ayah': {
                'method': 'POST',
                'description': 'Génère une vidéo depuis AlQuran Cloud API',
                'body': {
                    'surah': 'number (requis)',
                    'ayah': 'number (requis)',
                    'reciter': 'string (optionnel, défaut: ar.alafasy)',
                    'background': 'string (optionnel)',
                    'output_name': 'string (optionnel)'
                }
            },
            '/api/status/:job_id': {
                'method': 'GET',
                'description': 'Vérifie le statut d\'un job'
            },
            '/api/download/:filename': {
                'method': 'GET',
                'description': 'Télécharge une vidéo générée'
            }
        }
    })

if __name__ == '__main__':
    print("=" * 60)
    print("🎬 API Flask pour n8n - Générateur de vidéos Coran")
    print("=" * 60)
    print(f"📡 Serveur: http://localhost:8000")
    print(f"📚 Documentation: http://localhost:8000/api/docs")
    print(f"❤️  Health check: http://localhost:8000/api/health")
    print()
    print("⚠️  N'oubliez pas de placer un fichier default.mp4 dans backgrounds/")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=8000)
