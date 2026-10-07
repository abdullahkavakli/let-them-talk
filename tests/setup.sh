#!/bin/sh
# Once: a Python venv in tests/.venv with Playwright and its headless Chromium,
# for the page checks (tests/check_page.py). About 150 MB, outside git.
cd "$(dirname "$0")" || exit 1
python3 -m venv .venv &&
  .venv/bin/pip install --quiet playwright &&
  .venv/bin/python -m playwright install chromium &&
  echo "Done. Run the checks with: tests/check.sh"
