#!/usr/bin/env bash
set -euo pipefail

# Activate virtual environment if present
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
fi

pip install pyinstaller --quiet

pyinstaller \
    --onefile \
    --name tarock \
    --hidden-import "matplotlib.backends.backend_qtagg" \
    --hidden-import "matplotlib.backends.backend_agg" \
    --collect-all matplotlib \
    tarockmanager.py

echo "Done — binary: dist/tarock"
