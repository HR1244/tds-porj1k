#!/usr/bin/env bash
# Ensure Render's virtual environment is in the PATH
export PATH="/opt/render/project/src/.venv/bin:$HOME/.local/bin:$PATH"

# Start the server
uvicorn bot:app --host 0.0.0.0 --port $PORT
