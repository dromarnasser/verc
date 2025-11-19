#!/bin/bash
set -e

pip install -r requirements.txt

# Bind to $PORT env var (Railway sets this)
gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --preload
