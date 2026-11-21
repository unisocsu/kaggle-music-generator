# Kaggle worker setup

1. Create a Kaggle Notebook with GPU enabled and install the chosen ACE-Step 1.5 revision.
2. Add a Kaggle Notebook Secret named GITHUB_TOKEN. Use a fine-grained token restricted to this repository with Issues read/write and Contents write (release creation and asset upload).
3. Run worker.py in the notebook after setting GITHUB_REPOSITORY if needed.
4. Connect generate_audio(job, output_path) to the exact ACE-Step Python inference interface installed in the notebook.
5. Initialize/load the model once before starting the polling loop. Do not reload it for every Issue.

The adapter is intentionally a stub until the actual ACE-Step notebook/runtime version is selected. Kaggle sessions are not guaranteed to remain online indefinitely.