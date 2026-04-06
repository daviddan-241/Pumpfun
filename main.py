import requests
import time
import re
from flask import Flask
from threading import Thread

# ================= CONFIG =================
BOT_TOKEN = "8710292892:AAFI3UJ8LXcekksJeWd39B5DJvo7FhGOvnE"
CHAT_ID = "5578314612"

app = Flask(__name__)

SEEN = set()

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0"
})


# ================= KEEP ALIVE =================
@app.route("/")
def home():
    return "Running"


def run():
    app.run(host="0.0.0.0", port=10000)


# ================= TELEGRAM =================
def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        session.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except:
        pass


# ================= REAL SOURCE (SOLANA NEW TOKENS) =================
def get_new_tokens():
    try:
        url = "https://api.dexscreener.com/latest/dex/tokens"
        r = session.get(url, timeout=10)

        if r.status_code != 200:
            return []

        data = r.json()
        return data.get("pairs", [])[:50]

    except:
        return []


# ================= PUMP.FUN CHAT CHECK =================
def check_pumpfun_chat(mint):
    try:
        url = f"https://pump.fun/{mint}"
        r = session.get(url, timeout=10)

        if "/chat/" not in r.text:
            return None

        match = re.search(r"https://pump\.fun/chat/[a-zA-Z0-9]+", r.text)
        return match.group(0) if match else None

    except:
        return None


# ================= LOOP =================
def loop():
    print("BOT STARTED")
    send("🚀 Bot live (stable mode)")

    while True:
        try:
            tokens = get_new_tokens()

            print("scanning:", len(tokens))

            for t in tokens:
                base = t.get("baseToken", {})
                mint = base.get("address")
                name = base.get("name")

                if not mint or mint in SEEN:
                    continue

                SEEN.add(mint)

                chat = check_pumpfun_chat(mint)

                if chat:
                    send(
                        f"🚨 PUMP.FUN CHAT TOKEN\n\n"
                        f"{name}\n\n"
                        f"{mint}\n\n"
                        f"{chat}"
                    )

            time.sleep(10)

        except Exception as e:
            print("error:", e)
            time.sleep(5)


# ================= START =================
if __name__ == "__main__":
    Thread(target=run, daemon=True).start()
    time.sleep(2)
    loop()