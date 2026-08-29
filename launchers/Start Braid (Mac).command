#!/bin/bash
# Double-click this file to open Braid.
#
# The first time, macOS may say the file is from an unidentified developer.
# If that happens: right-click this file, choose Open, then click Open again.
# You only have to do that once.

cd "$(dirname "$0")/.." || exit 1

echo "Starting Braid…"
echo

find_python() {
  for candidate in python3 /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON="$(find_python)"

if [ -z "$PYTHON" ]; then
  echo "Braid needs Python 3.9 or newer, and none was found."
  echo
  echo "Every Mac normally ships with it. To install it, open Terminal and run:"
  echo "    xcode-select --install"
  echo
  echo "Then double-click this file again."
  echo
  read -r -p "Press Return to close this window. "
  exit 1
fi

export PYTHONPATH="$PWD/src:$PYTHONPATH"

if ! "$PYTHON" -m braid --version >/dev/null 2>&1; then
  echo "Could not start Braid from $PWD."
  echo "Make sure this file is still inside the folder you unzipped."
  echo
  read -r -p "Press Return to close this window. "
  exit 1
fi

echo "Braid is opening in your browser."
echo "Leave this window open while you use it. Close it to stop braid."
echo

"$PYTHON" -m braid serve

echo
read -r -p "Braid has stopped. Press Return to close this window. "
