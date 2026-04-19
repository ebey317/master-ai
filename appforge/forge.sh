#!/bin/bash
# AppForge launcher — run from anywhere.
exec python3 "$(dirname "$(readlink -f "$0")")/forge.py" "$@"
