import os
import requests
import time
from flask import Flask
from threading import Thread

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8768676919:AAFbHfcNAU_x899JeIIiduOBKEdj1xHw404")
CHAT_ID = os.environ.get("CHAT_ID", "-5191938939")

app = Flask(__name__)

WATCHLIST = {}
SENT = set()

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/"
})

api_session = requests.Session()
api_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/"
})


# ================= FLASK KEEP ALIVE =================
@app.route("/")
def home():
    return "Bot is LIVE"


def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


# ================= TELEGRAM =================
def send_telegram(msg):
    for attempt in range(3):
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            r = requests.post(
                url,
                data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": "false"},
                timeout=10
            )
            if r.status_code != 200:
                print(f"Telegram Error (attempt {attempt+1}): {r.text[:200]}", flush=True)
            else:
                print("✅ Sent to Telegram", flush=True)
                return
        except Exception as e:
            print(f"Telegram Exception (attempt {attempt+1}): {e}", flush=True)
            time.sleep(2)


# ================= COIN FETCH (v3 API) =================
def get_coins():
    retries = 3
    delay = 2
    for attempt in range(retries):
        try:
            url = "https://frontend-api-v3.pump.fun/coins?offset=0&limit=50&sort=created_timestamp&order=DESC&includeNsfw=true"
            r = api_session.get(url, timeout=15)

            if r.status_code != 200:
                print(f"API status {r.status_code}, retrying...", flush=True)
                time.sleep(delay)
                delay *= 2
                continue

            text = r.text.strip()
            if not text or text.startswith("<"):
                print("API returned non-JSON, retrying...", flush=True)
                time.sleep(delay)
                delay *= 2
                continue

            data = r.json()
            return data if isinstance(data, list) else data.get("coins", [])

        except Exception as e:
            print(f"API error (attempt {attempt+1}/{retries}): {e}", flush=True)
            time.sleep(delay)
            delay *= 2

    return []


# ================= DETECT PUMP.FUN COMMUNITY CHAT =================
def has_community_chat(mint):
    """
    Fetches the pump.fun coin page and checks if it has a holders-only community chat.
    The 'Join chat' button is server-rendered in the HTML only when a community exists.
    """
    try:
        url = f"https://pump.fun/coin/{mint}"
        r = session.get(url, timeout=15, allow_redirects=True)
        if r.status_code == 200 and "Join chat" in r.text:
            return True
    except Exception as e:
        print(f"Community chat check error for {mint[:10]}...: {e}", flush=True)
    return False


# ================= BOT LOOP =================
def bot_loop():
    print("🔥 BOT LOOP STARTED", flush=True)
    send_telegram("🚀 Pump.fun community chat bot is LIVE — scanning for new coins with holders chats...")

    while True:
        try:
            coins = get_coins()
            now = time.time()

            if coins:
                print(f"👀 Scanning {len(coins)} coins...", flush=True)
            else:
                print("⚠️ No coins returned, retrying next cycle", flush=True)

            for c in coins:
                mint = c.get("mint")
                name = c.get("name", "Unknown")
                symbol = c.get("symbol", "")

                if not mint:
                    continue

                # Track new coins
                if mint not in WATCHLIST:
                    WATCHLIST[mint] = now
                    print(f"📌 New: {name} ({symbol}) | {mint[:12]}...", flush=True)

                # Track within 10-minute window
                if now - WATCHLIST[mint] > 600:
                    continue

                if mint in SENT:
                    continue

                # Check if coin has a pump.fun holders-only community chat
                if has_community_chat(mint):
                    SENT.add(mint)

                    msg = (
                        "🔥 <b>NEW PUMP.FUN COMMUNITY CHAT DETECTED</b>\n\n"
                        f"🪙 <b>{name}</b> (${symbol})\n"
                        f"📋 <b>CA:</b> <code>{mint}</code>\n\n"
                        f"💬 <b>Holders chat available — tap Join:</b>\n"
                        f"https://pump.fun/coin/{mint}"
                    )

                    print(f"💬 Community chat found: {name} ({symbol})", flush=True)
                    send_telegram(msg)

            time.sleep(8)

        except Exception as e:
            print(f"Loop crash: {e}", flush=True)
            time.sleep(5)


# ================= START =================
if __name__ == "__main__":
    print("🔥 SYSTEM STARTING", flush=True)

    Thread(target=run_flask, daemon=True).start()
    time.sleep(2)

    bot_loop()
