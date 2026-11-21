# Kaggle Music Generator

GitHub Pages frontend + GitHub Issues queue + Kaggle GPU worker + GitHub Releases output storage. The generation engine is **ServeurpersoCom/acestep.cpp**, built with CUDA for Kaggle NVIDIA GPUs.

## Flow
1. Pages creates an Issue containing a versioned JSON music request.
2. GitHub Actions validates the request and labels it `queued`.
3. The running Kaggle notebook polls Issues and claims one job at a time.
4. The C++ pipeline runs `ace-lm` followed by `ace-synth` on `CUDA0`.
5. The worker uploads the MP3 to a GitHub Release, comments the result URL, and closes the Issue.

## Setup

### GitHub Actions repository secrets
Create these two secrets exactly:
- `KAGGLE_KEY`
- `KAGGLE_USER_NAME`

The deploy workflow explicitly installs `six` before installing/running Kaggle CLI.

### Kaggle Notebook Secret
Add a Kaggle Notebook Secret named `GITHUB_TOKEN`. Use a fine-grained token scoped only to this repository with Issues read/write and Contents read/write permissions. Contents write is required to create Releases and upload audio assets. Never commit this token or put it in the Pages frontend.

### Publish Pages
In Settings > Pages, choose Deploy from a branch, branch `main`, folder `/docs`.

### Deploy and run
Push a change under `kaggle/` or run Actions > Deploy Kaggle worker notebook > Run workflow. Open the Kaggle notebook named `kaggle-music-generator-worker`, confirm GPU and Internet are enabled, add the `GITHUB_TOKEN` notebook secret, then run all cells.

The notebook:
- Installs the C++/CUDA build toolchain.
- Clones `ServeurpersoCom/acestep.cpp` with its submodules.
- Builds CUDA code for NVIDIA T4 (compute capability 7.5).
- Downloads the Q8_0 Turbo model set.
- Starts the Issues polling worker.

## Model and inference settings
- LM: `acestep-5Hz-lm-4B-Q8_0.gguf` (quality-oriented 4B model).
- DiT: `acestep-v15-turbo-Q8_0.gguf` (8-step Turbo).
- Text encoder: Qwen3 Embedding 0.6B Q8_0.
- VAE: BF16.
- Target device: `CUDA0`.
- Audio output: MP3, 192 kbps.
- Jobs are processed sequentially.

The default model download is approximately 7.7 GB. The two Kaggle T4 cards do not automatically combine into one device; this worker targets the first CUDA device. Kaggle sessions are not guaranteed to stay online, so queued Issues wait until the notebook worker is running again.

## Layout
- `docs/`: GitHub Pages frontend.
- `.github/workflows/`: Issue intake and Kaggle notebook deployment.
- `kaggle/worker.py`: Issue polling, C++ inference, and Release upload.
- `kaggle/notebook/`: deployable Kaggle notebook and metadata.
- `protocol/`: versioned request format.
