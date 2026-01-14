# Railway Dockerfile pour API Coran
FROM python:3.10-slim

# Installer FFmpeg et dépendances
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fontconfig \
    fonts-liberation \
    fonts-dejavu \
    fonts-noto \
    fonts-noto-color-emoji \
    fonts-arabeyes \
    fonts-kacst-one \
    fonts-hosny-amiri \
    fonts-sil-scheherazade \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Télécharger et installer les polices coraniques KFGQPC
RUN mkdir -p /usr/share/fonts/truetype/kfgqpc && \
    cd /tmp && \
    wget -q https://github.com/aliftype/qahiri/releases/download/v1.0/Qahiri-1.0.zip && \
    unzip -q Qahiri-1.0.zip -d /usr/share/fonts/truetype/kfgqpc/ || true && \
    rm -f Qahiri-1.0.zip && \
    fc-cache -fv

# Créer le répertoire de travail
WORKDIR /app

# Copier requirements et installer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code
COPY . .

# Installer les polices personnalisées (si présentes)
RUN mkdir -p /usr/share/fonts/truetype/custom && \
    if [ -d "fonts" ]; then \
        cp fonts/*.ttf /usr/share/fonts/truetype/custom/ 2>/dev/null || true; \
        cp fonts/*.otf /usr/share/fonts/truetype/custom/ 2>/dev/null || true; \
        fc-cache -fv; \
    fi

# Créer les dossiers nécessaires
RUN mkdir -p uploads outputs temp backgrounds

# Exposer le port
EXPOSE 8000

# Commande de démarrage
CMD ["gunicorn", "api_n8n_with_reciter_4:app", "--bind", "0.0.0.0:8000", "--timeout", "600", "--workers", "2"]
