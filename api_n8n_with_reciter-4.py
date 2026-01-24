# Remplacez la fonction generate_video (ligne ~491) par ceci :

def generate_video(background_video, audio_file, ass_file, output_video, config):
    """Génère la vidéo finale - VERSION SIMPLIFIÉE STABLE"""
    
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
    
    # Construire le filtre vidéo
    if video_duration < audio_duration:
        # Background plus court → LOOP
        loops_needed = int(audio_duration / video_duration) + 1
        print(f"🔄 Background loop activé: {loops_needed} répétitions")
        
        # APPROCHE SIMPLIFIÉE - Juste stream_loop sans filtres complexes
        # Ça évite les problèmes de SIGKILL
        
        video_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,ass={ass_file}:fontsdir=."
        
        cmd = [
            "ffmpeg", 
            "-stream_loop", str(loops_needed - 1), 
            "-i", background_video, 
            "-i", audio_file,
            "-vf", video_filter,
            "-af", "apad=pad_dur=1",
            "-map", "0:v", 
            "-map", "1:a",
            "-t", str(audio_duration),
            "-c:v", "libx264", 
            "-crf", str(config['crf']),
            "-preset", config['preset'],
            "-c:a", "aac", 
            "-b:a", config['audio_bitrate'],
            "-shortest",
            "-y", output_video
        ]
    else:
        # Background plus long ou égal → Normal
        print(f"✅ Background suffisamment long")
        
        video_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,ass={ass_file}:fontsdir=."
        
        cmd = [
            "ffmpeg", 
            "-i", background_video, 
            "-i", audio_file,
            "-vf", video_filter,
            "-af", "apad=pad_dur=1",
            "-map", "0:v", 
            "-map", "1:a",
            "-t", str(audio_duration),
            "-c:v", "libx264", 
            "-crf", str(config['crf']),
            "-preset", config['preset'],
            "-c:a", "aac", 
            "-b:a", config['audio_bitrate'],
            "-y", output_video
        ]
    
    try:
        # Optimisations FFmpeg simples
        memory_opts = [
            "-max_muxing_queue_size", "1024",
            "-movflags", "+faststart"
        ]
        
        # IMPORTANT: Afficher la commande pour debug
        print(f"🎬 Commande ffmpeg: {' '.join(cmd[:10])}...")
        
        result = subprocess.run(
            cmd + memory_opts, 
            check=True, 
            capture_output=True,
            text=True,
            timeout=600  # Timeout de 10 minutes
        )
        
        print(f"✅ Vidéo générée avec succès")
        return True
        
    except subprocess.TimeoutExpired:
        print(f"⏱️ TIMEOUT: La génération a pris plus de 10 minutes")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ Erreur ffmpeg:")
        print(f"   Return code: {e.returncode}")
        if e.stderr:
            print(f"   Stderr: {e.stderr[:500]}")
        return False
    except Exception as e:
        print(f"❌ Erreur inattendue: {e}")
        return False
