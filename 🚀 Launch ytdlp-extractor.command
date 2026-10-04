#!/bin/bash

# Assure que Homebrew est dans le PATH (absent quand lancé depuis Finder)
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if ! command -v uv &> /dev/null; then
    echo "❌ uv introuvable. Installe-le : brew install uv"
    read -r -p "Appuie sur Entrée pour fermer..."
    exit 1
fi

echo "🔄 Vérification de l'environnement..."
uv sync --frozen --quiet || exit 1

echo "🚀 Démarrage de ytdlp-extractor..."
exec uv run --frozen python ytdlp_extractor.py
