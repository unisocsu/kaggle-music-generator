# Kaggle Music Generator

GitHub Pages frontend + GitHub Issues queue + Kaggle ACE-Step worker + GitHub Releases output storage.

## Flow
1. Pages creates an Issue containing a versioned JSON music request.
2. GitHub Actions validates the request and labels it queued.
3. A running Kaggle notebook polls the Issues queue and claims a job.
4. Kaggle generates audio with ACE-Step and uploads it as a GitHub Release asset.
5. Kaggle posts the download URL to the Issue; Pages displays the result.

## Setup

### GitHub Actions repository secrets
Create these two secrets exactly:
- KAGGLE_KEY
- KAGGLE_USER_NAME

They authenticate the Kaggle CLI so GitHub Actions can publish the notebook in kaggle/notebook. The usual Kaggle CLI variable is KAGGLE_USERNAME, but this workflow writes the expected kaggle.json fields using your chosen secret name KAGGLE_USER_NAME.

### Kaggle Notebook Secret
After the notebook is deployed, add a Kaggle Notebook Secret named GITHUB_TOKEN. Use a fine-grained GitHub token scoped only to this repository, with Issues read/write and Contents read/write permissions. Contents write is required to create Releases and upload audio assets. Never commit this token or put it in the Pages frontend.

### Publish Pages
In Settings > Pages, choose Deploy from a branch, branch main, folder /docs.

### Deploy and run
Push changes under kaggle/ or run Actions > Deploy Kaggle worker notebook > Run workflow. Open the Kaggle notebook named kaggle-music-generator-worker, make sure GPU and Internet are enabled, then run all cells.

The notebook installs ACE-Step 1.5, loads the Turbo DiT and 0.6B LM once, then polls GitHub Issues. Kaggle sessions are not guaranteed to stay online; queued Issues remain pending while the worker is offline.

## Model settings
- DiT: acestep-v15-turbo
- LM: acestep-5Hz-lm-0.6B
- Inference: 8 steps, ODE, one queued job at a time
- LM backend defaults to pt for compatibility. Change ACESTEP_LM_BACKEND to vllm only after verifying that backend works in the selected Kaggle image.
- Two T4 GPUs do not automatically combine their VRAM. This initial worker uses one GPU.
- ACE-Step 1.5 requires Python 3.11–3.12; the notebook creates a Python 3.12 environment.

## Layout
- docs/: GitHub Pages frontend.
- .github/workflows/: issue intake and Kaggle deployment automation.
- kaggle/worker.py: queue polling, ACE-Step inference, and Release upload.
- kaggle/notebook/: deployable Kaggle notebook and metadata.
- protocol/: versioned request format.
