#!/usr/bin/env bash
# Chạy web gán nhãn VoC
set -euo pipefail
cd "$(dirname "$0")"

ROOT="$(cd .. && pwd)"
PY="$ROOT/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "Chưa có môi trường ảo. Chạy trước:" >&2
  echo "  cd \"$ROOT\"" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  echo >&2
  echo "Đang thử dùng python3 hệ thống..." >&2
  PY=python3
fi

exec "$PY" -m uvicorn app:app --host 127.0.0.1 --port "${PORT:-8765}"
