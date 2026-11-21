# Kaggle C++ worker

## GitHub-side deployment credentials
The deployment workflow reads `KAGGLE_USER_NAME` and `KAGGLE_KEY`. It installs `six` explicitly before the Kaggle CLI to avoid the missing-six import failure.

## Secret required inside Kaggle
Create a Kaggle Notebook Secret named `GITHUB_TOKEN`. It must be a fine-grained GitHub token limited to this repository with Issues read/write and Contents read/write. The token is used by the running worker to read/claim Issues, create Releases, upload audio, and post results.

## Start
1. Add GitHub Actions secrets `KAGGLE_KEY` and `KAGGLE_USER_NAME`.
2. Add the Kaggle Notebook Secret `GITHUB_TOKEN`.
3. Run the Deploy Kaggle worker notebook workflow.
4. Open the deployed notebook and run all cells with GPU and Internet enabled.

The notebook clones and builds `ServeurpersoCom/acestep.cpp` with CUDA, downloads the Q8_0 Turbo model set, and starts the Issues worker.

## Model choices
- LM: 4B Q8_0 for higher quality.
- DiT: Turbo Q8_0 (8 inference steps).
- Text encoder: Qwen3 Embedding 0.6B Q8_0.
- VAE: BF16.
- GPU: CUDA0 (first T4).

The C++ CLI is invoked as two stages per job: `ace-lm` creates the enriched request and audio codes; `ace-synth` renders the MP3. The compiled binaries and downloaded model files stay on disk for the life of the Kaggle session. The CLI processes are started for each song, so model weights are loaded again for a new job.

Kaggle sessions are not guaranteed to stay online. Queued Issues remain pending until the notebook worker is started again.
