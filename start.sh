#!/bin/bash
# Updated start.sh for unified app.py
# Use 1 worker to ensure only one instance of the Telegram bot runs via the background thread.
exec gunicorn --workers 1 --threads 4 --timeout 60 --bind 0.0.0.0:$PORT app:app
