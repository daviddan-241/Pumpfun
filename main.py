import os
import requests
import time
from flask import Flask
from threading import Thread

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8768676919:AAFbHfcNAU_x899JeIIiduOBKEdj1xHw404")
CHAT_ID = os.environ.get("CHAT_ID", "-5191938939")

MAX_AGE_SECS = int(os.environ.get("MAX_AGE_SECS", "300"))
MIN_REPLIES = int(os.environ.get("MIN_REPLIES", "1"))
SEND_DELAY = float(os.environ.get("SEND_DELAY", "3"))

# Self-ping interval in seconds (keeps the server alive on Render / UptimeRobot)
PING_INTERVAL = int(os.environ.get("PING_INTERVAL", "240"))

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


# ================= FLASK =================
@app.route("/")
def home():
    return "Bot is LIVE", 200

@app.route("/ping")
def ping():
    return "pong", 200


def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


# ================= SELF-PING (keep-alive) =================
def self_ping():
    """
    Pings the bot's own / endpoint every PING_INTERVAL seconds.
    Keeps Render web services awake and satisfies UptimeRobot health checks.
    Set your UptimeRobot monitor to the same public URL.
    """
    time.sleep(30)
    port = int(os.environ.get("PORT", 5000))
    url = os.environ.get("RENDER_EXTERNAL_URL", f"http://localhost:{port}")
    while True:
        try:
            r = requests.get(f"{url}/ping", timeout=10)
            print(f"🏓 Self-ping {r.status_code}", flush=True)
        except Exception as e:
            print(f"⚠️ Self-ping failed: {e}", flush=True)
        time.sleep(PING_INTERVAL)


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
    Returns https://pump.fun/chat/{inviteLinkId} for coins that have an active
    community chat, or None if the chat group doesn't exist yet.
    """
    try:
        url = f"https://chat-api-v1.pump.fun/invites/coin/{mint}"
        r = chat_session.get(url, timeout=10)

        if r.status_code != 200:
            return None

        invite_id = r.json().get("inviteLinkId")
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

                if age_secs > MAX_AGE_SECS:
                    continue

                if reply_count < MIN_REPLIES:
                    continue

                chat_url = get_invite_link(mint)
                if not chat_url:
                    print(f"⏭️ {name} ({symbol}) — no chat yet", flush=True)
                    continue

                SENT.add(mint)

                usd_mc = c.get("usd_market_cap") or 0
                if usd_mc >= 1_000_000:
                    mc_str = f"${usd_mc/1_000_000:.2f}M"
                elif usd_mc >= 1_000:
                    mc_str = f"${usd_mc/1_000:.1f}K"
                else:
                    mc_str = f"${usd_mc:.2f}"

                mins = int(age_secs) // 60
                secs = int(age_secs) % 60
                age_str = f"{mins}m {secs}s" if mins else f"{secs}s"

                coin_url = f"https://pump.fun/coin/{mint}"

                msg = (
                    f"🆕 {name} (${symbol})\n"
                    f"💰 MC: {mc_str}\n"
                    f"⏱ Age: {age_str}\n"
                    f"💬 Replies: {reply_count}\n\n"
                    f"{coin_url}"
                )

                print(f"📨 {name} ({symbol}) | MC={mc_str} | replies={reply_count} | age={age_str}", flush=True)
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

    Thread(target=self_ping, daemon=True).start()

    bot_loop()
