import requests
import time
import re
from flask import Flask
from threading import Thread

# ================== CONFIG ==================
BOT_TOKEN = "8710292892:AAFI3UJ8LXcekksJeWd39B5DJvo7FhGOvnE"
CHAT_ID = "5578314612"

app = Flask(__name__)

WATCHLIST = {}
SENT = set()

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})


# ================== KEEP ALIVE ==================
@app.route("/")
def home():
    return "Bot running"

def run():
    app.run(host="0.0.0.0", port=10000)


# ================== TELEGRAM ==================
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        session.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram error:", e, flush=True)


# ================== NEW COINS ONLY ==================
def get_new_coins():
    try:
        url = "https://frontend-api.pump.fun/coins?offset=0&limit=50&sort=created_timestamp&order=desc"
        r = session.get(url, timeout=10)
        return r.json()
    except:
        return []


# ================== CHAT CHECK (REAL VERIFICATION) ==================
def check_chat(mint):
    try:
        url = f"https://pump.fun/{mint}"
        r = session.get(url, timeout=10)

        html = r.text.lower()

        # must contain chat keyword
        if "chat" not in html:
            return None

        match = re.search(r"https://pump\.fun/chat/[a-zA-Z0-9]+", r.text)

        if match:
            return match.group(0)

    except:
        pass

    return None


# ================== DOUBLE VERIFY ==================
def verify_chat(mint):
    first = check_chat(mint)
    if not first:
        return None

    time.sleep(0.5)

    second = check_chat(mint)

    if first and second:
        return second

    return None


# ================== BOT LOOP ==================
def bot():
    print("🔥 BOT STARTED", flush=True)
    send("🚀 Pump.fun NEW COIN CHAT bot LIVE")

    while True:
        coins = get_new_coins()
        now = time.time()

        for c in coins:
            mint = c.get("mint")
            name = c.get("name", "Unknown")

            if not mint:
                continue

            # track only new coins
            if mint not in WATCHLIST:
                WATCHLIST[mint] = now
                print(f"👀 New coin: {name}", flush=True)

            # only keep 5 min window
            if now - WATCHLIST[mint] > 300:
                continue

            if mint in SENT:
                continue

            chat = verify_chat(mint)

            if chat:
                SENT.add(mint)

                msg = (
                    "🚨 NEW PUMP.FUN COIN WITH CHAT\n\n"
                    f"Name: {name}\n"
                    f"CA: {mint}\n\n"
                    f"💬 Chat:\n{chat}\n\n"
                    f"https://pump.fun/{mint}"
                )

                print(f"💬 SENT: {name}", flush=True)
                send(msg)

        time.sleep(6)


# ================== START ==================
if __name__ == "__main__":
    Thread(target=run).start()
    bot()