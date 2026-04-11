import os
import requests
import time
from flask import Flask
from threading import Thread

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8768676919:AAFbHfcNAU_x899JeIIiduOBKEdj1xHw404")
CHAT_ID = os.environ.get("CHAT_ID", "-5191938939")

# Only alert for coins newer than this many seconds after creation
MAX_AGE_SECS = int(os.environ.get("MAX_AGE_SECS", "300"))   # 5 minutes

# Minimum replies before alerting (community activity signal)
MIN_REPLIES = int(os.environ.get("MIN_REPLIES", "1"))

# Delay between Telegram sends (seconds)
SEND_DELAY = float(os.environ.get("SEND_DELAY", "3"))

app = Flask(__name__)
SENT = set()
last_send_time = 0.0

api_session = requests.Session()
api_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/"
})

chat_session = requests.Session()
chat_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
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
    global last_send_time

    elapsed = time.time() - last_send_time
    if elapsed < SEND_DELAY:
        time.sleep(SEND_DELAY - elapsed)

    for attempt in range(5):
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            r = requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "text": msg,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "false"
                },
                timeout=10
            )
            last_send_time = time.time()

            if r.status_code == 429:
                retry_after = r.json().get("parameters", {}).get("retry_after", 30)
                print(f"⏳ Rate limited — waiting {retry_after}s", flush=True)
                time.sleep(retry_after + 1)
                continue

            if r.status_code != 200:
                print(f"Telegram error (attempt {attempt+1}): {r.text[:150]}", flush=True)
                time.sleep(2)
            else:
                print("✅ Sent", flush=True)
                return

        except Exception as e:
            print(f"Telegram exception (attempt {attempt+1}): {e}", flush=True)
            time.sleep(2)


# ================= COIN FETCH =================
def get_coins():
    retries = 3
    delay = 2
    for attempt in range(retries):
        try:
            url = "https://frontend-api-v3.pump.fun/coins?offset=0&limit=50&sort=created_timestamp&order=DESC&includeNsfw=true"
            r = api_session.get(url, timeout=15)

            if r.status_code != 200:
                print(f"API status {r.status_code}", flush=True)
                time.sleep(delay)
                delay *= 2
                continue

            text = r.text.strip()
            if not text or text.startswith("<"):
                time.sleep(delay)
                delay *= 2
                continue

            data = r.json()
            return data if isinstance(data, list) else data.get("coins", [])

        except Exception as e:
            print(f"API error (attempt {attempt+1}): {e}", flush=True)
            time.sleep(delay)
            delay *= 2

    return []


# ================= CHAT INVITE FETCH =================
def get_invite_link(mint):
    """
    Fetches the short invite link ID from the pump.fun chat API.
    Returns the full chat URL like https://pump.fun/chat/{inviteLinkId},
    or None if the coin has no community chat set up yet.
    """
    try:
        url = f"https://chat-api-v1.pump.fun/invites/coin/{mint}"
        r = chat_session.get(url, timeout=10)

        if r.status_code != 200:
            return None

        data = r.json()
        invite_id = data.get("inviteLinkId")
        if not invite_id:
            return None

        return f"https://pump.fun/chat/{invite_id}"

    except Exception as e:
        print(f"Chat API error for {mint}: {e}", flush=True)
        return None


# ================= BOT LOOP =================
def bot_loop():
    print("🔥 BOT LOOP STARTED", flush=True)
    send_telegram("🚀 Bot is LIVE — scanning pump.fun for new coins with community chats...")

    while True:
        try:
            coins = get_coins()
            now = time.time()

            if coins:
                print(f"👀 Scanning {len(coins)} coins", flush=True)

            for c in coins:
                mint = c.get("mint")
                if not mint or mint in SENT:
                    continue

                name = c.get("name", "Unknown")
                symbol = c.get("symbol", "")
                created_ts = (c.get("created_timestamp") or 0) / 1000
                reply_count = c.get("reply_count") or 0
                age_secs = now - created_ts

                # Only fresh coins
                if age_secs > MAX_AGE_SECS:
                    continue

                # Must have community activity
                if reply_count < MIN_REPLIES:
                    continue

                # Fetch the real short invite link from the chat API
                chat_url = get_invite_link(mint)
                if not chat_url:
                    print(f"⏭️ {name} ({symbol}) — no chat group yet, skipping", flush=True)
                    continue

                SENT.add(mint)

                msg = (
                    f"🆕 pump.fun new update\n\n"
                    f"{chat_url}"
                )

                print(f"📨 {name} ({symbol}) | replies={reply_count} | age={int(age_secs)}s | {chat_url}", flush=True)
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
