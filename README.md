# Kaggle Music Generator

GitHub Pages frontend + GitHub Issues queue + GitHub Actions orchestrator + a long-lived Kaggle GPU session + GitHub Releases for MP3 output. The engine is ServeurpersoCom/acestep.cpp.

## Architecture

1. Pages creates a public GitHub Issue containing a versioned JSON music request.
2. GitHub Actions validates the request and applies the queued label.
3. GitHub Actions starts one Kaggle notebook run using Kaggle CLI.
4. The Kaggle notebook downloads the Q8_0 models and starts one long-lived ace-server process. The frontend can start an idle engine session explicitly, before any song is submitted.
5. During the active run, Kaggle checks public Issues anonymously for new queued requests. It prints machine-readable log events such as KAGGLE_SEEN:123, KAGGLE_DONE:123, KAGGLE_PUBLISHED:123:<url>, and KAGGLE_FAILED:123.
6. GitHub Actions follows live Kaggle logs with kaggle kernels logs --follow. When it sees KAGGLE_SEEN, it adds the processing label and comments that the request was received.
7. After each MP3 is generated, the Kaggle worker immediately uploads it to its GitHub Release using a private token stored in Kaggle Secrets. GitHub Actions sees KAGGLE_PUBLISHED, records the download URL, marks the Issue completed, and closes it while the Kaggle engine remains active for more songs.
8. When the session eventually ends, Actions downloads the notebook outputs as a recovery path. It detects assets already uploaded live and does not upload duplicates.

Kaggle reads public Issues anonymously and uses the private Kaggle Secret only to create/upload Release assets. GitHub Actions handles issue comments, labels, result URLs, and closing Issues.

## Required repository Actions secrets

- KAGGLE_KEY — Kaggle API access token.
- KAGGLE_USER_NAME — Kaggle username.

Also add a Kaggle notebook Secret named `GITHUB_TOKEN` containing a fine-grained GitHub token restricted to this repository, with **Contents: Read and write** permission. This is used only by the Kaggle worker to upload MP3 Release assets immediately after generation. Do not put the token in the notebook source, Issue body, or chat. GitHub Actions continues to use its automatically provided `github.token` for issue comments, labels, result URLs, and closing Issues.

## GitHub Pages

In Settings > Pages, choose Deploy from a branch, branch main, folder /docs.

The frontend stores the user's GitHub token in browser localStorage and uses it directly for GitHub Issues API calls. The token is not sent to Kaggle. Use a fine-grained token restricted to this repository with Issues read/write permission. Anyone with access to this browser profile can access the saved token; use the disconnect button to remove it.

## Run

1. Set KAGGLE_KEY and KAGGLE_USER_NAME in repository Actions secrets.
2. In the Kaggle notebook settings, add and enable a Secret named `GITHUB_TOKEN` with a fine-grained token that has Contents read/write access to this repository.
3. Enable GitHub Actions and Pages.
4. Submit a song from Pages, or manually run Actions > Run queued music jobs on Kaggle.
5. While the Kaggle session is active, newly queued Issues are picked up automatically. Each MP3 is published immediately; the session remains available for additional songs.
6. A 10-minute schedule is included as a recovery trigger if an earlier Actions event was missed.

The workflow is serialized so only one Kaggle GPU session is submitted at a time. New workflow events that arrive during a session are handled by the already-running Kaggle poller.

## Persistent ACE-Step server

The notebook builds ace-server and starts it with:

- Device CUDA0
- Default memory policy; model components load as needed
- Host 127.0.0.1, port 8085

The server exposes asynchronous /lm and /synth endpoints and a FIFO job queue. The session worker polls each job status and fetches its result. This keeps the model store alive in one process across song requests, instead of starting ace-lm and ace-synth for every song.

The server process remains alive between requests, while model components are loaded according to the server's default memory policy. This avoids restarting the full engine process for each song without forcing all components to remain resident in VRAM. Kaggle controls session availability and runtime limits; it may terminate a session earlier.

## Models and generation

- LM: acestep-5Hz-lm-4B-Q8_0.gguf
- DiT: acestep-v15-turbo-Q8_0.gguf (8-step Turbo)
- Text encoder: Qwen3 Embedding 0.6B Q8_0
- VAE: BF16
- Target device: CUDA0
- Audio output: MP3, 192 kbps
- Requests are serialized by the ACE-Step server FIFO worker thread.
- Completed MP3 files are uploaded to GitHub Releases immediately from Kaggle; end-of-session output collection remains as a recovery path.

The Q8_0 essentials model set is approximately 7.7 GB on disk. The server process stays alive between requests, but its default memory policy is retained to avoid forcing all model components to remain resident in T4 VRAM.

## Layout

- docs/: Chat-style GitHub Pages frontend with local token persistence, recent-song sidebar, and an explicit Start Engine control.
- .github/workflows/issue-intake.yml: validates and queues new requests.
- .github/workflows/run-kaggle-job.yml: starts Kaggle, follows live logs, downloads MP3s and publishes releases.
- kaggle/notebook/: Kaggle notebook template and metadata.
- kaggle/session_worker.py: anonymous Issues poller, engine-start control handler, and ACE-Step HTTP API client.
- kaggle/worker.py: previous one-shot CLI worker, retained for reference.
- scripts/process_kaggle_queue.py: GitHub Actions session manager and Release publisher.
