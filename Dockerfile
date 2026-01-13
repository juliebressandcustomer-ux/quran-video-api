# Railway Dockerfile pour API Coran
FROM python:3.10-slim

# Installer FFmpeg et dépendances
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fontconfig \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Créer le répertoire de travail
WORKDIR /app

# Copier requirements et installer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code
COPY . .

# Créer les dossiers nécessaires
RUN mkdir -p uploads outputs temp backgrounds

# Exposer le port
EXPOSE 8000

# Commande de démarrage
CMD ["gunicorn", "api_n8n_with_reciter-4:app", "--bind", "0.0.0.0:8000", "--timeout", "600", "--workers", "2"]
