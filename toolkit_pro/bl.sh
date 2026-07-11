#!/bin/bash
# Run a toolkit Blender script headless: bash bl.sh <script.py> [args...]
set -e
BL=$(which blender 2>/dev/null || true)
[ -z "$BL" ] && BL=$(ls -d ~/Downloads/blender-*/blender 2>/dev/null | head -1)
[ -z "$BL" ] && { echo "blender not found" >&2; exit 1; }
SCRIPT="$1"; shift
exec "$BL" -b --factory-startup -P "$SCRIPT" -- "$@" 2>&1 | grep -vE "^(Read|Blender [0-9]|Color management|glTF import|Draw|Warn:|Info:|Fra:|Saved:|Time:|.*INFO:)" | grep -v "^$"
