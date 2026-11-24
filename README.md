# Kaggle Music Generator

GitHub Pages frontend + GitHub Issues queue + GitHub Actions orchestrator + a long-lived Kaggle GPU session + GitHub Releases for MP3 output. The engine is ServeurpersoCom/acestep.cpp.

## Architecture

1. Pages creates a public GitHub Issue containing a versioned JSON music request.
2. GitHub Actions validates the request and applies the queued label.
3. GitHub Actions starts one Kaggle notebook run using Kaggle CLI.
4. The Kaggle notebook downloads the Q8_0 models and starts one long-lived ace-server process. The frontend can start an idle engine session explicitly, before any song is submitted.
5. During the active run, Kaggle checks public Issues anonymously for new queued requests. It prints machine-readable log events such as KAGGLE_SEEN:123, KAGGLE_DONE:123, and KAGGLE_FAILED:123.
6. GitHub Actions follows live Kaggle logs with kaggle kernels logs --follow. When it sees KAGGLE_SEEN, it adds the processing label and comments that the request was received.
7. The persistent ACE-Step HTTP server accepts /lm and /synth requests in sequence. Its keep-loaded mode retains model weights between requests.
8. The Kaggle session ends after 3 minutes with no new requests or after its session time budget. Actions downloads all generated MP3s, uploads each to a GitHub Release, comments the playback/download URL, marks the Issue completed, and closes it.

Kaggle performs only anonymous GET requests to public Issues. It does not receive a GitHub token and never writes to GitHub. All authenticated GitHub comments, labels, Releases, and issue updates are performed by GitHub Actions.

## Required repository Actions secrets

- KAGGLE_KEY — Kaggle API access token.
- KAGGLE_USER_NAME — Kaggle username.

The GitHub Actions workflow uses its automatically provided github.token for repository writes. No GitHub token is required in Kaggle Secrets.

## GitHub Pages

In Settings > Pages, choose Deploy from a branch, branch main, folder /docs.

The frontend stores the user's GitHub token in browser localStorage and uses it directly for GitHub Issues API calls. The token is not sent to Kaggle. Use a fine-grained token restricted to this repository with Issues read/write permission. Anyone with access to this browser profile can access the saved token; use the disconnect button to remove it.

## Run

1. Set KAGGLE_KEY and KAGGLE_USER_NAME in repository Actions secrets.
2. Enable GitHub Actions and Pages.
3. Submit a song from Pages, or manually run Actions > Run queued music jobs on Kaggle.
4. While the Kaggle session is active, newly queued Issues are picked up automatically. The session closes after 180 seconds without a new request.
5. A 10-minute schedule is included as a recovery trigger if an earlier Actions event was missed.

The workflow is serialized so only one Kaggle GPU session is submitted at a time. New workflow events that arrive during a session are handled by the already-running Kaggle poller.

## Persistent ACE-Step server

The notebook builds ace-server and starts it with:

- Device CUDA0
- keep-loaded enabled
- Host 127.0.0.1, port 8085

The server exposes asynchronous /lm and /synth endpoints and a FIFO job queue. The session worker polls each job status and fetches its result. This keeps the model store alive in one process across song requests, instead of starting ace-lm and ace-synth for every song.

The server loads model modules lazily on first use; after they have been loaded, keep-loaded retains them between requests. This increases VRAM use compared with the default eviction policy. Kaggle controls session availability and runtime limits; it may terminate a session earlier.

## Models and generation

- LM: acestep-5Hz-lm-4B-Q8_0.gguf
- DiT: acestep-v15-turbo-Q8_0.gguf (8-step Turbo)
- Text encoder: Qwen3 Embedding 0.6B Q8_0
- VAE: BF16
- Target device: CUDA0
- Audio output: MP3, 192 kbps
- Requests are serialized by the ACE-Step server FIFO worker thread.

The Q8_0 essentials model set is approximately 7.7 GB on disk. keep-loaded keeps loaded modules resident in GPU memory; verify actual memory use and successful first generation on the selected Kaggle accelerator before relying on long sessions.

## Layout

- docs/: Chat-style GitHub Pages frontend with local token persistence, recent-song sidebar, and an explicit Start Engine control.
- .github/workflows/issue-intake.yml: validates and queues new requests.
- .github/workflows/run-kaggle-job.yml: starts Kaggle, follows live logs, downloads MP3s and publishes releases.
- kaggle/notebook/: Kaggle notebook template and metadata.
- kaggle/session_worker.py: anonymous Issues poller, engine-start control handler, and ACE-Step HTTP API client.
- kaggle/worker.py: previous one-shot CLI worker, retained for reference.
- scripts/process_kaggle_queue.py: GitHub Actions session manager and Release publisher.
