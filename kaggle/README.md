# Kaggle C++ worker

## GitHub-side deployment credentials
The queue workflow reads the GitHub Actions secrets `KAGGLE_USER_NAME` and `KAGGLE_KEY`. It installs the Kaggle CLI and pushes the persistent GPU notebook.

## Start
1. Add GitHub Actions secrets `KAGGLE_KEY` and `KAGGLE_USER_NAME`.
2. Submit a music request through the Pages frontend. The issue-intake workflow validates it, labels it `queued`, and dispatches the Kaggle queue workflow.
3. GitHub Actions pushes `kaggle/notebook/worker.ipynb` to Kaggle with GPU and Internet enabled.

## ACE-Step runtime
The notebook no longer compiles ACE-Step from source. It checks the NVIDIA GPU, clones the matching `pwilkin/acestep.cpp` v0.1.2 source tree (without submodules, for its model-download script), downloads the published Linux x64 CUDA release, verifies its pinned SHA-256, and extracts the prebuilt `ace-server` and shared libraries into `/kaggle/working/acestep.cpp/build`.

Release asset:
`acestep-cuda-linux-x64.tar.gz`

Pinned SHA-256:
`2f06f56d5fb0ab1a5eaa59f02133d5b9f83205cb4d36db11cc66fa2367c2d33d`

Before starting the worker, the notebook checks shared-library dependencies with `ldd` and runs `ace-server --help`. Model weights are downloaded separately with `models.sh --lm 4B --quant Q8_0`; they are not included in the binary release.

## Model choices
- LM: 4B Q8_0.
- DiT: Turbo Q8_0 (8 inference steps).
- GPU: CUDA0 (first T4).

The persistent HTTP server is started with `--keep-loaded`. It handles the queue through the public GitHub Issues API; GitHub Actions handles authenticated issue updates and Release uploads.

Kaggle sessions are not guaranteed to stay online. Queued Issues remain pending until the notebook worker is started again.
