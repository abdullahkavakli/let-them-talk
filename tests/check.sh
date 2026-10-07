#!/bin/sh
# Runs the checks: the server's (plain Python) and the page's (a headless
# browser from tests/.venv; tests/setup.sh installs it once, in this checkout
# or the main one, which worktrees use too). Exits 1 only when a check fails;
# a missing setup or a browser that won't start is reported and skipped, so it
# never blocks a push by itself.
cd "$(dirname "$0")/.." || exit 0
status=0
python3 -I tests/check_server.py || status=1
py=tests/.venv/bin/python
[ -x "$py" ] || py="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)")/tests/.venv/bin/python"
if [ -x "$py" ]; then
  "$py" -I tests/check_page.py
  [ $? -eq 1 ] && status=1
else
  echo "page checks skipped: run tests/setup.sh once to install them"
fi
exit $status
