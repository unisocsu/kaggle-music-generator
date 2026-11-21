# Kaggle Music Generator

GitHub Pages frontend + GitHub Issues queue + GitHub Actions orchestrator + Kaggle GPU worker + GitHub Releases for MP3 output. The engine is ServeurpersoCom/acestep.cpp built with CUDA.

## Architecture

1. Pages creates an Issue containing a versioned JSON music request.
2. GitHub Actions validates the request and labels it queued.
3. GitHub Actions reads queued Issues using its automatically provided token.
4. Actions injects one request into the notebook source and runs kaggle kernels push.
5. Kaggle builds/runs ACE-Step, generates one MP3, and exposes it as kernel output.
6. Actions checks kaggle kernels status, downloads the MP3 with kaggle kernels output, uploads it to a GitHub Release, comments the result URL, and closes the Issue.

Kaggle does not receive or need a GitHub token. GitHub credentials remain on the Actions runner.

## GitHub Actions repository secrets

- KAGGLE_KEY — Kaggle API access token.
- KAGGLE_USER_NAME — Kaggle username.

No GITHUB_TOKEN Kaggle Notebook Secret is required. The workflow uses the automatically provided github.token to read Issues and publish Release assets. The workflow installs six explicitly before Kaggle CLI.

## GitHub Pages

In Settings > Pages, choose Deploy from a branch, branch main, folder /docs.

The current static frontend still asks the user to enter a fine-grained GitHub token to create Issues directly through GitHub's API. This token is not sent to Kaggle. Removing the frontend token requires a server-side submission endpoint such as a Cloudflare Worker.

## Run

1. Set KAGGLE_KEY and KAGGLE_USER_NAME in repository Actions secrets.
2. Enable GitHub Actions and Pages.
3. Submit a song from Pages, or manually run Actions > Run queued music jobs on Kaggle.
4. The workflow drains queued Issues in creation order. A 10-minute schedule is included as a fallback.

The queue is serialized so only one Kaggle GPU job is submitted at a time.

## Kaggle notebook behavior

Each request creates a new Kaggle kernel execution. The notebook:
- Installs the C++/CUDA build toolchain and hf downloader.
- Clones ServeurpersoCom/acestep.cpp with its submodules.
- Builds CUDA code for NVIDIA T4 (compute capability 7.5).
- Downloads the Q8_0 Turbo model set.
- Runs one job and saves the MP3 under /kaggle/working/output/.

Because Kaggle starts a fresh execution per job, the engine build and model downloads may repeat for every song. This avoids a long-running polling notebook and removes GitHub credentials from Kaggle, but increases cold-start time. Kaggle controls session availability and runtime limits.

## Model and inference settings

- LM: acestep-5Hz-lm-4B-Q8_0.gguf.
- DiT: acestep-v15-turbo-Q8_0.gguf (8-step Turbo).
- Text encoder: Qwen3 Embedding 0.6B Q8_0.
- VAE: BF16.
- Target device: CUDA0.
- Audio output: MP3, 192 kbps.
- Jobs are sequential.

The stated model download size is approximately 7.7 GB. Kaggle's dual T4 accelerator does not automatically combine both GPUs into one memory pool; this notebook targets the first CUDA device.

## Layout

- docs/: GitHub Pages frontend.
- .github/workflows/issue-intake.yml: validates and queues new requests.
- .github/workflows/run-kaggle-job.yml: orchestrates Kaggle CLI and publishes outputs.
- scripts/prepare_kaggle_notebook.py: injects a per-job request into the notebook.
- scripts/process_kaggle_queue.py: queue manager on GitHub Actions.
- kaggle/worker.py: one-shot C++ inference, no GitHub API or token.
- kaggle/notebook/: Kaggle notebook template and metadata.
- protocol/: versioned request format.
