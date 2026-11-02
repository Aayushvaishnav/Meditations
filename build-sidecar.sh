#!/bin/bash
# Build the Python backend into the Tauri sidecar bundle (one-dir, fast
# startup). Required before `npm run tauri build|dev` with the packaged
# backend; CI runs the same steps inside the release workflow.
set -e
cd "$(dirname "$0")/backend"
uv sync --locked --python 3.12 --group packaging
uv run --locked --no-sync pyinstaller sidecar.spec --clean --noconfirm --distpath ../frontend/src-tauri/binaries
echo "sidecar ready: frontend/src-tauri/binaries/meditations-backend/"
