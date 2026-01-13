# 🎬 API Génération Vidéos Coran - Cloud Deployment

API Flask pour générer des vidéos coraniques avec sous-titres synchronisés.

## 🚀 Déploiement sur Railway.app

### Étape 1 : Créer un compte
1. Allez sur https://railway.app
2. Inscrivez-vous avec GitHub
3. Vous obtenez **5$ gratuit/mois**

### Étape 2 : Préparer votre repo GitHub
1. Créez un nouveau repo sur GitHub
2. Uploadez ces fichiers :
   - `api_n8n_with_reciter-4.py`
   - `requirements.txt`
   - `nixpacks.toml`
   - `railway.json`
   - `.gitignore`
   - Dossier `backgrounds/` avec votre `default.mp4`

### Étape 3 : Déployer sur Railway
1. Connectez-vous sur Railway
2. Cliquez sur **"New Project"**
3. Sélectionnez **"Deploy from GitHub repo"**
4. Choisissez votre repo
5. Railway détecte automatiquement Python et FFmpeg
6. Attendez 2-3 minutes ⏱️

### Étape 4 : Obtenir l'URL publique
1. Cliquez sur votre projet
2. Allez dans **"Settings"** > **"Networking"**
3. Cliquez sur **"Generate Domain"**
4. Vous obtenez une URL type : `https://votre-app.up.railway.app`

### Étape 5 : Utiliser dans n8n
Remplacez `http://localhost:8000` par votre URL Railway :

```
POST https://votre-app.up.railway.app/api/generate
```

## 📊 Alternatives Cloud (Budget)

### Option 1 : Railway.app ⭐ **RECOMMANDÉ**
- ✅ **Prix** : 5$/mois gratuit, puis ~5$/mois
- ✅ **Setup** : 5 minutes
- ✅ **FFmpeg** : Supporté nativement
- ✅ **Difficultés** : Aucune

### Option 2 : Render.com
- ✅ **Prix** : Gratuit (avec limitations)
- ⚠️ **Setup** : 10 minutes
- ✅ **FFmpeg** : Supporté
- ⚠️ **Limite** : S'endort après 15min d'inactivité

### Option 3 : Google Cloud Run
- ✅ **Prix** : Gratuit jusqu'à 2M requêtes/mois
- ⚠️ **Setup** : 30 minutes (Docker requis)
- ✅ **FFmpeg** : Supporté
- ⚠️ **Difficultés** : Moyenne

### Option 4 : Heroku
- ⚠️ **Prix** : 5$/mois minimum
- ✅ **Setup** : 5 minutes
- ✅ **FFmpeg** : Buildpack requis
- ✅ **Difficultés** : Facile

## 🎨 Structure des fichiers

```
votre-repo/
├── api_n8n_with_reciter-4.py    # Script principal
├── requirements.txt              # Dépendances Python
├── nixpacks.toml                # Config FFmpeg pour Railway
├── railway.json                 # Config Railway
├── .gitignore                   # Fichiers à ignorer
└── backgrounds/
    ├── default.mp4              # Vidéo par défaut (OBLIGATOIRE)
    └── mosques/                 # Dossier optionnel
        ├── video1.mp4
        └── video2.mp4
```

## 🔧 Configuration

### Variables d'environnement (optionnel)
Dans Railway > Settings > Variables :
```
PORT=8000
FLASK_ENV=production
```

## 📝 Notes importantes

1. **Vidéo default.mp4** : OBLIGATOIRE dans `backgrounds/`
2. **Timeout** : Configuré à 600s pour les longues vidéos
3. **Workers** : 2 workers Gunicorn pour gérer plusieurs requêtes
4. **Stockage** : Les fichiers sont temporaires (supprimés après traitement)

## 🆘 Problèmes courants

### Le déploiement échoue ?
- Vérifiez que `default.mp4` existe dans `backgrounds/`
- Vérifiez les logs Railway

### FFmpeg introuvable ?
- Railway installe FFmpeg via `nixpacks.toml` automatiquement
- Si problème, vérifiez que le fichier existe bien

### Timeout lors de la génération ?
- Augmentez le timeout dans `nixpacks.toml`
- Réduisez la qualité vidéo (quality: "draft")

## 📞 Support

Pour toute question, créez une issue sur GitHub ou contactez-moi.

---
**Made with ❤️ for the Ummah**
