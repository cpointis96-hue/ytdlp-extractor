# ytdlp-extractor

Prototype desktop Python pour piloter yt-dlp : audio/vidéo, sous-titres, file d’attente et historique SQLite. L’interface CustomTkinter est en français. Les onze langues proposées concernent les sous-titres et la transcription, pas la traduction de l’interface.

## État réel

Le stockage, les presets et la normalisation audio sont testés. Une commande construite par l’application a téléchargé un clip synthétique servi localement, l’a converti en MP3 puis normalisé. Cela ne valide pas l’accès actuel à YouTube, les sessions authentifiées ou le cycle complet de la file graphique.

Le processus graphique a été lancé sans erreur immédiate sur macOS avec des dossiers isolés. Après déverrouillage, Computer Use montre bien l'interface originale CustomTkinter, sans historique ni URL personnelle. Les essais de clic n'ont pas établi un changement d'onglet : le cycle graphique complet reste non validé. La capture native a été affichée dans la conversation, mais n'est pas encore incluse dans cette archive.

## Installation et lancement

Prévoir Python 3.11 avec Tk, uv, yt-dlp et FFmpeg/ffprobe dans le PATH. Exemple macOS/Homebrew :

```sh
brew install python@3.11 python-tk@3.11 uv yt-dlp ffmpeg
python3.11 -c 'import tkinter; print(tkinter.TkVersion)'
uv sync --frozen --python python3.11
uv run --frozen python ytdlp_extractor.py
```

`🚀 Launch ytdlp-extractor.command` est un lanceur macOS qui suppose ces prérequis installés. Pas de bundle `.app` autonome. `main.py` n’est pas le point d’entrée graphique. Les paquets verrouillés sont CustomTkinter, darkdetect et packaging ; uv n’installe pas les exécutables externes yt-dlp et FFmpeg.

### Session isolée

Par défaut : `~/Library/Application Support/ytdlp-extractor/extractor.db` et `~/Downloads/ytdlp-extractor`. La file peut reprendre les jobs existants au lancement. Pour tester sans charger son historique :

```sh
YTDLP_EXTRACTOR_DATA_DIR="$PWD/.local-test/data" \
YTDLP_EXTRACTOR_DOWNLOAD_DIR="$PWD/.local-test/downloads" \
uv run --frozen python ytdlp_extractor.py
```

Aucun cookie, historique personnel ou téléchargement n’est inclus. Ne sélectionner des cookies que pour un contenu auquel on est autorisé à accéder.

## Techniques et structure

- `ytdlp_extractor.py` : UI, Store SQLite/WAL, Governor, commandes yt-dlp, worker et pipeline FFmpeg.
- Threads, queue d’événements UI, progression lue depuis la sortie du sous-processus.
- Presets par domaine, formats, qualité, découpage, playlists et sous-titres.
- Normalisation à −14 LUFS ; codecs adaptés aux sorties MP3/M4A/AAC/Opus/WAV/FLAC, sortie à 48 kHz.
- MLX Whisper et psutil : optionnels, absents de l’installation minimale et non validés ici.

## Tests

```sh
uv run --frozen python -m unittest discover -s tests -v
```

Six tests couvrent l’isolation, les domaines, la file SQLite, la conservation de l’original sur échec, le remplacement après succès et les six formats audio réels. Le dernier exige FFmpeg/ffprobe ; sinon il est ignoré explicitement. [Résultats et limites](VERIFICATION.md).

## Limites et reprise

Le worker exécute un job à la fois : la politique `concurrent` n’implémente pas deux téléchargements parallèles. Le Governor utilise éventuellement la charge CPU comme approximation et les capteurs exposés par psutil ; ce n’est pas un accès vérifié à la température Apple M5. Les replis H.264/AV1 peuvent contourner le plafond de résolution : à durcir avant d’en faire une garantie.

La découverte du fichier à post-traiter repose sur les fichiers récents. Certains échecs de post-traitement sont silencieux. MLX Whisper peut télécharger un modèle si activé ; aucun benchmark de vitesse n’est validé. Le bouton de mise à jour lance `brew upgrade yt-dlp`, non utilisé pendant les tests.

Priorités : vérifier les onglets et le cycle ajouter/annuler/reprendre ; gérer les exécutables manquants ; associer le job à sa sortie exacte ; rendre les échecs visibles ; tester les sous-titres sur une source autorisée. `APP-LAYOUT.md` est un plan Tauri envisagé, pas l’application livrée.

Cette copie corrige les domaines de presets, la sécurité du remplacement audio et le lanceur, sans redessiner l’interface. Les sources originales restent intactes. Aucun binaire hébergé n’est annoncé ici.

## Dépôt et téléchargement

[Voir le dépôt](https://github.com/cpointis96-hue/ytdlp-extractor) · [Télécharger les sources ZIP](https://github.com/cpointis96-hue/ytdlp-extractor/archive/HEAD.zip). Le ZIP contient les sources ; suivre l’installation ci-dessus.
