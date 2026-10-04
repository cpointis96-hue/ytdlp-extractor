# Vérification — 4 octobre 2026

macOS, Python 3.11.16, Tk 8.6 ; trois paquets de `uv.lock` installés avec `uv sync --frozen`. Sources originales, cookies et historique utilisateur non chargés ou modifiés.

## Observé

- `python -m unittest discover -s tests -v` : 6 tests réussis ; sous-cas FFmpeg MP3, M4A, AAC, Opus, WAV et FLAC réellement exécutés.
- Échec simulé avec sortie partielle et succès simulé avec sortie vide : original conservé, temporaire nettoyé.
- Presets : domaines exacts et sous-domaines acceptés ; `notyoutube.com`, `youtube.com.attacker.invalid`, URL vide et locale sans correspondance ni exception.
- Test séparé : clip H.264/AAC synthétique de 2 s servi par HTTP local éphémère ; commande `YtDlpRunner.build`, yt-dlp retour 0, MP3 puis `Pipeline.run` sans transcription. ffprobe : piste audio, durée 2,000 s. Aucun cookie ni média externe.
- `App().mainloop()` lancé avec répertoires isolés, sans erreur immédiate. Computer Use indique un Mac verrouillé : affichage, interactions et captures non confirmés.

## Corrections

Remplacement audio seulement si FFmpeg retourne 0 avec sortie non vide. Codec par format et sortie 48 kHz pour éviter l’erreur FLAC `invalid block size: 96000`. Correspondance sûre des domaines. Répertoires d’isolation. Lanceur sans chemin Python propre à cette machine et arrêt sur échec d’installation.

## Non testé

Sites distants, cookies, comptes, playlists, SponsorBlock, sous-titres réseau, transcription MLX, qualité perceptuelle/LUFS mesurés, température physique, cycle complet UI/worker, annulation réelle et distribution `.app`. Ces résultats ne certifient pas toutes les fonctions de l’ancien README.
