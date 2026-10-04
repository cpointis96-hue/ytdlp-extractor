# Personal OS — Layout & Architecture

> Compagnon de `DESIGN-claude.md` (tokens visuels) et de `claude_extractor_v3.py` (logique extractor à porter).
> Ce document définit la structure de l'app, les panneaux, leurs comportements, et les règles UX.

---

## 1. Identité du projet

**Nom de travail :** Personal OS
**Type :** Application desktop locale (macOS prioritaire, Linux/Windows possibles)
**Stack :** Tauri v2 + React 19 + TypeScript + Tailwind CSS + react-grid-layout
**Backend :** Rust (Tauri commands) + SQLite
**Philosophie :** Cockpit personnel. Tout ce que je consomme et produis dans une même fenêtre. Ergonomie minimaliste façon Apple, presque invisible — l'UI s'efface devant le contenu.

---

## 2. Stack technique — décisions arrêtées

| Couche | Choix | Pourquoi |
|---|---|---|
| Runtime desktop | Tauri v2 (stable 2.10+) | 8MB binaire, démarrage <1s, WebView natif macOS |
| Frontend | React 19 + TypeScript | Stack déjà maîtrisée |
| Styling | Tailwind CSS v4 | Tokens directement mappés depuis DESIGN-claude.md |
| Layout panneaux | react-grid-layout | Activement maintenu, drag/resize/persist natif |
| Persistance app | SQLite via `tauri-plugin-sql` | Cohérent avec Extractor existant |
| Persistance layout | localStorage (JSON) | Simple, suffisant |
| Terminal | xterm.js + `tauri-plugin-shell` | Battle-tested (VS Code) |
| Webviews tierces | `WebviewWindow` natif Tauri | Sessions persistées, contourne X-Frame-Options |
| Scraping X | `gallery-dl` via subprocess Rust | 100% gratuit, pas d'API payante |
| YouTube | `WebviewWindow` natif (pas iframe) | Session persistée, fil personnalisé |
| Fact-check IA | Claude API (clé user) | Configurable dans Settings |

**Règles strictes :**
- Aucune iframe de site tiers (X, YouTube) → uniquement `WebviewWindow` natif Tauri
- Tout I/O réseau passe par le backend Rust (CSP propre côté frontend)
- Aucune dépendance à un VPS, instance publique tierce, ou API payante (sauf clé Claude que l'user fournit)

---

## 3. Structure globale de l'écran

```
┌────┬──────────────────────────────────────────────┐
│ S  │  Grid de panneaux (react-grid-layout)        │
│ I  │  ┌────────────┐  ┌────────────┐              │
│ D  │  │  Panel A   │  │  Panel B   │              │
│ E  │  │            │  │            │              │
│ B  │  └────────────┘  └────────────┘              │
│ A  │  ┌─────────────────────────────┐             │
│ R  │  │  Panel C                    │             │
│    │  └─────────────────────────────┘             │
└────┴──────────────────────────────────────────────┘
```

### Sidebar (gauche)

- **Largeur collapsed :** 48px (icônes seules)
- **Largeur expanded :** 200px (icônes + labels)
- **Toggle :** clic sur le logo en haut OU raccourci `Cmd+B`
- **Background :** `surface-dark` (#181715), border droite `hairline-soft`
- **Items (de haut en bas) :**
  - Logo / toggle (32px)
  - `+` Nouveau panneau (ouvre menu de sélection)
  - Liste des panneaux ouverts (icône + label si expanded)
  - Spacer (flex-grow)
  - Icône rouage Settings (en bas)

### Zone principale

- **Background :** `surface-dark` (#181715)
- **Padding :** 8px tout autour
- **Gap entre panneaux :** 8px
- **Layout :** react-grid-layout en mode `responsive`, breakpoints lg/md/sm
- **Persistance :** layout JSON sauvé dans localStorage à chaque drag/resize

---

## 4. Anatomie d'un panneau

```
┌────────────────────────────────────────┐
│ ⋮⋮  Nom du panneau           ⚙ ✕     │  ← Header 32px
├────────────────────────────────────────┤
│                                        │
│         Contenu du panneau             │  ← Flex 1, scroll si nécessaire
│                                        │
└────────────────────────────────────────┘
```

### Header (32px)

- **Background :** `surface-dark-elevated` (#252320)
- **Border bottom :** 1px `hairline-soft` foncé (rgba(255,255,255,0.05))
- **Padding :** 0 8px
- **Drag handle :** zone gauche `⋮⋮` (6px, cursor: grab)
- **Titre :** typographie `caption` (StyreneB 13px / 500), couleur `on-dark-soft`
- **Boutons droite (16px chacun, gap 8px) :**
  - Icône paramètres panneau (optionnel selon panneau)
  - Icône `✕` fermer
- **Hover panneau :** boutons s'opacifient de 60% → 100% sur hover du header

### Contenu

- **Background :** `surface-dark-soft` (#1f1e1b)
- **Padding :** dépend du panneau (voir section 5)
- **Scroll :** vertical si overflow, scrollbar custom fine 4px (couleur `hairline-soft`)
- **Border radius :** 8px (rounded-md), uniquement sur le panneau global pas sur header/contenu séparément

### États

- **Default :** comme décrit
- **Hover panneau :** légère élévation (shadow `0 0 0 1px rgba(204,120,92,0.15)`)
- **Focus (panneau actif) :** border 1px `primary` (#cc785c) sur le contour
- **Drag en cours :** opacity 0.7, cursor grabbing

---

## 5. Les panneaux — catalogue

### 5.1 Panel `XFeed` — Fil X scrapé

**Source de données :** `gallery-dl` lance via subprocess Rust toutes les 15 min (configurable). Résultats stockés en SQLite.

**Contenu visuel :**
- Liste verticale de tweets, scroll infini
- Chaque tweet :
  - Avatar 32px circle (gauche)
  - Auteur en `caption` strong + handle en `caption` muted-soft
  - Date relative en `caption` muted (à droite)
  - Texte du tweet en `body-sm`
  - Médias (images/vidéos) si présents, max-width 100%, rounded-md
  - Footer : icônes interactions (replies, RT, likes) en `caption` muted, **uniquement affichage**, pas d'interaction
  - Bouton fact-check (icône loupe SVG 14px) à droite, visible au hover du tweet

**Header panneau :**
- Titre : nom du profil sélectionné (ex: "X — elonmusk")
- Bouton paramètres panneau → dropdown : changer profil, refresh maintenant, ouvrir profils

**Settings spécifiques (gérés dans Settings global, voir §7) :**
- Liste des comptes X à scraper (un par ligne)
- Fréquence de refresh (5/15/30/60 min)
- Chemin gallery-dl (auto-détecté via `which gallery-dl`)

**Action fact-check :**
- Clic sur l'icône loupe d'un tweet → ouvre/active le panneau `ChatIA` avec le tweet pré-rempli en input + prompt système de fact-check (configurable dans Settings)

---

### 5.2 Panel `YouTube` — Webview natif

**Implémentation :** `WebviewWindow` Tauri natif chargeant `https://youtube.com`. Session persistée dans son propre profile (cookies, login conservés).

**Contenu visuel :**
- Le webview prend 100% de l'espace contenu
- Overlay top-right : 3 boutons SVG 14px (forward, back, reload) qui apparaissent au hover du panneau (opacity 0 → 0.6)

**Header panneau :**
- Titre : "YouTube"
- Bouton paramètres panneau → "Effacer session", "Ouvrir DevTools"

**Notes techniques :**
- Utiliser le feature flag `unstable` de Tauri v2 pour multi-webview, OU créer un sous-composant qui spawn une WebviewWindow positionnée en absolute par-dessus le panneau React
- À tester : approche `webview` enfant vs window séparée. Préférer enfant si stable.

---

### 5.3 Panel `Terminal` — xterm.js + zsh

**Implémentation :** xterm.js dans un div, `tauri-plugin-shell` lance un process zsh, communication via events Tauri.

**Contenu visuel :**
- Fond `surface-dark-soft`, font `JetBrains Mono` 12px
- Cursor coral (`primary`)
- Selection background `primary` à 25% alpha
- Padding 8px

**Header panneau :**
- Titre : "Terminal — ~/path/courant"
- Bouton paramètres panneau → "Nouvelle session", "Effacer"

**Notes techniques :**
- Utiliser `xterm-addon-fit` pour resize auto au resize du panneau
- Gérer l'environnement complet : charger `~/.zshrc`, hériter du PATH (Homebrew, etc.) via `tauri-plugin-shell` avec spawn `bash -lc 'exec zsh -i'`

---

### 5.4 Panel `Extractor` — port de claude_extractor_v3

**Implémentation :** rewrite React/TypeScript de l'app Python existante. Réutilise SQLite (même schéma : tables `jobs`, `history`, `presets`).

**Contenu visuel — version compacte adaptée panneau :**
- Section haut : input URL + bouton "Ajouter" (height 34px)
- Toggle mode : Audio / Vidéo / Subs (3 boutons segmented control)
- Options dynamiques selon mode (format audio, qualité vidéo, etc.) — collapse/expand
- Section milieu : liste de jobs en cours (chaque ligne : titre, progress bar, %)
- Section bas : log compact (collapsible, hauteur 60px par défaut, drag pour resize)

**Backend :**
- Le backend Rust spawn `yt-dlp` via subprocess, parse stdout/stderr, émet events vers le frontend
- mlx_whisper (transcription) : exécuté en subprocess Python, optionnel
- Toute la logique de governor (limite jobs parallèles selon CPU/RAM) portée en Rust

**Header panneau :**
- Titre : "Extractor"
- Bouton paramètres panneau → "Ouvrir dossier downloads", "Update yt-dlp"

---

### 5.5 Panel `ChatIA` — Fact-check & assistant

**Implémentation :** chat React simple, appel API Claude (clé user dans Settings), streaming des réponses.

**Contenu visuel :**
- Liste messages (user à droite, assistant à gauche, max-width 80%)
- Input bottom : textarea auto-resize (max 200px), bouton envoi (icône SVG 14px) à droite
- Affichage markdown basique pour les réponses (gras, italique, code, listes, liens)

**Comportements :**
- S'ouvre automatiquement quand on clique fact-check sur un tweet → injecte le tweet + prompt système configuré
- Peut aussi être ajouté manuellement comme panneau standalone (chat libre)
- Conversations sauvegardées en SQLite (table `chats`)

**Header panneau :**
- Titre : "Chat IA" ou contexte ("Fact-check: tweet de @user")
- Bouton paramètres panneau → "Nouvelle conversation", "Historique"

---

## 6. Interactions & raccourcis clavier (macOS)

| Raccourci | Action |
|---|---|
| `Cmd+B` | Toggle sidebar |
| `Cmd+,` | Ouvrir Settings |
| `Cmd+N` | Menu nouveau panneau |
| `Cmd+W` | Fermer panneau actif |
| `Cmd+1..9` | Focus panneau N |
| `Cmd+K` | Command palette (futur) |
| `Esc` | Fermer drawer Settings / overlays |

---

## 7. Settings — un seul endroit pour tout

**Accès :** icône rouage 16px en bas de la sidebar, OU `Cmd+,`

**UI :** drawer slide-in depuis la droite, largeur 480px, fond `surface-dark-elevated`, overlay 50% noir derrière

**Structure (sections en accordéon, une seule ouverte à la fois) :**

### Général
- Thème : Auto / Dark / Light (Light en V2)
- Langue interface : FR / EN
- Démarrage : restaurer le layout précédent (toggle)

### Profils & comptes
- Liste des profils X à scraper (textarea, un par ligne)
- Fréquence refresh X (slider 5/15/30/60 min)
- Bouton "Tester gallery-dl" (lance commande, affiche résultat)

### Fact-check & Chat IA
- Clé API Claude (input password)
- Modèle (dropdown : Sonnet 4.6 / Opus 4.7 / Haiku 4.5)
- Prompt système fact-check (textarea large)
- Prompt système chat libre (textarea large)
- Reset prompts par défaut (bouton)

### Extractor
- Dossier de téléchargement (path picker)
- Cookies file (path picker, optionnel)
- Limite jobs parallèles (slider 1-8)
- Auto-update yt-dlp au démarrage (toggle)

### Avancé
- Ouvrir le dossier de config (bouton → reveal in Finder)
- Réinitialiser layout (bouton avec confirm)
- Exporter / Importer settings (boutons)
- Version app + version Tauri (info)

**Règles UI Settings :**
- Aucun bouton "Sauvegarder" — toute modification est appliquée et persistée immédiatement
- Toast en bas-droite si action notable (ex: "yt-dlp à jour" / "Profil X ajouté")
- Confirmation modale uniquement pour actions destructrices (reset)

---

## 8. Tokens visuels — mapping vers DESIGN-claude.md

L'app fonctionne **exclusivement en mode dark** (V1). Tous les tokens utilisés viennent du DESIGN-claude.md, surfaces dark uniquement :

| Usage app | Token DESIGN-claude.md |
|---|---|
| Background main | `surface-dark` (#181715) |
| Background panneau header | `surface-dark-elevated` (#252320) |
| Background panneau contenu | `surface-dark-soft` (#1f1e1b) |
| Background sidebar | `surface-dark` (#181715) |
| Texte principal | `on-dark` (#faf9f5) |
| Texte secondaire | `on-dark-soft` (#a09d96) |
| Accent / focus / cursor | `primary` (#cc785c) |
| Accent hover | `primary-active` darken (#a9583e) |
| Borders subtils | rgba(255,255,255,0.06) |
| Success | `success` (#5db872) |
| Warning | `warning` (#d4a017) |
| Error | `error` (#c64545) |
| Info | `accent-teal` (#5db8a6) |

**Typo :**
- UI : `StyreneB, Inter, sans-serif` (`title-sm`, `body-sm`, `caption` selon contexte)
- Display occasionnel (titres section Settings) : `Copernicus, serif` taille `title-lg`
- Mono (terminal, code, logs) : `JetBrains Mono`

**Spacing :** strict `xxs` 4 / `xs` 8 / `sm` 12 / `md` 16 / `lg` 24

**Rounded :** quasi-exclusif `rounded-md` (8px) pour panneaux, boutons, inputs. `rounded-sm` (6px) pour petits badges.

---

## 9. Icônes — règles

- **Source unique :** `lucide-react` (cohérence parfaite, 1500+ icônes, design line par défaut)
- **Tailles standard :** 14px (boutons header panneau), 16px (sidebar, settings), 20px (jamais sauf logo)
- **Stroke width :** 1.5 (par défaut Lucide), jamais 2 ou plus (trop épais pour le minimalisme visé)
- **Couleur :** `on-dark-soft` au repos, `on-dark` au hover, `primary` si état actif
- **Aucune icône colorée** sauf indicateurs de statut (success/error/warn) où la couleur EST l'info

---

## 10. Animations — règles strictes

- **Durée standard :** 150ms ease-out
- **Durée pour drawers/sidebars :** 200ms cubic-bezier(0.16, 1, 0.3, 1) (ease-out smooth)
- **Hover transitions :** opacity et background uniquement, jamais de transform sauf scale 0.98 sur active button
- **Pas d'animation sur :** ouverture panneau, drag, resize (instant pour la perf et la précision)
- **Loading states :** skeleton subtil ou spinner Lucide `Loader2` qui spin 1s linear infinite

---

## 11. Persistance & données

**SQLite (via `tauri-plugin-sql`) :**
```sql
-- Réutilise les tables d'Extractor :
jobs, history, presets

-- Nouvelles tables Personal OS :
CREATE TABLE x_profiles (
  id INTEGER PRIMARY KEY,
  handle TEXT UNIQUE NOT NULL,
  display_name TEXT,
  added_at REAL
);

CREATE TABLE x_tweets (
  id INTEGER PRIMARY KEY,
  tweet_id TEXT UNIQUE NOT NULL,
  profile_id INTEGER REFERENCES x_profiles(id),
  text TEXT,
  author_handle TEXT,
  created_at REAL,
  scraped_at REAL,
  media_json TEXT,
  raw_json TEXT
);

CREATE TABLE chats (
  id INTEGER PRIMARY KEY,
  title TEXT,
  context_type TEXT, -- 'free' | 'fact_check'
  created_at REAL,
  updated_at REAL
);

CREATE TABLE chat_messages (
  id INTEGER PRIMARY KEY,
  chat_id INTEGER REFERENCES chats(id),
  role TEXT, -- 'user' | 'assistant' | 'system'
  content TEXT,
  created_at REAL
);

CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value TEXT -- JSON
);
```

**localStorage :**
- `layout` : config react-grid-layout actuelle
- `sidebar_collapsed` : boolean
- `last_active_panel` : panel id

**Fichiers :**
- `~/Library/Application Support/PersonalOS/personal-os.db` (SQLite)
- `~/Library/Application Support/PersonalOS/logs/` (logs de subprocess)

---

## 12. Sécurité Tauri v2

**capabilities (`src-tauri/capabilities/main.json`) :**
- `core:default`
- `shell:allow-execute` scoped à : `gallery-dl`, `yt-dlp`, `zsh`, `bash`, `which`, `brew`
- `sql:default`
- `fs:allow-read-dir` scoped à `$DOWNLOAD/personal-os/**` et `$APPDATA/**`
- `fs:allow-write-file` scoped à `$DOWNLOAD/personal-os/**` et `$APPDATA/**`
- `http:default` scoped à `https://api.anthropic.com/**`
- `webview:allow-create-webview-window` (pour panel YouTube)

**CSP (`tauri.conf.json`) :**
```
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline';
img-src 'self' data: asset: https://asset.localhost;
connect-src 'self' ipc: https://ipc.localhost https://api.anthropic.com;
```

Pas de `frame-src` — les sites tiers passent par WebviewWindow natif, pas par iframe.

---

## 13. Plan de découpage projet (pour Claude Code `/plan`)

**Phase 1 — Fondations** (≈ 1-2j)
1. Scaffold Tauri v2 + React 19 + TypeScript + Tailwind v4
2. Tokens design dans `tailwind.config.ts` (depuis DESIGN-claude.md)
3. Layout global : Sidebar + zone grid vide
4. Intégration react-grid-layout, panneau "Hello World" drag/resize/close
5. Persistance layout localStorage
6. Settings drawer (squelette, sections vides)
7. SQLite plugin + migrations initiales

**Phase 2 — Premiers panneaux** (≈ 2-3j)
8. Panel Terminal (xterm.js + plugin-shell)
9. Panel ChatIA (input + appel API Claude streaming)
10. Section Settings → Fact-check (clé API, prompts)

**Phase 3 — X & YouTube** (≈ 3-4j)
11. Subprocess Rust pour gallery-dl, parsing JSON
12. Section Settings → Profils X
13. Panel XFeed (UI + scroll infini + fact-check trigger)
14. Panel YouTube (WebviewWindow natif intégré)

**Phase 4 — Extractor port** (≈ 3-5j)
15. Port logique yt-dlp + governor en Rust (depuis claude_extractor_v3.py)
16. Panel Extractor (UI compacte React)
17. Section Settings → Extractor

**Phase 5 — Polish** (≈ 2-3j)
18. Raccourcis clavier globaux
19. Animations/transitions finales
20. Icônes Lucide partout, audit visuel
21. Tests sur macOS M5 (perf, mémoire)
22. Build & DMG

**Total estimé :** 11-17 jours de dev solo accompagné Claude Code.

---

## 14. Hors scope V1 (à noter pour V2)

- Mode Light (uniquement Dark en V1)
- Multi-fenêtres (une seule fenêtre principale en V1)
- Command palette `Cmd+K`
- Synchronisation cloud des settings
- Plugin system (panneaux tiers)
- Linux/Windows builds (focus macOS pur en V1)
- Notifications natives macOS

---

## 15. Risques connus & mitigations

| Risque | Mitigation |
|---|---|
| `gallery-dl` casse quand X change son HTML | Fallback : lancer commande de mise à jour `gallery-dl` automatique au démarrage si erreur de scraping détectée |
| Tauri multi-webview en feature flag `unstable` | Tester en début de Phase 3. Plan B : iframe avec proxy Rust qui réécrit headers (plus complexe mais stable) |
| Performance react-grid-layout avec 5+ panneaux lourds | Lazy-render contenu hors viewport, mémoïzation aggressive |
| API Claude rate limits | Afficher quota usage dans Settings, gestion d'erreur propre avec backoff |
| WebView macOS partage cookies entre instances | Utiliser un profile name unique par WebviewWindow YouTube |

---

## 16. Notes pour Claude Code

- **Prioritise la lisibilité** : composants courts (max 150 lignes), un fichier par panneau, hooks custom pour la logique
- **Type-safety stricte** : `strict: true` dans tsconfig, jamais de `any`
- **Commands Rust** : un fichier par domaine (`x.rs`, `youtube.rs`, `extractor.rs`, `chat.rs`)
- **Style** : Prettier + ESLint config standard, Tailwind class-sorting
- **Tests** : pas obligatoire en V1 mais bienvenu sur la logique Rust critique (governor, parsing)
- **Commits** : conventional commits (`feat:`, `fix:`, `chore:`)
- **Pas de surfaces hors design system** : si tu hésites, prends le token le plus proche dans DESIGN-claude.md plutôt qu'inventer

---

## Annexe — checklist avant `/plan` Claude Code

- [ ] Ce fichier `APP-LAYOUT.md` lu
- [ ] `DESIGN-claude.md` lu (tokens visuels)
- [ ] `claude_extractor_v3.py` parcouru (logique à porter)
- [ ] Node 22+ installé (`brew install node`)
- [ ] Rust toolchain installé (`brew install rustup-init && rustup-init`)
- [ ] OrbStack tourne (pour tests éventuels conteneurs)
- [ ] Clé API Claude prête (à mettre dans Settings après scaffold)
- [ ] Compte X connecté dans Safari/Firefox (gallery-dl utilisera les cookies)
