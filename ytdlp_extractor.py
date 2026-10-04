#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extractor System v3 — Fichier unique
SQLite · Governor M5 · Event-driven UI · Pipeline local
"""
from __future__ import annotations

import customtkinter as ctk
import tkinter as tk
import tkinter.filedialog as filedialog

import subprocess
import threading
import queue
import re
import os
import json
import time
import random
import signal
import sqlite3
import platform
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Callable, List, Dict, Any

SUBTITLE_DELAY_MIN = 8.0
SUBTITLE_DELAY_MAX = 15.0
SUBTITLE_HTTP_RETRY_SLEEP = "http:exp=5:120"

# ── Optionnels ───────────────────────────────────────────────────────────────
try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

try:
    import mlx_whisper
    HAS_WHISPER = True
except Exception:
    HAS_WHISPER = False

# ── CONFIG ───────────────────────────────────────────────────────────────────
APP_NAME = "ytdlp-extractor"
BG = "#181715"
BG_ELEVATED = "#252320"
BG_INPUT = "#1f1e1b"
BORDER = "#2d2925"
TEXT = "#faf9f5"
TEXT_DIM = "#a09d96"
ACCENT = "#cc785c"
ACCENT_HOV = "#d98b6e"
ACCENT_DIM = "#7a4535"
SUCCESS = "#5db872"
ERROR = "#c64545"
WARN = "#d4a017"
INFO = "#5db8a6"

FONT_MONO = ("JetBrains Mono", 12)
FONT_MONO_S = ("JetBrains Mono", 11)
FONT_MONO_B = ("JetBrains Mono", 12, "bold")
FONT_MONO_XS = ("JetBrains Mono", 10)
FONT_TITLE = ("SF Pro Display", 14, "bold")
FONT_SMALL = ("SF Pro Text", 11)
FONT_UI = ("SF Pro Text", 13)
FONT_UI_S = ("SF Pro Text", 12)

SUPPORT_DIR = Path(os.environ.get("YTDLP_EXTRACTOR_DATA_DIR", str(Path.home() / "Library/Application Support/ytdlp-extractor"))).expanduser()
SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = SUPPORT_DIR / "extractor.db"
DOWNLOAD_DIR = Path(os.environ.get("YTDLP_EXTRACTOR_DOWNLOAD_DIR", str(Path.home() / "Downloads" / "ytdlp-extractor"))).expanduser()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

LANG_OPTIONS = {
    "Français": "fr", "English": "en", "Español": "es",
    "Deutsch": "de", "Italiano": "it", "Português": "pt",
    "日本語": "ja", "한국어": "ko", "中文": "zh",
    "العربية": "ar", "Русский": "ru",
}

PRESETS: List[Dict[str, Any]] = [
    {"domain": "music.youtube.com", "mode": "Audio", "audio_fmt": "OPUS", "post": ["loudnorm"]},
    {"domain": "youtube.com", "mode": "Vidéo", "video_quality": "1080p", "video_codec": "h264", "post": ["transcribe", "scene"]},
    {"domain": "youtu.be", "mode": "Vidéo", "video_quality": "1080p", "video_codec": "h264", "post": ["transcribe"]},
    {"domain": "instagram.com", "mode": "Vidéo", "video_quality": "720p", "video_codec": "h264", "post": []},
    {"domain": "twitter.com", "mode": "Vidéo", "video_quality": "720p", "video_codec": "h264", "post": []},
    {"domain": "x.com", "mode": "Vidéo", "video_quality": "720p", "video_codec": "h264", "post": []},
    {"domain": "soundcloud.com", "mode": "Audio", "audio_fmt": "MP3", "post": ["loudnorm"]},
    {"domain": "bandcamp.com", "mode": "Audio", "audio_fmt": "FLAC", "post": []},
]

# ── CORE SQLITE ──────────────────────────────────────────────────────────────
@dataclass(slots=True)
class JobRow:
    id: int
    url: str
    mode: str
    preset_json: str
    status: str
    progress: float
    meta_json: str
    created_at: float
    updated_at: float

    @property
    def preset(self) -> dict:
        return json.loads(self.preset_json) if self.preset_json else {}

    @property
    def meta(self) -> dict:
        return json.loads(self.meta_json) if self.meta_json else {}


class Store:
    """Singleton SQLite thread-safe. Zéro JSON externe."""
    _inst = None
    _lock = threading.RLock()

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
            cls._inst._init_db()
        return cls._inst

    def _init_db(self):
        self._db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS jobs(
                id INTEGER PRIMARY KEY,
                url TEXT NOT NULL,
                mode TEXT,
                preset TEXT DEFAULT '{}',
                status TEXT DEFAULT 'queued',
                progress REAL DEFAULT 0,
                meta TEXT DEFAULT '{}',
                created_at REAL,
                updated_at REAL
            )
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS history(
                id INTEGER PRIMARY KEY,
                url TEXT UNIQUE,
                title TEXT,
                channel TEXT,
                mode TEXT,
                file_path TEXT,
                phash TEXT,
                downloaded_at REAL
            )
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS presets(
                id INTEGER PRIMARY KEY,
                domain TEXT UNIQUE,
                config TEXT
            )
        """)
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_hist_date ON history(downloaded_at)")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_hist_url ON history(url)")
        self._db.commit()
        self._ui_queue: Optional[queue.Queue] = None
        self._load_default_presets()

    def set_ui_queue(self, q: queue.Queue):
        self._ui_queue = q

    def _emit(self, event: str, data: dict):
        if self._ui_queue:
            try:
                self._ui_queue.put_nowait((event, data))
            except queue.Full:
                pass

    def _load_default_presets(self):
        for p in PRESETS:
            self._db.execute(
                "INSERT OR IGNORE INTO presets(domain,config) VALUES (?,?)",
                (p["domain"], json.dumps(p))
            )
        self._db.commit()

    def preset_for_url(self, url: str) -> Optional[dict]:
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        cur = self._db.execute("SELECT config FROM presets WHERE domain=?", (host,))
        row = cur.fetchone()
        if row:
            return json.loads(row[0])
        for domain, config in self._db.execute("SELECT domain, config FROM presets ORDER BY length(domain) DESC"):
            if host.endswith("." + domain):
                return json.loads(config)
        return None

    def job_add(self, url: str, mode: str, preset: dict = None, meta: dict = None) -> int:
        with self._lock:
            now = time.time()
            cur = self._db.execute(
                "INSERT INTO jobs(url,mode,preset,status,progress,meta,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (url, mode, json.dumps(preset or {}), "queued", 0.0, json.dumps(meta or {}), now, now)
            )
            self._db.commit()
            self._emit("job_added", {"id": cur.lastrowid, "url": url, "mode": mode})
            return cur.lastrowid

    def job_claim_next(self) -> Optional[JobRow]:
        with self._lock:
            cur = self._db.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                return None
            job = JobRow(*row)
            now = time.time()
            self._db.execute("UPDATE jobs SET status='running', updated_at=? WHERE id=?", (now, job.id))
            self._db.commit()
            self._emit("job_started", {"id": job.id, "url": job.url})
            return job

    def job_update(self, job_id: int, progress: float = None, status: str = None, meta: dict = None):
        with self._lock:
            sets, vals = [], []
            if progress is not None:
                sets.append("progress=?")
                vals.append(progress)
            if status:
                sets.append("status=?")
                vals.append(status)
            if meta is not None:
                sets.append("meta=?")
                vals.append(json.dumps(meta))
            sets.append("updated_at=?")
            vals.append(time.time())
            vals.append(job_id)
            self._db.execute(f"UPDATE jobs SET {','.join(sets)} WHERE id=?", vals)
            self._db.commit()
            self._emit("job_updated", {"id": job_id, "progress": progress, "status": status})

    def job_meta_update(self, job_id: int, patch: dict):
        """Merge un résultat de job sans écraser les options persistées."""
        with self._lock:
            row = self._db.execute("SELECT meta FROM jobs WHERE id=?", (job_id,)).fetchone()
            current = json.loads(row[0] or "{}") if row else {}
            current.update(patch)
            self._db.execute(
                "UPDATE jobs SET meta=?, updated_at=? WHERE id=?",
                (json.dumps(current), time.time(), job_id),
            )
            self._db.commit()

    def cancel_queued(self):
        with self._lock:
            now = time.time()
            self._db.execute(
                "UPDATE jobs SET status='cancelled', updated_at=? WHERE status IN ('queued','waiting','retrying')",
                (now,),
            )
            self._db.commit()

    def job_delete(self, job_id: int):
        with self._lock:
            self._db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            self._db.commit()

    def recover_jobs(self):
        """Reset les jobs bloqués depuis >10 min (crash précédent)."""
        with self._lock:
            cutoff = time.time() - 600
            self._db.execute("UPDATE jobs SET status='queued' WHERE status='running' AND updated_at < ?", (cutoff,))
            self._db.commit()

    def history_add(self, url: str, title: str, channel: str, mode: str, path: str):
        with self._lock:
            self._db.execute(
                """INSERT INTO history(url,title,channel,mode,file_path,downloaded_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(url) DO UPDATE SET
                   title=excluded.title, channel=excluded.channel, mode=excluded.mode,
                   file_path=excluded.file_path, downloaded_at=excluded.downloaded_at""",
                (url, title or "", channel or "", mode, path, time.time())
            )
            self._db.commit()
            self._emit("history_changed", {})

    def history_fetch(self, limit: int = 50, offset: int = 0):
        with self._lock:
            cur = self._db.execute(
                "SELECT * FROM history ORDER BY downloaded_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            )
            return cur.fetchall()

    def history_search(self, query: str, limit: int = 50):
        with self._lock:
            q = f"%{query}%"
            cur = self._db.execute(
                "SELECT * FROM history WHERE title LIKE ? OR url LIKE ? OR channel LIKE ? ORDER BY downloaded_at DESC LIMIT ?",
                (q, q, q, limit)
            )
            return cur.fetchall()

    def stats(self) -> dict:
        with self._lock:
            total = self._db.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            queued = self._db.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
            running = self._db.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0]
            return {"total": total, "queued": queued, "running": running}

    def queue_list(self, limit: int = 100) -> List[JobRow]:
        with self._lock:
            cur = self._db.execute(
                "SELECT * FROM jobs WHERE status IN ('queued','running','waiting','retrying','done','error','cancelled') ORDER BY created_at LIMIT ?",
                (limit,)
            )
            return [JobRow(*r) for r in cur.fetchall()]


# ── GOVERNOR ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Policy:
    rate_limit: str   # "0" = illimité
    max_height: int   # 0 = pause
    concurrent: int


class Governor:
    """Adapte qualité et débit selon thermique / batterie du Air M5."""
    def __init__(self):
        self._last_thermal = 0.0

    def _thermal(self) -> str:
        if not HAS_PSUTIL:
            return "nominal"
        try:
            # Fallback simple : si CPU > 70% on considère que ça chauffe
            if psutil.cpu_percent(interval=0.2) > 70:
                return "moderate"
            # Température si dispo
            temps = psutil.sensors_temperatures()
            if temps:
                for k, v in temps.items():
                    if v:
                        t = v[0].current
                        self._last_thermal = t
                        if t > 85:
                            return "critical"
                        if t > 75:
                            return "heavy"
                        if t > 65:
                            return "moderate"
        except Exception:
            pass
        return "nominal"

    def _on_battery(self) -> bool:
        if not HAS_PSUTIL:
            return False
        try:
            bat = psutil.sensors_battery()
            return bat is not None and not bat.power_plugged
        except Exception:
            return False

    def get_policy(self) -> Policy:
        th = self._thermal()
        bat = self._on_battery()
        if th == "critical":
            return Policy("0", 0, 0)
        if th == "heavy":
            return Policy("500K", 480, 1)
        if bat:
            return Policy("2M", 720, 1)
        if th == "moderate":
            return Policy("5M", 1080, 1)
        return Policy("0", 2160, 2)

    def apply(self, cmd: List[str], policy: Policy, requested_height: int = 2160) -> List[str]:
        out = [c for c in cmd]
        # Rate limit
        has_rate = False
        for i, c in enumerate(out):
            if c == "--limit-rate":
                has_rate = True
                if policy.rate_limit != "0":
                    out[i + 1] = policy.rate_limit
                else:
                    # remove rate limit
                    out = out[:i] + out[i + 2:]
                break
        if not has_rate and policy.rate_limit != "0":
            out += ["--limit-rate", policy.rate_limit]

        # Height cap
        h = min(requested_height, policy.max_height) if policy.max_height else requested_height
        return out, h


# ── PIPELINE ─────────────────────────────────────────────────────────────────
class Pipeline:
    """Post-traitement local : transcription MLX, loudnorm, scenes."""
    def __init__(self):
        self.model = "mlx-community/whisper-large-v3-turbo"

    def run(self, path: Path, mode: str, meta: dict):
        if not path.exists():
            return
        if mode == "Audio" or path.suffix in (".mp3", ".m4a", ".wav", ".opus", ".flac"):
            self._loudnorm(path)
            if HAS_WHISPER and meta.get("transcribe", True):
                self._transcribe(path, meta)
        elif mode == "Vidéo":
            if HAS_WHISPER and meta.get("transcribe", True):
                self._transcribe(path, meta)
            self._scene_extract(path)

    def _transcribe(self, path: Path, meta: dict):
        try:
            result = mlx_whisper.transcribe(
                str(path), path_or_hf_repo=self.model,
                language=meta.get("lang", "fr"), word_timestamps=True,
            )
            srt = path.with_suffix(".srt")
            self._write_srt(result.get("segments", []), srt)
            # chapitres auto
            chaps = self._chapters(result.get("segments", []))
            if chaps:
                path.with_suffix(".chapters.json").write_text(
                    json.dumps(chaps, ensure_ascii=False), encoding="utf-8"
                )
        except Exception:
            pass

    def _write_srt(self, segs: list, path: Path):
        def fmt(t: float) -> str:
            h, r = divmod(t, 3600)
            m, s = divmod(r, 60)
            return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")
        lines = []
        for i, seg in enumerate(segs, 1):
            txt = seg.get("text", "").strip()
            if txt:
                lines.append(f"{i}\n{fmt(seg['start'])} --> {fmt(seg['end'])}\n{txt}\n")
        path.write_text("\n".join(lines), encoding="utf-8")

    def _chapters(self, segs: list, gap: float = 3.0) -> list:
        chaps, last = [], 0.0
        for seg in segs:
            if seg["start"] - last > gap:
                chaps.append({"start": seg["start"], "title": seg["text"][:50]})
            last = seg["end"]
        return chaps

    def _loudnorm(self, path: Path):
        tmp = path.with_suffix(".norm" + path.suffix)
        codec = {".mp3": "libmp3lame", ".m4a": "aac", ".aac": "aac",
                 ".opus": "libopus", ".wav": "pcm_s16le", ".flac": "flac"}.get(path.suffix.lower())
        if codec is None:
            return
        cmd = ["ffmpeg", "-y", "-i", str(path), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
               "-ar", "48000", "-c:a", codec, "-b:a", "192k", str(tmp)]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(path)
        except Exception:
            pass
        finally:
            if tmp.exists():
                tmp.unlink()

    def _scene_extract(self, path: Path, thr: float = 0.3):
        out = path.parent / f"{path.stem}.scenes"
        out.mkdir(exist_ok=True)
        cmd = ["ffmpeg", "-i", str(path), "-vf", f"select=gt(scene\\,{thr}),scale=320:-1",
               "-vsync", "vfr", str(out / "%03d.jpg")]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120)
        except Exception:
            pass


# ── RUNNER ───────────────────────────────────────────────────────────────────
class YtDlpRunner:
    def __init__(self, store: Store, governor: Governor, pipeline: Pipeline):
        self.store = store
        self.gov = governor
        self.pipe = pipeline
        self._proc = None
        self._cancelled = False

    def build(self, job: JobRow, opts: dict) -> List[str]:
        url = job.url
        mode = opts.get("mode", "Audio")
        channel_folder = opts.get("channel_folder", "").strip()

        if channel_folder:
            out_tpl = str(DOWNLOAD_DIR / channel_folder / "%(upload_date>%d.%m.%Y)s - %(title).180B.%(ext)s")
        elif opts.get("playlist"):
            out_tpl = str(DOWNLOAD_DIR / "%(playlist_title|%(uploader)s)s" /
                          "%(playlist_index|0)03d - %(upload_date>%d.%m.%Y)s - %(title).160B.%(ext)s")
        else:
            out_tpl = str(DOWNLOAD_DIR / "%(upload_date>%d.%m.%Y)s - %(title).180B.%(ext)s")

        cmd = ["yt-dlp", "--newline", "--progress", "--no-warnings",
               "--retries", "5", "--fragment-retries", "5", "--retry-sleep", "3",
               "--no-overwrites", "-o", out_tpl]

        cmd += ["--yes-playlist"] if opts.get("playlist") else ["--no-playlist"]

        if opts.get("start") or opts.get("end"):
            s = opts.get("start") or "0"
            e = opts.get("end") or "inf"
            cmd += ["--download-sections", f"*{s}-{e}", "--force-keyframes-at-cuts"]

        cf = opts.get("cookies_file", "")
        br = opts.get("cookies_browser", "Aucun")
        if cf and Path(cf).exists():
            cmd += ["--cookies", cf]
        elif br and br != "Aucun":
            cmd += ["--cookies-from-browser", br.lower()]

        if opts.get("sponsorblock"):
            cmd += ["--sponsorblock-remove", "sponsor,intro,outro,selfpromo,interaction"]

        req_height = 2160
        if mode == "Audio":
            cmd += ["-x", "--audio-format", opts.get("audio_format", "mp3").lower(),
                    "--audio-quality", "0", "--embed-metadata"]
            if opts.get("embed_thumb"):
                cmd += ["--embed-thumbnail"]
            if opts.get("split_chapters"):
                cmd += ["--split-chapters", "-o", f"chapter:%(title)s - %(section_title)s.%(ext)s"]

        elif mode == "Vidéo":
            q = opts.get("video_quality", "Best")
            c = opts.get("video_format", "mp4").lower()
            codec = opts.get("video_codec", "any")
            if q == "Best":
                fmt = "bv*+ba/b"
                req_height = 2160
            else:
                h = q.replace("p", "")
                fmt = f"bv*[height<={h}]+ba/b[height<={h}]"
                req_height = int(h)
            if codec == "h264":
                fmt = f"bv*[vcodec^=avc][height<={req_height}]+ba/b"
            elif codec == "av1":
                fmt = f"bv*[vcodec^=av01]+ba/b"
            cmd += ["-f", fmt, "--merge-output-format", c, "--embed-metadata", "--embed-chapters"]
            if opts.get("embed_thumb"):
                cmd += ["--embed-thumbnail"]
            if opts.get("embed_subs"):
                lc = LANG_OPTIONS.get(opts.get("sub_lang1", "Français"), "fr")
                cmd += ["--embed-subs", "--sub-langs", lc, "--write-auto-subs"]
            if opts.get("split_chapters"):
                cmd += ["--split-chapters"]

        elif mode == "Sous-titres":
            l1 = LANG_OPTIONS.get(opts.get("sub_lang1", "Français"), "fr")
            sf = "srt" if opts.get("sub_format") == "TXT" else opts.get("sub_format", "srt").lower()
            cmd += ["--skip-download", "--write-subs", "--write-auto-subs",
                    "--sub-langs", l1, "--convert-subs", sf,
                    "--sleep-subtitles", "2", "--retry-sleep", SUBTITLE_HTTP_RETRY_SLEEP]

        # Governor
        policy = self.gov.get_policy()
        if policy.concurrent == 0:
            raise RuntimeError("thermal_pause")
        cmd, capped_h = self.gov.apply(cmd, policy, req_height)
        if capped_h != req_height and mode == "Vidéo":
            # Rebuild fmt with capped height
            h = capped_h
            fmt = f"bv*[height<={h}]+ba/b[height<={h}]"
            if codec == "h264":
                fmt = f"bv*[vcodec^=avc][height<={h}]+ba/b"
            elif codec == "av1":
                fmt = f"bv*[vcodec^=av01]+ba/b"
            # Replace -f argument
            try:
                idx = cmd.index("-f")
                cmd[idx + 1] = fmt
            except ValueError:
                cmd += ["-f", fmt]

        cmd.append(url)
        return cmd

    def run(self, job: JobRow, opts: dict):
        self._cancel_event = threading.Event()
        threading.Thread(target=self._thread, args=(job, opts), daemon=True).start()

    def _thread(self, job: JobRow, opts: dict):
        try:
            cmd = self.build(job, opts)
        except RuntimeError as e:
            if "thermal_pause" in str(e):
                self.store.job_update(job.id, status="queued")
                self.store._emit("log", {"text": "⏸ Pause thermique — retry dans 30s\n", "color": WARN})
            return

        self.store._emit("log", {"text": f"$ {' '.join(cmd)}\n", "color": TEXT_DIM})
        start_t = time.time()

        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
            start_new_session=True,
        )

        prog_re = re.compile(r"\[download\]\s+(\d+\.?\d*)%")
        err_re = re.compile(r"ERROR", re.I)
        warn_re = re.compile(r"WARNING", re.I)
        title_re = re.compile(r"\[info\]\s+\S+:\s+(.+)")
        detected_title = ""
        had_error = False
        had_429 = False
        no_subtitles = False

        for line in self._proc.stdout:
            if self._cancel_event.is_set():
                break
            line = line.rstrip()
            if not line:
                continue

            color = TEXT_DIM
            if err_re.search(line):
                color = ERROR
                had_error = True
            if "429" in line or "Too Many Requests" in line:
                had_429 = True
                self.store.job_update(job.id, status="retrying")
                self.store._emit("log", {"text": "Rate limit YouTube détecté, yt-dlp applique son backoff HTTP.\n", "color": WARN})
            if "no subtitles" in line.lower() or "there are no subtitles" in line.lower():
                no_subtitles = True
            elif warn_re.search(line):
                color = WARN
            elif "[download] 100%" in line:
                color = SUCCESS
            elif line.startswith(("[ExtractAudio]", "[Metadata]", "[EmbedThumbnail]")):
                color = INFO

            m = prog_re.search(line)
            if m:
                self.store.job_update(job.id, progress=float(m.group(1)) / 100.0)

            t = title_re.search(line)
            if t and not detected_title:
                detected_title = t.group(1).strip()

            self.store._emit("log", {"text": line + "\n", "color": color})

        code = self._proc.wait()
        if self._cancel_event.is_set():
            self.store.job_update(job.id, status="cancelled")
            self.store.job_meta_update(job.id, {"outcome": "cancelled"})
            self.store._emit("done", {"id": job.id, "result": "cancelled", "title": ""})
            return

        if code == 0 and not had_error:
            self.store.job_update(job.id, status="done", progress=1.0)
            outcome = "no_subtitles" if no_subtitles else "success"
            self.store.job_meta_update(job.id, {"outcome": outcome})
            # Post-pipeline
            self._find_and_process(job, opts, start_t, detected_title)
            self.store.history_add(job.url, detected_title, opts.get("channel", ""),
                                   opts.get("mode", "Audio"), str(DOWNLOAD_DIR))
            self.store._emit("done", {"id": job.id, "result": outcome, "title": detected_title})
        else:
            self.store.job_update(job.id, status="error")
            outcome = "rate_limited" if had_429 else "error"
            self.store.job_meta_update(job.id, {"outcome": outcome})
            self.store._emit("done", {"id": job.id, "result": outcome, "title": ""})

    def _find_and_process(self, job: JobRow, opts: dict, after: float, title: str):
        """Trouve le fichier créé et lance le pipeline."""
        exts = []
        if opts.get("mode") == "Audio":
            exts = [".mp3", ".m4a", ".opus", ".wav", ".flac", ".aac"]
        elif opts.get("mode") == "Vidéo":
            exts = [".mp4", ".mkv", ".webm"]
        else:
            return
        best: Optional[Path] = None
        best_t = 0
        for ext in exts:
            for f in DOWNLOAD_DIR.rglob(f"*{ext}"):
                try:
                    st = f.stat().st_mtime
                    if st > after and st > best_t:
                        best_t = st
                        best = f
                except Exception:
                    continue
        if best:
            meta = {"lang": LANG_OPTIONS.get(opts.get("sub_lang1", "Français"), "fr"),
                    "transcribe": opts.get("mode") in ("Audio", "Vidéo")}
            self.pipe.run(best, opts.get("mode"), meta)

    def cancel(self):
        if not hasattr(self, "_cancel_event"):
            self._cancel_event = threading.Event()
        self._cancel_event.set()
        if self._proc and self._proc.poll() is None:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    self._proc.kill()


# ── QUEUE WORKER ─────────────────────────────────────────────────────────────
class QueueWorker(threading.Thread):
    """Daemon qui consomme la file SQLite et exécute les jobs."""
    def __init__(self, store: Store, runner: YtDlpRunner):
        super().__init__(daemon=True)
        self.store = store
        self.runner = runner
        self._running = True
        self._last_subtitle_finished = 0.0

    def run(self):
        self.store.recover_jobs()
        while self._running:
            policy = self.runner.gov.get_policy()
            if policy.concurrent == 0:
                time.sleep(30)
                continue
            job = self.store.job_claim_next()
            if not job:
                time.sleep(2)
                continue
            if job.mode == "Sous-titres" and self._last_subtitle_finished:
                delay = random.uniform(SUBTITLE_DELAY_MIN, SUBTITLE_DELAY_MAX)
                remaining = delay - (time.time() - self._last_subtitle_finished)
                if remaining > 0:
                    self.store.job_update(job.id, status="waiting")
                    self.store._emit("log", {"text": f"Attente sous-titres: {remaining:.0f}s avant le prochain élément.\n", "color": INFO})
                    while remaining > 0 and self._running and not getattr(self.runner, "_cancel_event", threading.Event()).is_set():
                        time.sleep(min(0.25, remaining))
                        remaining = delay - (time.time() - self._last_subtitle_finished)
                    if not self._running or getattr(self.runner, "_cancel_event", threading.Event()).is_set():
                        self.store.job_update(job.id, status="cancelled")
                        continue
                    self.store.job_update(job.id, status="running")
            opts = (job.meta or {}).get("opts")
            if not opts:
                self.store.job_update(job.id, status="error")
                time.sleep(1)
                continue
            self.runner.run(job, opts)
            while True:
                time.sleep(0.5)
                with self.store._lock:
                    cur = self.store._db.execute("SELECT status FROM jobs WHERE id=?", (job.id,))
                    row = cur.fetchone()
                if not row or row[0] not in ("running", "waiting", "retrying"):
                    break
            if job.mode == "Sous-titres":
                self._last_subtitle_finished = time.time()

    def stop(self):
        self._running = False
        self.runner.cancel()
        self.store.cancel_queued()


# ── UI ───────────────────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title(APP_NAME)
        h = min(840, max(640, self.winfo_screenheight() - 100))
        self.geometry(f"860x{h}")
        self.minsize(760, 600)
        self.configure(fg_color=BG)

        # Core
        self.store = Store()
        self.ui_queue: queue.Queue = queue.Queue()
        self.store.set_ui_queue(self.ui_queue)

        self.gov = Governor()
        self.pipe = Pipeline()
        self.runner = YtDlpRunner(self.store, self.gov, self.pipe)
        self.worker = QueueWorker(self.store, self.runner)
        self.worker.start()

        self.busy = False
        self._ch_entries: List[dict] = []
        self._ch_vars: List[tuple] = []
        self._ch_offset = 0
        self._ch_batch = 80
        self._ch_panel_visible = False

        self._build()
        self._on_mode_change("Audio")
        self._poll_ui_queue()

    # ── BUILD ─────────────────────────────────────────────────────────────────
    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent", height=44)
        hdr.pack(fill="x", padx=20, pady=(10, 0))
        hdr.pack_propagate(False)

        wm = ctk.CTkFrame(hdr, fg_color="transparent")
        wm.pack(side="left", fill="y")
        ctk.CTkLabel(wm, text="◆", font=("SF Pro Display", 12), text_color=ACCENT).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(wm, text="Extractor", font=FONT_TITLE, text_color=TEXT).pack(side="left")

        self.ver_lbl = ctk.CTkLabel(hdr, text="", font=FONT_SMALL, text_color=TEXT_DIM)
        self.ver_lbl.pack(side="right", padx=(0, 4))
        ctk.CTkButton(hdr, text="↑", font=FONT_SMALL, width=26, height=26,
                      fg_color="transparent", hover_color=BG_ELEVATED, text_color=TEXT_DIM,
                      border_color=BORDER, border_width=1, corner_radius=6,
                      command=self._update_ytdlp).pack(side="right")
        threading.Thread(target=self._fetch_version, daemon=True).start()

        ctk.CTkFrame(self, fg_color=BORDER, height=1).pack(fill="x", pady=(8, 0))

        # Main area
        self._main_area = ctk.CTkFrame(self, fg_color="transparent")
        self._main_area.pack(fill="both", expand=True, padx=16, pady=4)
        self._main_area.grid_rowconfigure(0, weight=1)
        self._main_area.grid_columnconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(
            self._main_area, fg_color=BG,
            segmented_button_fg_color=BG_ELEVATED,
            segmented_button_selected_color=BG_INPUT,
            segmented_button_selected_hover_color=BG_INPUT,
            segmented_button_unselected_color=BG_ELEVATED,
            segmented_button_unselected_hover_color=BG_INPUT,
            text_color=TEXT, border_color=BORDER, border_width=1,
        )
        self.tabs.grid(row=0, column=0, sticky="nsew")
        self.tabs.add("  Télécharger  ")
        self.tabs.add("  File  ")
        self.tabs.add("  Historique  ")
        self.tabs.add("  Aide  ")

        self._build_download_tab(self.tabs.tab("  Télécharger  "))
        self._build_queue_tab(self.tabs.tab("  File  "))
        self._build_history_tab(self.tabs.tab("  Historique  "))
        self._build_help_tab(self.tabs.tab("  Aide  "))

        self._build_channel_panel()

        # Separator + Progress
        ctk.CTkFrame(self, fg_color=BORDER, height=1).pack(fill="x")
        self.progress = ctk.CTkProgressBar(self, height=2, progress_color=ACCENT,
                                           fg_color=BG_ELEVATED, corner_radius=0)
        self.progress.set(0)
        self.progress.pack(fill="x")

        # Footer
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=16, pady=(6, 4))

        self.btn_run = ctk.CTkButton(
            foot, text="▶  Télécharger", font=FONT_UI, height=38, width=148,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color="#fff",
            corner_radius=8, command=self._run,
        )
        self.btn_run.pack(side="left")

        self.btn_queue = ctk.CTkButton(
            foot, text="+", font=FONT_UI, height=38, width=38,
            fg_color="transparent", hover_color=BG_ELEVATED, text_color=TEXT_DIM,
            border_color=BORDER, border_width=1, corner_radius=8,
            command=self._add_to_queue,
        )
        self.btn_queue.pack(side="left", padx=(6, 0))

        self.status = ctk.CTkLabel(foot, text="prêt", font=FONT_SMALL,
                                   text_color=TEXT_DIM, anchor="center")
        self.status.pack(side="left", fill="x", expand=True)

        self.btn_cancel = ctk.CTkButton(
            foot, text="◼", font=FONT_UI, height=38, width=38,
            fg_color="transparent", hover_color=BG_ELEVATED, text_color=TEXT_DIM,
            border_color=BORDER, border_width=1, corner_radius=8,
            command=self._cancel, state="disabled",
        )
        self.btn_cancel.pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            foot, text="📁", font=FONT_UI, height=38, width=38,
            fg_color="transparent", hover_color=BG_ELEVATED, text_color=TEXT_DIM,
            border_color=BORDER, border_width=1, corner_radius=8,
            command=self._open_folder,
        ).pack(side="right")

        # Log handle + panel
        self._log_h = tk.Frame(self, height=4, bg=BORDER, cursor="sb_v_double_arrow")
        self._log_h.pack(fill="x")
        self._log_h.bind("<Enter>", lambda e: self._log_h.configure(bg=ACCENT_DIM))
        self._log_h.bind("<Leave>", lambda e: self._log_h.configure(bg=BORDER))
        self._log_h.bind("<Button-1>", self._log_resize_start)
        self._log_h.bind("<B1-Motion>", self._log_resize_drag)

        self.log = ctk.CTkTextbox(
            self, height=90, font=FONT_MONO_XS, fg_color=BG_ELEVATED,
            text_color=TEXT_DIM, border_color=BORDER, border_width=1,
            corner_radius=0, wrap="none",
        )
        self.log.pack(fill="x", padx=0, pady=0)
        for tag, col in [("error", ERROR), ("warn", WARN), ("success", SUCCESS),
                         ("info", INFO), ("accent", ACCENT), ("dim", TEXT_DIM)]:
            self.log.tag_config(tag, foreground=col)
        self._log_insert("── log ─\n", "dim")

    # ── TABS ──────────────────────────────────────────────────────────────────
    def _build_download_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        scroll._scrollbar.configure(width=6)
        self._dl_scroll = scroll

        # URL
        url_row = ctk.CTkFrame(scroll, fg_color="transparent")
        url_row.pack(fill="x", padx=8, pady=(10, 2))
        self.entry_url = ctk.CTkTextbox(
            url_row, height=64, font=FONT_MONO, fg_color=BG_INPUT,
            border_color=BORDER, border_width=1, text_color=TEXT, wrap="none", corner_radius=8,
        )
        self.entry_url.pack(fill="x", expand=True)
        self.entry_url.bind("<KeyRelease>", lambda e: self._on_url_change())
        self.entry_url.bind("<<Paste>>", lambda e: self.after(20, self._on_url_change))

        self.url_status = ctk.CTkLabel(scroll, text="", font=FONT_SMALL,
                                       text_color=TEXT_DIM, anchor="w")
        self.url_status.pack(fill="x", padx=10, pady=(2, 6))

        # Mode
        self.mode_seg = ctk.CTkSegmentedButton(
            scroll, values=["Audio", "Vidéo", "Sous-titres"],
            font=FONT_UI_S, height=34, fg_color=BG_INPUT, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOV, unselected_color=BG_INPUT,
            unselected_hover_color=BG_ELEVATED, text_color=TEXT,
            command=self._on_mode_change,
        )
        self.mode_seg.set("Audio")
        self.mode_seg.pack(fill="x", padx=8, pady=(0, 8))

        # Options
        self.opts_card = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED,
                                      corner_radius=8, border_color=BORDER, border_width=1)
        self.opts_card.pack(fill="x", padx=8, pady=(0, 8))
        self._build_dynamic_opts()

        # Time
        trow = ctk.CTkFrame(scroll, fg_color="transparent")
        trow.pack(fill="x", padx=8, pady=(0, 8))
        self.entry_start = self._input(trow, "début  00:00")
        self.entry_start.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(trow, text="—", font=FONT_UI_S, text_color=TEXT_DIM).pack(side="left", padx=10)
        self.entry_end = self._input(trow, "fin  05:30")
        self.entry_end.pack(side="left", fill="x", expand=True)

        # Advanced
        self._adv_open = False
        self._adv_btn = ctk.CTkButton(
            scroll, text="  Avancé  ›", font=FONT_UI_S, height=28,
            fg_color="transparent", hover_color=BG_ELEVATED, text_color=TEXT_DIM,
            anchor="w", corner_radius=8, border_width=0,
            command=self._toggle_adv,
        )
        self._adv_btn.pack(fill="x", padx=8, pady=(0, 2))

        self.adv_frame = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED,
                                      corner_radius=8, border_color=BORDER, border_width=1)
        adv_inner = ctk.CTkFrame(self.adv_frame, fg_color="transparent")
        adv_inner.pack(fill="x", padx=14, pady=10)

        self.var_playlist = ctk.BooleanVar(value=False)
        self.var_thumb = ctk.BooleanVar(value=True)
        self.var_subs_embed = ctk.BooleanVar(value=False)
        self.var_sponsorbl = ctk.BooleanVar(value=False)
        self.var_chapters = ctk.BooleanVar(value=False)

        self._sw(adv_inner, "Playlist", self.var_playlist).grid(row=0, column=0, sticky="w", padx=4, pady=3)
        self._sw(adv_inner, "Miniature", self.var_thumb).grid(row=0, column=1, sticky="w", padx=4, pady=3)
        self._sw(adv_inner, "Subs embarqués", self.var_subs_embed).grid(row=1, column=0, sticky="w", padx=4, pady=3)
        self._sw(adv_inner, "SponsorBlock", self.var_sponsorbl).grid(row=1, column=1, sticky="w", padx=4, pady=3)
        self._sw(adv_inner, "Par chapitres", self.var_chapters).grid(row=2, column=0, sticky="w", padx=4, pady=3)

        crow = ctk.CTkFrame(adv_inner, fg_color="transparent")
        crow.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(crow, text="Cookies", font=FONT_SMALL, text_color=TEXT_DIM).pack(side="left")
        self.cookies_file_entry = ctk.CTkEntry(
            crow, placeholder_text="cookies.txt", font=FONT_MONO_S, height=26,
            fg_color=BG_INPUT, border_color=BORDER, border_width=1, text_color=TEXT,
        )
        self.cookies_file_entry.pack(side="left", fill="x", expand=True, padx=6)
        self._ghost(crow, "📂", self._browse_cookies, width=40).pack(side="left")

    def _build_queue_tab(self, parent):
        ctk.CTkLabel(parent, text="File persistante SQLite — survit aux redémarrages",
                     font=FONT_SMALL, text_color=TEXT_DIM, anchor="w").pack(fill="x", padx=8, pady=(10, 6))
        self.queue_box = ctk.CTkTextbox(
            parent, font=FONT_MONO_S, fg_color=BG_INPUT, text_color=TEXT,
            border_color=BORDER, border_width=1, corner_radius=8,
        )
        self.queue_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        brow = ctk.CTkFrame(parent, fg_color="transparent")
        brow.pack(fill="x", padx=8, pady=(0, 8))
        self._ghost(brow, "▶  Lancer la file", self._run_queue, width=140).pack(side="left")
        self._ghost(brow, "🗑  Vider", self._clear_queue).pack(side="left", padx=(6, 0))

    def _build_history_tab(self, parent):
        srow = ctk.CTkFrame(parent, fg_color="transparent")
        srow.pack(fill="x", padx=8, pady=(8, 4))
        self.hist_search = ctk.CTkEntry(
            srow, placeholder_text="Rechercher…", font=FONT_UI_S, height=30,
            fg_color=BG_INPUT, border_color=BORDER, border_width=1, text_color=TEXT,
        )
        self.hist_search.pack(side="left", fill="x", expand=True)
        self.hist_search.bind("<KeyRelease>", lambda e: self._refresh_history())
        self._ghost(srow, "↻", self._refresh_history, width=36).pack(side="left", padx=(6, 0))

        self.history_frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.history_frame.pack(fill="both", expand=True)
        self.history_frame._scrollbar.configure(width=6)
        self._refresh_history()

    def _build_help_tab(self, parent):
        txt = ctk.CTkTextbox(parent, font=FONT_MONO_S, fg_color=BG_INPUT,
                             text_color=TEXT_DIM, border_color=BORDER, border_width=1,
                             corner_radius=8, wrap="word")
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        help_text = """
◆ EXTRACTOR SYSTEM v3

── ARCHITECTURE ─────────────────────────────────────────────────
SQLite · Governor M5 · EventBus · Pipeline local

── MODES ────────────────────────────────────────────────────────
Audio  → MP3/M4A/OPUS/WAV/FLAC/AAC + loudnorm + transcription MLX
Vidéo  → h264/av1 + scènes auto + sous-titres Whisper
Subs   → SRT/VTT/ASS/LRC/TXT (sleep 2s, cookies auto)

── GOVERNOR ─────────────────────────────────────────────────────
Détecte batterie / thermique en temps réel.
Débranche le câble → baisse auto en 720p / 2M.
Mac > 80°C → pause automatique.

── FILE PERSISTANTE ─────────────────────────────────────────────
Ajoute une URL → stockée en SQLite immédiatement.
Crash / redémarrage → reprise exacte où ça s'est arrêté.

── RACCOURCIS ───────────────────────────────────────────────────
Cmd+Shift+D (global) → DL l'URL du presse-papiers
Share Extension Safari → envoi direct

── POST-TRAITEMENT AUTO ─────────────────────────────────────────
Whisper MLX (Neural Engine) : 1h audio → ~45s
Loudnorm -14 LUFS : volume uniforme
Scene detect : storyboard visuel dans .scenes/
"""
        txt.insert("1.0", help_text.strip())
        txt.configure(state="disabled")

    def _build_dynamic_opts(self):
        wrap = ctk.CTkFrame(self.opts_card, fg_color="transparent")
        wrap.pack(fill="x", padx=14, pady=10)
        self._opts_wrap = wrap

        self.audio_fmt = self._optmenu(wrap, ["MP3", "M4A", "OPUS", "WAV", "FLAC", "AAC"], "MP3")
        self.vid_qual = self._optmenu(wrap, ["Best", "2160p", "1440p", "1080p", "720p", "480p", "360p"], "1080p")
        self.vid_fmt = self._optmenu(wrap, ["MP4", "MKV", "WEBM"], "MP4")
        self.vid_codec = self._optmenu(wrap, ["any", "h264", "av1", "vp9"], "h264")
        self.sub_fmt = self._optmenu(wrap, ["SRT", "VTT", "ASS", "LRC", "TXT"], "SRT")
        self.sub_lang1 = self._optmenu(wrap, list(LANG_OPTIONS.keys()), "Français")
        self.sub_lang2 = self._optmenu(wrap, ["(aucune)"] + list(LANG_OPTIONS.keys()), "English")

    def _build_channel_panel(self):
        self._ch_panel = ctk.CTkFrame(
            self._main_area, fg_color=BG_ELEVATED, corner_radius=8,
            border_color=BORDER, border_width=1, width=300,
        )
        self._ch_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._ch_panel.grid_remove()

        hdr = ctk.CTkFrame(self._ch_panel, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(10, 4))
        self._ch_status_lbl = ctk.CTkLabel(hdr, text="Chaîne", font=FONT_UI_S,
                                           text_color=TEXT_DIM, anchor="w")
        self._ch_status_lbl.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(hdr, text="✕", width=24, height=24, font=FONT_UI_S,
                      fg_color="transparent", hover_color=BG_ELEVATED,
                      text_color=TEXT_DIM, border_width=0, corner_radius=4,
                      command=self._hide_channel_panel).pack(side="right")

        ctk.CTkFrame(self._ch_panel, fg_color=BORDER, height=1).pack(fill="x")

        ctrl = ctk.CTkFrame(self._ch_panel, fg_color="transparent")
        ctrl.pack(fill="x", padx=8, pady=(6, 2))
        for txt, val in (("Tout", True), ("Aucun", False)):
            ctk.CTkButton(
                ctrl, text=txt, font=FONT_UI_S, height=26, width=56,
                fg_color="transparent", hover_color=BG_ELEVATED, text_color=TEXT_DIM,
                border_color=BORDER, border_width=1, corner_radius=5,
                command=lambda v=val: self._ch_select_all(v),
            ).pack(side="left", padx=(0, 4))

        self._ch_count_lbl = ctk.CTkLabel(ctrl, text="", font=FONT_UI_S,
                                          text_color=TEXT_DIM, anchor="e")
        self._ch_count_lbl.pack(side="right")

        self._ch_list = ctk.CTkScrollableFrame(self._ch_panel, fg_color="transparent")
        self._ch_list.pack(fill="both", expand=True, padx=6, pady=(4, 0))
        self._ch_list._scrollbar.configure(width=6)

        self._ch_mode_lbl = ctk.CTkLabel(self._ch_panel, text="", font=FONT_UI_S,
                                         text_color=ACCENT, anchor="w")
        self._ch_mode_lbl.pack(fill="x", padx=12, pady=(4, 0))

        ctk.CTkFrame(self._ch_panel, fg_color=BORDER, height=1).pack(fill="x")
        self._ch_dl_btn = ctk.CTkButton(
            self._ch_panel, text="Télécharger la sélection", font=FONT_UI_S, height=38,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color="#fff",
            corner_radius=8, command=self._ch_download, state="disabled",
        )
        self._ch_dl_btn.pack(fill="x", padx=12, pady=8)

        # Pagination
        self._ch_more_btn = ctk.CTkButton(
            self._ch_panel, text="▼ Charger plus", font=FONT_UI_S, height=28,
            fg_color="transparent", hover_color=BG_ELEVATED, text_color=TEXT_DIM,
            command=self._ch_load_more,
        )
        self._ch_more_btn.pack(fill="x", padx=12, pady=(0, 4))

    # ── LOGIC ─────────────────────────────────────────────────────────────────
    def _on_mode_change(self, mode: str):
        for w in self._opts_wrap.winfo_children():
            w.grid_forget()
        g = self._opts_wrap
        for i in range(6):
            g.grid_columnconfigure(i, weight=0)

        if mode == "Audio":
            g.grid_columnconfigure(0, weight=1)
            self.audio_fmt.grid(row=0, column=0, sticky="ew")
        elif mode == "Vidéo":
            for i in range(3):
                g.grid_columnconfigure(i, weight=1)
            self.vid_qual.grid(row=0, column=0, sticky="ew", padx=(0, 6))
            self.vid_fmt.grid(row=0, column=1, sticky="ew", padx=(0, 6))
            self.vid_codec.grid(row=0, column=2, sticky="ew")
        elif mode == "Sous-titres":
            for i in range(2):
                g.grid_columnconfigure(i, weight=1)
            self.sub_fmt.grid(row=0, column=0, sticky="ew", padx=(0, 6))
            self.sub_lang1.grid(row=0, column=1, sticky="ew")
        self._update_ch_mode_lbl()

    def _toggle_adv(self):
        self._adv_open = not self._adv_open
        if self._adv_open:
            self.adv_frame.pack(fill="x", padx=8, pady=(0, 8))
            self._adv_btn.configure(text="  Avancé  ˅")
        else:
            self.adv_frame.pack_forget()
            self._adv_btn.configure(text="  Avancé  ›")

    def _get_valid_urls(self) -> List[str]:
        text = self.entry_url.get("1.0", "end-1c")
        urls = []
        for u in text.splitlines():
            u = u.strip()
            if not u:
                continue
            try:
                p = urlparse(u)
                if p.scheme in ("http", "https") and p.netloc:
                    urls.append(u)
            except Exception:
                pass
        return urls

    def _validate_url(self) -> bool:
        urls = self._get_valid_urls()
        if urls:
            n = len(urls)
            self.url_status.configure(text=f"✓ {n} URL valide{'s' if n > 1 else ''}", text_color=SUCCESS)
        else:
            text = self.entry_url.get("1.0", "end-1c").strip()
            if text:
                self.url_status.configure(text="✗ URL invalide", text_color=ERROR)
            else:
                self.url_status.configure(text="", text_color=TEXT_DIM)
        return bool(urls)

    def _on_url_change(self):
        self._validate_url()
        urls = self._get_valid_urls()
        if not urls:
            return
        url = urls[0]
        # Auto-preset
        preset = self.store.preset_for_url(url)
        if preset:
            self._apply_preset(preset)
        if self._is_channel(url):
            if not self._ch_panel_visible or getattr(self, "_last_ch_url", None) != url:
                self._last_ch_url = url
                self._show_channel_panel(url)

    def _apply_preset(self, p: dict):
        if "mode" in p:
            self.mode_seg.set(p["mode"])
            self._on_mode_change(p["mode"])
        if "audio_fmt" in p:
            self.audio_fmt.set(p["audio_fmt"])
        if "video_quality" in p:
            self.vid_qual.set(p["video_quality"])
        if "video_codec" in p:
            self.vid_codec.set(p["video_codec"])

    def _is_channel(self, url: str) -> bool:
        try:
            p = urlparse(url)
            if not any(h in p.netloc for h in ("youtube.com", "youtu.be")):
                return False
            path = p.path
            if re.search(r'^/@[^/?#]+', path):
                return True
            if re.search(r'^/(c|user|channel)/[^/?#]+', path):
                return True
            if "/playlist" in path:
                return True
            if "list=" in p.query and "v=" not in p.query:
                return True
        except Exception:
            pass
        return False

    def _build_opts(self, url: str) -> dict:
        return {
            "url": url,
            "mode": self.mode_seg.get(),
            "start": self.entry_start.get().strip(),
            "end": self.entry_end.get().strip(),
            "audio_format": self.audio_fmt.get(),
            "video_quality": self.vid_qual.get(),
            "video_format": self.vid_fmt.get(),
            "video_codec": self.vid_codec.get(),
            "sub_format": self.sub_fmt.get(),
            "sub_lang1": self.sub_lang1.get(),
            "sub_lang2": self.sub_lang2.get(),
            "playlist": self.var_playlist.get(),
            "embed_thumb": self.var_thumb.get(),
            "embed_subs": self.var_subs_embed.get(),
            "sponsorblock": self.var_sponsorbl.get(),
            "split_chapters": self.var_chapters.get(),
            "cookies_file": self.cookies_file_entry.get().strip(),
            "channel_folder": "",
        }

    def _run(self):
        if self.busy:
            return
        urls = self._get_valid_urls()
        if not urls:
            self.status.configure(text="URL invalide", text_color=ERROR)
            return
        for url in urls:
            opts = self._build_opts(url)
            preset = self.store.preset_for_url(url)
            if preset:
                opts["post"] = preset.get("post", [])
            self.store.job_add(url, opts["mode"], preset=preset, meta={"opts": opts})
        self.status.configure(text=f"{len(urls)} job(s) en file", text_color=SUCCESS)
        self.entry_url.delete("1.0", "end")
        self._validate_url()
        self._refresh_queue_box()

    def _add_to_queue(self):
        urls = self._get_valid_urls()
        if not urls:
            self.status.configure(text="URL invalide", text_color=ERROR)
            return
        for url in urls:
            opts = self._build_opts(url)
            preset = self.store.preset_for_url(url)
            self.store.job_add(url, opts["mode"], preset=preset, meta={"opts": opts})
        self.status.configure(text=f"{len(urls)} ajouté(s)", text_color=SUCCESS)
        self._refresh_queue_box()
        self.tabs.set("  File  ")

    def _run_queue(self):
        # Synchronise la textbox vers SQLite si vide
        text = self.queue_box.get("1.0", "end-1c")
        for line in text.splitlines():
            u = line.strip()
            if u and u.startswith("http"):
                # évite les doublons déjà en base
                self.store.job_add(u, self.mode_seg.get(), meta={"opts": self._build_opts(u)})
        self.queue_box.delete("1.0", "end")
        self._refresh_queue_box()
        self.status.configure(text="File synchronisée", text_color=SUCCESS)

    def _clear_queue(self):
        # Supprime les jobs queued de SQLite
        with self.store._lock:
            self.store._db.execute("DELETE FROM jobs WHERE status='queued'")
            self.store._db.commit()
        self.queue_box.delete("1.0", "end")
        self._refresh_queue_box()

    def _cancel(self):
        self.runner.cancel()
        self.store.cancel_queued()
        self.status.configure(text="annulation de la file…", text_color=WARN)
        self._refresh_queue_box()

    def _set_busy(self, busy: bool):
        self.busy = busy
        s = "disabled" if busy else "normal"
        self.btn_run.configure(state=s)
        self.btn_queue.configure(state=s)
        if busy:
            self.btn_cancel.configure(state="normal", text_color=ERROR, border_color=ERROR)
        else:
            self.btn_cancel.configure(state="disabled", text_color=TEXT_DIM, border_color=BORDER)

    # ── UI QUEUE POLL ─────────────────────────────────────────────────────────
    def _poll_ui_queue(self):
        try:
            while True:
                ev, data = self.ui_queue.get_nowait()
                if ev == "log":
                    self._log_insert(data["text"], {ERROR: "error", WARN: "warn",
                                                    SUCCESS: "success", INFO: "info",
                                                    ACCENT: "accent"}.get(data.get("color"), "dim"))
                elif ev == "job_started":
                    self._set_busy(True)
                    self.progress.set(0)
                    self.status.configure(text=f"DL #{data['id']}…", text_color=WARN)
                elif ev == "job_updated":
                    p = data.get("progress")
                    if p is not None:
                        self.progress.set(p)
                    status = data.get("status")
                    if status == "waiting":
                        self.status.configure(text="attente avant le prochain sous-titre…", text_color=INFO)
                    elif status == "retrying":
                        self.status.configure(text="nouvelle tentative après rate limit…", text_color=WARN)
                    self._refresh_queue_box()
                elif ev == "done":
                    res = data["result"]
                    if res == "ok":
                        self.progress.set(1.0)
                        self.status.configure(text=f"✓ {data.get('title','terminé')[:40]}", text_color=SUCCESS)
                    elif res == "success":
                        self.progress.set(1.0)
                        self.status.configure(text="✓ sous-titres terminés", text_color=SUCCESS)
                    elif res == "no_subtitles":
                        self.status.configure(text="aucun sous-titre demandé", text_color=WARN)
                    elif res == "cancelled":
                        self.status.configure(text="annulé", text_color=WARN)
                        self.progress.set(0)
                    elif res == "rate_limited":
                        self.status.configure(text="abandonné après rate limit", text_color=ERROR)
                        self.progress.set(0)
                    else:
                        self.status.configure(text=f"échec — {res}", text_color=ERROR)
                        self.progress.set(0)
                    self._set_busy(False)
                    self._refresh_history()
                    self._refresh_queue_box()
                elif ev == "history_changed":
                    self._refresh_history()
                elif ev == "job_added":
                    self._refresh_queue_box()
        except queue.Empty:
            pass
        self.after(150, self._poll_ui_queue)

    # ── HISTORY ───────────────────────────────────────────────────────────────
    def _refresh_history(self):
        for w in self.history_frame.winfo_children():
            w.destroy()
        q = self.hist_search.get().strip()
        if q:
            rows = self.store.history_search(q, limit=40)
        else:
            rows = self.store.history_fetch(limit=30)
        if not rows:
            ctk.CTkLabel(self.history_frame, text="Aucun historique.", font=FONT_UI_S,
                         text_color=TEXT_DIM).pack(pady=20)
            return
        for r in rows:
            _, url, title, channel, mode, fpath, _, date = r
            row = ctk.CTkFrame(self.history_frame, fg_color=BG_ELEVATED,
                               corner_radius=8, border_color=BORDER, border_width=1)
            row.pack(fill="x", padx=8, pady=3)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(inner, text=f"{mode}  ·  {self._fmt_ts(date)}",
                         font=FONT_SMALL, text_color=ACCENT, anchor="w").pack(fill="x")
            ctk.CTkLabel(inner, text=(title or url)[:70], font=FONT_UI_S,
                         text_color=TEXT, anchor="w").pack(fill="x")
            def _reuse(u=url):
                self.entry_url.delete("1.0", "end")
                self.entry_url.insert("1.0", u)
                self._on_url_change()
                self.tabs.set("  Télécharger  ")
            self._ghost(inner, "↩", _reuse, width=70).pack(anchor="e")

    def _fmt_ts(self, ts: float) -> str:
        return datetime.fromtimestamp(ts).strftime("%d/%m %H:%M") if ts else ""

    # ── QUEUE BOX ─────────────────────────────────────────────────────────────
    def _refresh_queue_box(self):
        self.queue_box.delete("1.0", "end")
        jobs = self.store.queue_list(limit=100)
        for j in jobs:
            status_icon = {
                "queued": "○", "running": "▶", "waiting": "◷", "retrying": "↻",
                "done": "✓", "error": "✗", "cancelled": "⊘",
            }.get(j.status, "?")
            self.queue_box.insert("end", f"{status_icon} [{j.mode}] {j.url[:70]}\n")

    # ── CHANNEL PANEL ─────────────────────────────────────────────────────────
    def _show_channel_panel(self, url: str):
        self._ch_entries.clear()
        self._ch_vars.clear()
        self._ch_offset = 0
        self._channel_name = ""
        for w in self._ch_list.winfo_children():
            w.destroy()
        self._ch_status_lbl.configure(text="Chargement…", text_color=TEXT_DIM)
        self._ch_dl_btn.configure(state="disabled")
        self._ch_count_lbl.configure(text="")
        self._update_ch_mode_lbl()
        self._main_area.grid_columnconfigure(1, minsize=300)
        self._ch_panel.grid()
        self._ch_panel_visible = True
        threading.Thread(target=self._fetch_channel, args=(url,), daemon=True).start()

    def _hide_channel_panel(self):
        self._ch_panel.grid_remove()
        self._main_area.grid_columnconfigure(1, minsize=0)
        self._ch_panel_visible = False
        # LIBÈRE LA RAM
        self._ch_entries.clear()
        self._ch_vars.clear()
        for w in self._ch_list.winfo_children():
            w.destroy()

    def _update_ch_mode_lbl(self):
        mode = self.mode_seg.get()
        if mode == "Audio":
            txt = f"{mode} · {self.audio_fmt.get()}"
        elif mode == "Vidéo":
            txt = f"{mode} · {self.vid_qual.get()} {self.vid_fmt.get()}"
        else:
            txt = f"{mode} · {self.sub_fmt.get()}"
        self._ch_mode_lbl.configure(text=f"↓ {txt}")

    def _fetch_channel(self, url: str):
        try:
            proc = subprocess.Popen(
                ["yt-dlp", "--flat-playlist", "-j", "--no-warnings", url],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
            )
            count = 0
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                count += 1
                self._ch_entries.append(entry)
                if count <= self._ch_batch:
                    self.after(0, self._ch_render_entry, entry, count)
            proc.wait()
            self.after(0, self._ch_done, count)
        except Exception as e:
            self.after(0, lambda: self._ch_status_lbl.configure(text=f"Erreur: {e}", text_color=ERROR))

    def _ch_render_entry(self, entry: dict, idx: int):
        if not self._ch_panel_visible:
            return
        if not self._channel_name:
            self._channel_name = (entry.get("channel") or entry.get("uploader") or
                                  entry.get("playlist_title") or "")
        title = (entry.get("title") or entry.get("id") or f"#{idx}")[:46]
        var = ctk.BooleanVar(value=False)
        self._ch_vars.append((var, entry))

        row = ctk.CTkFrame(self._ch_list, fg_color="transparent", height=28)
        row.pack(fill="x", padx=2, pady=1)
        row.pack_propagate(False)

        ctk.CTkCheckBox(
            row, text="", variable=var, width=18, checkbox_width=15, checkbox_height=15,
            fg_color=ACCENT, hover_color=ACCENT_HOV, border_color=BORDER,
            command=self._ch_update_count,
        ).pack(side="left", padx=(2, 4))

        ctk.CTkLabel(row, text=f"{idx:>3}  {title}", font=("JetBrains Mono", 10),
                     text_color=TEXT_DIM, anchor="w").pack(side="left", fill="x", expand=True)

    def _ch_load_more(self):
        start = self._ch_offset
        end = min(start + self._ch_batch, len(self._ch_entries))
        for i in range(start, end):
            self._ch_render_entry(self._ch_entries[i], i + 1)
        self._ch_offset = end
        if self._ch_offset >= len(self._ch_entries):
            self._ch_more_btn.configure(state="disabled", text="Tout chargé")
        else:
            self._ch_more_btn.configure(state="normal", text=f"▼ Charger plus ({len(self._ch_entries) - self._ch_offset})")

    def _ch_done(self, count: int):
        if not self._ch_panel_visible:
            return
        self._ch_status_lbl.configure(text=f"{count} vidéo(s)", text_color=TEXT)
        self._ch_offset = min(self._ch_batch, count)
        if count > self._ch_batch:
            self._ch_more_btn.configure(state="normal", text=f"▼ Charger plus ({count - self._ch_batch})")
        else:
            self._ch_more_btn.configure(state="disabled", text="Tout chargé")
        if count > 0:
            self._ch_dl_btn.configure(state="normal")

    def _ch_select_all(self, val: bool):
        for var, _ in self._ch_vars:
            var.set(val)
        self._ch_update_count()

    def _ch_update_count(self):
        n = sum(1 for v, _ in self._ch_vars if v.get())
        self._ch_count_lbl.configure(text=f"{n} sélectionnée(s)" if n else "")

    def _ch_download(self):
        selected = [(v, e) for v, e in self._ch_vars if v.get()]
        if not selected:
            return
        folder = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', self._channel_name)[:120] if self._channel_name else ""
        for _, entry in selected:
            vid = (entry.get("url") or entry.get("webpage_url") or
                   f"https://www.youtube.com/watch?v={entry.get('id','')}")
            opts = self._build_opts(vid)
            opts["channel_folder"] = folder
            self.store.job_add(vid, opts["mode"], meta={"opts": opts})
        self._hide_channel_panel()
        self.status.configure(text=f"{len(selected)} en file", text_color=WARN)
        self._refresh_queue_box()

    # ── HELPERS ───────────────────────────────────────────────────────────────
    def _log_insert(self, text: str, tag: str = "dim"):
        self.log.configure(state="normal")
        self.log.insert("end", text, tag)
        # Limite taille log (RAM)
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 500:
            self.log.delete("1.0", "100.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _log_resize_start(self, e):
        self._log_drag_y = e.y_root
        self._log_drag_h = self.log.winfo_height()

    def _log_resize_drag(self, e):
        dy = self._log_drag_y - e.y_root
        nh = max(40, min(400, self._log_drag_h + dy))
        self.log.configure(height=int(nh))

    def _input(self, parent, ph):
        return ctk.CTkEntry(parent, placeholder_text=ph, font=FONT_MONO, height=34,
                            fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                            text_color=TEXT, placeholder_text_color=TEXT_DIM, corner_radius=8)

    def _ghost(self, parent, text, cmd, width=76, height=34):
        return ctk.CTkButton(parent, text=text, command=cmd, font=FONT_UI_S,
                             height=height, width=width, fg_color="transparent",
                             hover_color=BG_ELEVATED, text_color=TEXT_DIM,
                             border_color=BORDER, border_width=1, corner_radius=8)

    def _sw(self, parent, text, var):
        return ctk.CTkSwitch(parent, text=text, variable=var, font=FONT_UI_S, text_color=TEXT,
                             progress_color=ACCENT, button_color=TEXT_DIM,
                             button_hover_color=TEXT, fg_color=BG_INPUT)

    def _optmenu(self, parent, values, default):
        m = ctk.CTkOptionMenu(
            parent, values=values, font=FONT_UI_S, fg_color=BG_INPUT, button_color=BG_INPUT,
            button_hover_color=BG_ELEVATED, text_color=TEXT, dropdown_font=FONT_UI_S,
            dropdown_fg_color=BG_ELEVATED, dropdown_text_color=TEXT, height=32, corner_radius=8,
        )
        m.set(default)
        return m

    def _browse_cookies(self):
        p = filedialog.askopenfilename(title="Cookies", initialdir=str(DOWNLOAD_DIR),
                                       filetypes=[("txt", "*.txt"), ("Tous", "*.*")])
        if p:
            self.cookies_file_entry.delete(0, "end")
            self.cookies_file_entry.insert(0, p)

    def _open_folder(self):
        try:
            subprocess.run(["open", str(DOWNLOAD_DIR)])
        except Exception as e:
            self._log_insert(f"open: {e}\n", "error")

    def _update_ytdlp(self):
        def _do():
            self.after(0, lambda: self._log_insert("\n$ brew upgrade yt-dlp\n", "accent"))
            r = subprocess.run(["brew", "upgrade", "yt-dlp"], capture_output=True, text=True)
            output = r.stdout or r.stderr or "done\n"
            self.after(0, lambda: self._log_insert(output, "dim"))
            self._fetch_version()
        threading.Thread(target=_do, daemon=True).start()

    def _fetch_version(self):
        try:
            v = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=5).stdout.strip()
            self.after(0, lambda: self.ver_lbl.configure(text=f"yt-dlp {v}"))
        except Exception:
            self.after(0, lambda: self.ver_lbl.configure(text="yt-dlp ✗", text_color=ERROR))


if __name__ == "__main__":
    App().mainloop()
