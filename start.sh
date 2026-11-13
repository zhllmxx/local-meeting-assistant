#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
"$ROOT/install-services.sh"

echo "Local meeting assistant: http://127.0.0.1:8766"
echo "Using Doubao ASR and Doubao LLM; their configuration status appears in the page."
