import os
import requests
import time
import re
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Connection": "keep-alive",
    "Accept-Encoding": "gzip, deflate, br",
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
    for attempt in range(3):  # Retry sending
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            r = session.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)

            if r.status_code != 200:
                print(f"Telegram Error (attempt {attempt+1}):", r.text[:200], flush=True)
            else:
                return  # Stop retrying after a successful send

        except Exception as e:
            print(f"Telegram Exception (attempt {attempt+1}):", e, flush=True)
            time.sleep(2)  # Small delay before retry


# ================= SAFE COIN FETCH =================
def get_coins():
    retries = 3
    delay = 2  # Start with 2 seconds
    for attempt in range(retries):
        try:
            url = "https://frontend-api.pump.fun/coins?offset=0&limit=50&sort=created_timestamp&order=desc"
            r = session.get(url, timeout=10)

            if r.status_code != 200:
                print("API blocked (status):", r.status_code, flush=True)
                time.sleep(delay)
                delay *= 2  # Exponential backoff
                continue

            text = r.text.strip()
            if not text or text.startswith("<"):
                print("API returned non-JSON (blocked or HTML)", flush=True)
                time.sleep(delay)
                delay *= 2
                continue

            return r.json()

        except Exception as e:
            print(f"API error (attempt {attempt + 1}/{retries}):", e, flush=True)
            time.sleep(delay)
            delay *= 2

    print("API requests failed after retries", flush=True)
    return []


# ================= CHAT DETECTOR =================
def get_chat(mint):
    try:
        url = f"https://pump.fun/{mint}"
        r = session.get(url, timeout=10)

        html = r.text.lower()

        if "chat" not in html:
            return None

        match = re.search(r"https://pump\.fun/chat/[a-zA-Z0-9]+", r.text)
        if match:
            return match.group(0)

    except Exception as e:
        print("Chat error:", e, flush=True)

    return None


# ================= VERIFY CHAT =================
def verify_chat(mint):
    first = get_chat(mint)
    if not first:
        return None

    time.sleep(0.5)

    second = get_chat(mint)

    if first and second:
        return second

    return None


# ================= BOT LOOP =================
def bot_loop():
    print("🔥 BOT LOOP STARTED", flush=True)
    send_telegram("🚀 Pump.fun bot LIVE (stable mode)")

    while True:
        try:
            coins = get_coins()
            now = time.time()

            print(f"👀 scanning {len(coins)} coins", flush=True)

            for c in coins:
                mint = c.get("mint")
                name = c.get("name", "Unknown")

                if not mint:
                    continue

                # track new coins
                if mint not in WATCHLIST:
                    WATCHLIST[mint] = now
                    print(f"👀 Tracking new coin: {name} with CA: {mint}", flush=True)

                # 5-minute time window for active tracking
                if now - WATCHLIST[mint] > 300:
                    continue

                if mint in SENT:
                    continue

                # Verify if the coin has a valid Pump.fun chat
                chat = verify_chat(mint)

                if chat:
                    SENT.add(mint)

                    msg = (
                        "🚨 VERIFIED PUMP.FUN COIN WITH CHAT\n\n"
                        f"Name: {name}\n"
                        f"Contract Address: {mint}\n\n"
                        f"💬 Chat:\n{chat}\n\n"
                        f"https://pump.fun/{mint}"
                    )

                    print(f"💬 SENT TO TELEGRAM: {name}", flush=True)
                    send_telegram(msg)

            time.sleep(8)

        except Exception as e:
            print("Loop crash:", e, flush=True)
            time.sleep(5)


# ================= START =================
if __name__ == "__main__":
    print("🔥 SYSTEM STARTING", flush=True)

    Thread(target=run_flask, daemon=True).start()
    time.sleep(2)

    bot_loop()