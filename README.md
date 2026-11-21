# Kaggle Music Generator

GitHub Pages frontend + GitHub Issues queue + Kaggle ACE-Step worker + GitHub Releases output storage.

## Flow
1. Pages creates an Issue containing a versioned JSON music request.
2. GitHub Actions validates the request and labels it queued.
3. A running Kaggle notebook polls the Issues queue and claims a job.
4. Kaggle generates audio with ACE-Step and uploads it as a GitHub Release asset.
5. Kaggle posts the download URL to the Issue; Pages displays the result.

## Layout
- docs/: GitHub Pages frontend.
- .github/workflows/: issue intake automation.
- kaggle/: Kaggle worker.
- protocol/: versioned request format.

## Setup
1. Publish the main branch /docs folder in Settings > Pages.
2. Create a fine-grained GitHub token scoped to this repository with Issues read/write and Contents write permissions.
3. Store the token as a Kaggle Notebook Secret named GITHUB_TOKEN. Never commit it or put it in frontend code.
4. Install ACE-Step in a Kaggle notebook and run kaggle/worker.py after connecting its generation adapter to the exact ACE-Step version.
5. Open the Pages site and enter a repository-scoped token in the connection field. The page keeps it in memory only.

## Important
Kaggle notebooks are not guaranteed always-on servers. Sessions can be stopped by Kaggle limits or inactivity. Pending jobs remain in Issues while the worker is offline.
The worker's ACE-Step adapter is deliberately isolated: its exact Python inference API must be connected and tested against the selected model/runtime before audio generation works.
GitHub Releases have storage and upload constraints. The initial design stores one audio asset per job.

See protocol/job-v1.json for the request schema.