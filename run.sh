#!/bin/bash

# --- User Configuration ---
CONDA_ENV_NAME="fantasy-agent"
PATH_TO_CONDA_BASE="$HOME/miniconda3"


# --- Activation ---
echo "Initializing Conda..."

# This is the standard way to make 'conda' available in a script
source "$PATH_TO_CONDA_BASE/etc/profile.d/conda.sh"
if [ $? -ne 0 ]; then
    echo "Error: Could not source conda.sh. Is your PATH_TO_CONDA_BASE correct?"
    echo "Current path set to: $PATH_TO_CONDA_BASE"
    exit 1
fi

echo "Activating Conda environment: $CONDA_ENV_NAME"
conda activate "$CONDA_ENV_NAME"
if [ $? -ne 0 ]; then
    echo "Error: Could not activate conda environment '$CONDA_ENV_NAME'."
    echo "Please make sure this environment name is correct."
    exit 1
fi

echo "Running data pipeline to get new data..."
python download_pipeline.py

echo "Starting Fantasy Dashboard..."
streamlit run dashboard.py

# Deactivate when done (optional, good practice)
conda deactivate