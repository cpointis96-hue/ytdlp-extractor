# YouTube Subtitle Robustness Implementation Plan

> **For agentic workers:** This plan was executed inline in the current workspace.

**Goal:** Make selected YouTube subtitle downloads sequential, rate-limit aware, cancellable, and observable without changing the existing visual direction or video/audio behavior.

**Architecture:** Keep the existing single-file architecture. Persist job outcomes in `Store`, centralize subtitle options in `YtDlpRunner`, and enforce the inter-item delay in `QueueWorker`. Use yt-dlp's native HTTP retry backoff for each active subtitle process.

**Tech Stack:** Python, CustomTkinter, SQLite, yt-dlp 2026.08.19.

**Spec:** User request in the task conversation.

## Global Constraints

- Scan channels with `--flat-playlist -j`.
- Process selected subtitle URLs sequentially.
- Do not enable browser cookies automatically.
- Preserve video, audio, quality, naming, destination, and existing subtitle format behavior.
- Do not test a full 500-video channel.

### Task 1: Harden the subtitle command

**Files:**
- Modify: `ytdlp_extractor.py`

- [x] Add `--no-overwrites` to prevent unnecessary rewrites.
- [x] Keep manual and automatic subtitle flags and the selected language.
- [x] Add yt-dlp native `--retry-sleep http:exp=5:120`.
- [x] Keep `--sleep-subtitles 2` for requests within one job.

### Task 2: Make the persistent queue observable and cancellable

**Files:**
- Modify: `ytdlp_extractor.py`

- [x] Persist outcome metadata without overwriting job options.
- [x] Add `waiting`, `retrying`, and `cancelled` queue states.
- [x] Cancel queued jobs when Stop is pressed.
- [x] Terminate the active process group and escalate to SIGKILL only if needed.

### Task 3: Pace selected subtitle jobs

**Files:**
- Modify: `ytdlp_extractor.py`

- [x] Add a randomized 8 to 15 second delay between subtitle jobs.
- [x] Interrupt the delay when the queue is cancelled.
- [x] Leave audio and video jobs on their existing timing path.

### Task 4: Validate

**Files:**
- Modify: `README.md`, `main.py`

- [x] Compile the application with the project virtual environment.
- [x] Verify generated commands for audio, video, and subtitles.
- [x] Verify process-group cancellation with a controlled subprocess.
- [x] Run a bounded public YouTube test with 20 entries.
- [x] Document the verified behavior and the GUI accessibility limitation.
