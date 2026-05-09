#!/bin/bash

# Start the Telegram bot in the background
echo "Starting Telegram Bot..."
python bot.py &

# Start the Flask web application with Gunicorn
echo "Starting Web Application..."
gunicorn webapp:app --bind 0.0.0.0:$PORT
