import requests
import time
import re
from flask import Flask
from threading import Thread

BOT_TOKEN = "8710292892:AAHGhAR_2xdkXba2wNclnyl5wOK_OjE38I4"
CHAT_ID = "5578314612"

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot running"

def run():
    app.run(host="0.0.0.0", port=10000)

def keep_alive():
    Thread(target=run).start()


# STORE COINS TO RECHECK
WATCHLIST = {}  # ca -> timestamp
SEEN_SENT = set()


# ================= TELEGRAM =================
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})


# ================= FETCH COINS =================
def get_coins():
    try:
        url = "https://frontend-api.pump.fun/coins?offset=0&limit=50&sort=created_timestamp&order=desc"
        r = requests.get(url, timeout=10)
        return r.json()
    except:
        return []


# ================= CHAT DETECTOR =================
def get_chat(ca):
    try:
        r = requests.get(f"https://pump.fun/{ca}", timeout=10)
        match = re.search(r"(https://pump\.fun/chat/[a-zA-Z0-9]+)", r.text)
        if match:
            return match.group(1)
    except:
        pass
    return None


# ================= MAIN SNIPER =================
def main():
    print("🔥 SNIPER BOT STARTED")
    send_telegram("🚀 Pump.fun sniper bot LIVE")

    while True:
        coins = get_coins()

        now = time.time()

        for c in coins:
            ca = c.get("mint")
            name = c.get("name")

            if not ca:
                continue

            # add to watchlist (track for 5 min)
            if ca not in WATCHLIST:
                WATCHLIST[ca] = now
                print(f"👀 Tracking new coin: {name}")

            # re-check only for 5 minutes
            age = now - WATCHLIST[ca]
            if age > 300:
                continue

            chat = get_chat(ca)

            if chat and ca not in SEEN_SENT:
                SEEN_SENT.add(ca)

                msg = f"""
🚨 NEW PUMP.FUN COIN WITH CHAT

Name: {name}
CA: {ca}

💬 Chat:
{chat}

https://pump.fun/{ca}
"""
                print(f"💬 FOUND CHAT: {name}")
                send_telegram(msg)

        time.sleep(10)


if __name__ == "__main__":
    keep_alive()
    main()