import requests
import time
import re
from flask import Flask
from threading import Thread

# ================== CONFIG ==================
BOT_TOKEN = "8710292892:AAHGhAR_2xdkXba2wNclnyl5wOK_OjE38I4"
CHAT_ID = "5578314612"

# ============================================

SEEN = set()

# ===== KEEP ALIVE (FOR RENDER WEB SERVICE) =====
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running"

def run():
    app.run(host='0.0.0.0', port=10000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ==============================================

def get_new_coins():
    url = "https://frontend-api.pump.fun/coins"
    try:
        r = requests.get(url, timeout=10)
        return r.json()
    except:
        return []

def get_chat_link(ca):
    try:
        url = f"https://pump.fun/{ca}"
        r = requests.get(url, timeout=10)

        if "pump.fun/chat/" in r.text:
            match = re.search(r"(https://pump\.fun/chat/[a-zA-Z0-9]+)", r.text)
            if match:
                return match.group(1)

    except:
        return None

    return None

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }

    try:
        requests.post(url, data=data)
    except:
        pass

def main():
    print("🔥 Scanning pump.fun for NEW coins with chats...")

    while True:
        coins = get_new_coins()

        print(f"Scanning {len(coins)} coins...")

        for coin in coins:
            ca = coin.get("mint")
            name = coin.get("name")
            mc = coin.get("market_cap", 0)

            if not ca or ca in SEEN:
                continue

            SEEN.add(ca)

            chat_link = get_chat_link(ca)

            if chat_link:
                print(f"✅ FOUND CHAT: {name}")

                msg = f"""
🚨 *NEW COIN WITH CHAT*

💎 Name: {name}
📜 CA: `{ca}`
💰 MC: ${mc}

💬 Chat:
{chat_link}

🔗 https://pump.fun/{ca}
"""

                send_telegram(msg)

        time.sleep(15)

# ===== START =====
if __name__ == "__main__":
    keep_alive()  # fixes Render port issue
    main()