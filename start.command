#!/bin/bash
# macOS: double-click to start the annotation site (Linux: ./start.command).
cd "$(dirname "$0")" || exit 1

for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 &&
     "$py" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then
    "$py" server.py "$@"
    status=$?
    [ $status -ne 0 ] && read -r -p "Press Enter to close this window."
    exit $status
  fi
done

echo "Python 3.8 or newer was not found."
echo "Install it from https://www.python.org/downloads/ , then double-click start.command again."
read -r -p "Press Enter to close this window."
exit 1
