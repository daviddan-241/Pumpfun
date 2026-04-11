import os
import requests
import time
from flask import Flask
from threading import Thread

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8768676919:AAFbHfcNAU_x899JeIIiduOBKEdj1xHw404")
CHAT_ID = os.environ.get("CHAT_ID", "-5191938939")

# Only alert for coins newer than this many minutes
MAX_AGE_MINUTES = int(os.environ.get("MAX_AGE_MINUTES", "10"))

# Minimum reply count to consider a coin active
MIN_REPLIES = int(os.environ.get("MIN_REPLIES", "1"))

# Seconds to wait between Telegram sends
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

    # Enforce minimum gap between sends
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
                    "disable_web_page_preview": "true"
                },
                timeout=10
            )
            last_send_time = time.time()

            if r.status_code == 429:
                retry_after = r.json().get("parameters", {}).get("retry_after", 30)
                print(f"⏳ Rate limited, waiting {retry_after}s...", flush=True)
                time.sleep(retry_after + 1)
                continue

            if r.status_code != 200:
                print(f"Telegram Error (attempt {attempt+1}): {r.text[:200]}", flush=True)
                time.sleep(2)
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


# ================= CHECK FOR PUMP.FUN COMMUNITY CHAT =================
def check_community_chat(mint):
    """
    Hits the pump.fun coin page and looks for the community chat section.
    The section is only fully rendered (with community name visible) for coins
    that have an active community. Falls back to 'Join chat' presence as minimum signal.
    Returns True if the coin page shows a community chat.
    """
    try:
        url = f"https://pump.fun/coin/{mint}"
        r = api_session.get(url, timeout=15)
        if r.status_code == 200:
            html = r.text
            # Look for the specific community chat section in the rendered HTML
            # "chat" text appearing near the coin image in the community section
            # indicates an established community (not just the generic Join button)
            has_chat_section = (
                "Join chat" in html and
                (" chat</div>" in html or "<!-- --> chat" in html)
            )
            return has_chat_section
    except Exception as e:
        print(f"Chat check error: {e}", flush=True)
    return False


# ================= BOT LOOP =================
def bot_loop():
    print("🔥 BOT LOOP STARTED", flush=True)
    send_telegram(
        "🚀 <b>Pump.fun chat monitor is LIVE</b>\n\n"
        "Watching for new coins with active holders community chats..."
    )

    while True:
        try:
            coins = get_coins()
            now = time.time()
            max_age_secs = MAX_AGE_MINUTES * 60

            if coins:
                print(f"👀 Scanning {len(coins)} coins...", flush=True)

            for c in coins:
                mint = c.get("mint")
                if not mint or mint in SENT:
                    continue

                name = c.get("name", "Unknown")
                symbol = c.get("symbol", "")
                created_ts = c.get("created_timestamp", 0) / 1000
                reply_count = c.get("reply_count", 0) or 0
                age_secs = now - created_ts

                # Only look at fresh coins within the time window
                if age_secs > max_age_secs:
                    continue

                # Must have at least MIN_REPLIES to show community activity
                if reply_count < MIN_REPLIES:
                    continue

                # Check if coin page shows a community chat section
                if check_community_chat(mint):
                    SENT.add(mint)

                    age_mins = int(age_secs / 60)
                    age_str = f"{age_mins}m ago" if age_mins > 0 else "just now"

                    msg = (
                        "🔥 <b>PUMP.FUN COIN WITH COMMUNITY CHAT</b>\n\n"
                        f"🪙 <b>{name}</b> (${symbol})\n"
                        f"📋 <b>CA:</b> <code>{mint}</code>\n"
                        f"🕐 Created: {age_str}\n"
                        f"💬 Replies: {reply_count}\n\n"
                        f"👥 <b>Join the holders chat:</b>\n"
                        f"https://pump.fun/coin/{mint}"
                    )

                    print(f"💬 Community chat found: {name} ({symbol}) | replies={reply_count}", flush=True)
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
