import requests
import time
import re
from flask import Flask
from threading import Thread

# ================= CONFIG =================
BOT_TOKEN = "8710292892:AAFI3UJ8LXcekksJeWd39B5DJvo7FhGOvnE"
CHAT_ID = "5578314612"

app = Flask(__name__)

WATCHLIST = {}
SENT = set()

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0"
})


# ================= FLASK KEEP ALIVE =================
@app.route("/")
def home():
    return "Bot is running"


def run_flask():
    app.run(host="0.0.0.0", port=10000)


# ================= TELEGRAM =================
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = session.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)

        if r.status_code != 200:
            print("Telegram error:", r.text[:200], flush=True)

    except Exception as e:
        print("Telegram exception:", e, flush=True)


# ================= SAFE COIN FETCH (FIXED) =================
def get_coins():
    try:
        url = "https://frontend-api.pump.fun/coins?offset=0&limit=50&sort=created_timestamp&order=desc"
        r = session.get(url, timeout=10)

        # 🔥 IMPORTANT FIX: validate response BEFORE JSON parsing
        if r.status_code != 200:
            print("API blocked (status):", r.status_code, flush=True)
            return []

        text = r.text.strip()

        if not text or text.startswith("<"):
            print("API returned non-JSON (blocked or HTML)", flush=True)
            return []

        return r.json()

    except Exception as e:
        print("API error:", e, flush=True)
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
                    print(f"👀 Tracking: {name}", flush=True)

                # 5 min window
                if now - WATCHLIST[mint] > 300:
                    continue

                if mint in SENT:
                    continue

                chat = verify_chat(mint)

                if chat:
                    SENT.add(mint)

                    msg = (
                        "🚨 VERIFIED PUMP.FUN COIN WITH CHAT\n\n"
                        f"Name: {name}\n"
                        f"CA: {mint}\n\n"
                        f"💬 Chat:\n{chat}\n\n"
                        f"https://pump.fun/{mint}"
                    )

                    print(f"💬 SENT: {name}", flush=True)
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