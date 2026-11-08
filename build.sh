#!/usr/bin/env bash
set -euo pipefail

# Activate virtual environment if present
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
fi

pip install pyinstaller --quiet

# Data entry tool
pyinstaller --onefile --name tarockmanager \
    --collect-all tarock_core \
    tarockmanager.py

# Presentation tool (needs the images folder for the Walter page)
pyinstaller --onefile --name presenter \
    --hidden-import "matplotlib.backends.backend_qtagg" \
    --hidden-import "matplotlib.backends.backend_agg" \
    --collect-all matplotlib \
    --collect-all tarock_core \
    --add-data "images:images" \
    presenter.py

echo "Done - binaries: dist/tarockmanager, dist/presenter"
