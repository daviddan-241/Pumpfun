# Pump.fun Coin Monitor Bot

## Overview
A Python bot that monitors new coin listings on pump.fun, verifies if they have an associated chat, and sends notifications to a Telegram channel/chat when a verified coin is found.

## Architecture
- **Language:** Python 3.12
- **Web Framework:** Flask (keep-alive web server on port 5000)
- **Concurrency:** Threading (Flask server + bot loop run simultaneously)
- **External APIs:** pump.fun API, Telegram Bot API

## Key Files
- `main.py` - Main application: Flask keep-alive server + bot monitoring loop
- `requirements.txt` - Python dependencies (Flask, Werkzeug, requests, gunicorn)
- `Procfile` / `procfile` - Deployment run commands

## Configuration
The bot requires a valid Telegram bot token and chat ID configured in `main.py`:
- `BOT_TOKEN` - Telegram bot token (line 9)
- `CHAT_ID` - Telegram chat/channel ID (line 10)

## How It Works
1. Flask server runs on port 5000 as a keep-alive endpoint
2. Bot loop polls the pump.fun API every 8 seconds for new coins
3. For each new coin, it checks if a valid pump.fun chat exists (double-verified)
4. If a verified chat is found, sends a Telegram notification with coin details
5. Coins are tracked for 5 minutes in a watchlist to avoid repeated checks

## Running
The app starts with `python main.py`, which launches both the Flask server (port 5000) and the bot loop via threading.

## Deployment
Configured as a VM deployment (always-running) since the bot needs to maintain persistent state (WATCHLIST, SENT sets) and run continuously.
