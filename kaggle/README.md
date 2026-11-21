# Kaggle worker

## GitHub-side deployment credentials
The repository workflow reads the GitHub Actions secrets KAGGLE_USER_NAME and KAGGLE_KEY to deploy this notebook through the Kaggle CLI.

## Secret required inside Kaggle
Create a Kaggle Notebook Secret named GITHUB_TOKEN. It must be a fine-grained GitHub token limited to this repository with Issues read/write and Contents read/write. The token is used only by the running worker to read/claim Issues, create Releases, upload audio, and post results.

## Start
1. Add both GitHub Actions secrets.
2. Run the Deploy Kaggle worker notebook workflow (or push a change under kaggle/).
3. Open the deployed Kaggle notebook and add the GITHUB_TOKEN notebook secret.
4. Enable GPU and Internet, then run all cells.

The notebook uses ACE-Step 1.5 Turbo DiT + 0.6B LM, initializes them once, and processes one queued issue at a time. The default LM backend is pt for compatibility. The first run downloads model weights and installs dependencies; later runs may still need to reload weights if Kaggle has reset the session.

Kaggle sessions are not guaranteed always-on. Pending requests stay in GitHub Issues until the worker is running again.
