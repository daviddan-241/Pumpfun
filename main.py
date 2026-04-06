import requests
import time
import re
from flask import Flask
from threading import Thread

# ===== CONFIG =====
BOT_TOKEN = "8710292892:AAHGhAR_2xdkXba2wNclnyl5wOK_OjE38I4"
CHAT_ID = "5578314612"

SEEN = set()

# ===== KEEP ALIVE =====
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running"

def run():
    app.run(host='0.0.0.0', port=10000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ===== TELEGRAM TEST =====
def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": text
    }

    try:
        r = requests.post(url, data=data)
        print("Telegram response:", r.text)
    except Exception as e:
        print("Telegram error:", e)

# ===== GET COINS =====
def get_new_coins():
    try:
        r = requests.get("https://frontend-api.pump.fun/coins", timeout=10)
        data = r.json()
        print(f"Fetched {len(data)} coins")
        return data
    except Exception as e:
        print("Error fetching coins:", e)
        return []

# ===== GET CHAT =====
def get_chat_link(ca):
    try:
        url = f"https://pump.fun/{ca}"
        r = requests.get(url, timeout=10)

        match = re.search(r"(https://pump\.fun/chat/[a-zA-Z0-9]+)", r.text)
        if match:
            return match.group(1)

    except Exception as e:
        print("Chat fetch error:", e)

    return None

# ===== MAIN LOOP =====
def main():
    print("🔥 BOT STARTED")

    # 🔥 FORCE TEST MESSAGE
    send_telegram("✅ Bot is LIVE and scanning!")

    while True:
        coins = get_new_coins()

        for coin in coins:
            try:
                ca = coin.get("mint")
                name = coin.get("name")

                print(f"Checking: {name} | {ca}")

                if not ca or ca in SEEN:
                    continue

                SEEN.add(ca)

                chat = get_chat_link(ca)

                if chat:
                    print(f"✅ FOUND CHAT: {name}")

                    msg = f"""
NEW COIN WITH CHAT

Name: {name}
CA: {ca}

Chat:
{chat}

https://pump.fun/{ca}
"""

                    send_telegram(msg)

            except Exception as e:
                print("Loop error:", e)

        time.sleep(15)

# ===== START =====
if __name__ == "__main__":
    keep_alive()
    main()