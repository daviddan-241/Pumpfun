import os
import requests
import time
from collections import deque
from flask import Flask
from threading import Thread

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8768676919:AAFbHfcNAU_x899JeIIiduOBKEdj1xHw404")
CHAT_ID = os.environ.get("CHAT_ID", "-1003908847150")

# Only consider coins newer than this many seconds
MAX_AGE_SECS = int(os.environ.get("MAX_AGE_SECS", "600"))

# Minimum replies to qualify (pump.fun's listing endpoint usually reports 0,
# so leave this at 0 unless you really want to gate on it).
MIN_REPLIES = int(os.environ.get("MIN_REPLIES", "0"))

# If "1", only send coins that already have an active community chat.
# Default "0" so the bot drops steadily even when chats don't exist yet.
REQUIRE_CHAT = os.environ.get("REQUIRE_CHAT", "0") == "1"

# Throttle Telegram sends so the channel gets a steady drip, not a burst.
SEND_DELAY = float(os.environ.get("SEND_DELAY", "4"))

# Max coins to send per scan tick (extra ones get caught on the next tick).
MAX_PER_SCAN = int(os.environ.get("MAX_PER_SCAN", "3"))

# Polling cadence for the pump.fun listing endpoint.
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "8"))

# Self-ping interval (keeps the server alive on Render / UptimeRobot).
PING_INTERVAL = int(os.environ.get("PING_INTERVAL", "240"))

# Send the "bot is live" message on startup.
ANNOUNCE_STARTUP = os.environ.get("ANNOUNCE_STARTUP", "1") == "1"

app = Flask(__name__)

# Cap the dedupe set so memory stays bounded over long runs.
SENT = set()
SENT_ORDER = deque(maxlen=5000)

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

@app.route("/status")
def status():
    return {"sent_count": len(SENT), "last_send_time": last_send_time}, 200


def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)


# ================= SELF-PING (keep-alive) =================
def self_ping():
    """Pings /ping every PING_INTERVAL seconds to keep the server warm."""
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
                timeout=15
            )
            last_send_time = time.time()

            if r.status_code == 429:
                retry_after = r.json().get("parameters", {}).get("retry_after", 30)
                print(f"⏳ Rate limited — waiting {retry_after}s", flush=True)
                time.sleep(retry_after + 1)
                continue

            if r.status_code != 200:
                print(f"Telegram error (attempt {attempt+1}): {r.text[:200]}", flush=True)
                time.sleep(2)
                continue

            print("✅ Sent", flush=True)
            return True

        except Exception as e:
            print(f"Telegram exception (attempt {attempt+1}): {e}", flush=True)
            time.sleep(2)

    return False


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
    Returns https://pump.fun/chat/{inviteLinkId} if the coin already has an
    active community chat, else None. The endpoint returns 200 with a
    `failedReason` body when the group doesn't exist yet — handle that.
    """
    try:
        url = f"https://chat-api-v1.pump.fun/invites/coin/{mint}"
        r = chat_session.get(url, timeout=10)

        if r.status_code != 200:
            return None

        body = r.json()
        if body.get("failedReason") or not body.get("inviteLinkId"):
            return None

        return f"https://pump.fun/chat/{body['inviteLinkId']}"

    except Exception:
        return None


# ================= HELPERS =================
def remember_sent(mint):
    if len(SENT_ORDER) == SENT_ORDER.maxlen and SENT_ORDER:
        old = SENT_ORDER[0]  # will be evicted by the next append
        # Defer eviction: when deque hits maxlen, the leftmost is dropped on append.
        # Mirror that here.
    SENT_ORDER.append(mint)
    SENT.add(mint)
    # Trim SENT to match deque contents to avoid unbounded growth.
    if len(SENT) > SENT_ORDER.maxlen:
        keep = set(SENT_ORDER)
        SENT.intersection_update(keep)


def format_mc(usd_mc):
    if usd_mc >= 1_000_000:
        return f"${usd_mc/1_000_000:.2f}M"
    if usd_mc >= 1_000:
        return f"${usd_mc/1_000:.1f}K"
    return f"${usd_mc:.2f}"


def format_age(secs):
    secs = int(secs)
    mins = secs // 60
    rem = secs % 60
    return f"{mins}m {rem}s" if mins else f"{rem}s"


def build_message(coin, age_secs, chat_url):
    name = coin.get("name", "Unknown")
    symbol = coin.get("symbol", "")
    reply_count = coin.get("reply_count") or 0
    usd_mc = coin.get("usd_market_cap") or 0
    mint = coin.get("mint")
    coin_url = f"https://pump.fun/coin/{mint}"

    lines = [
        f"🆕 {name} (${symbol})",
        f"💰 MC: {format_mc(usd_mc)}",
        f"⏱ Age: {format_age(age_secs)}",
        f"💬 Replies: {reply_count}",
        "",
        f"🔗 {coin_url}",
    ]
    if chat_url:
        lines.append(f"💭 Chat: {chat_url}")
    return "\n".join(lines)


# ================= BOT LOOP =================
def bot_loop():
    print("🔥 BOT LOOP STARTED", flush=True)
    print(
        f"   MAX_AGE_SECS={MAX_AGE_SECS}  MIN_REPLIES={MIN_REPLIES}  "
        f"REQUIRE_CHAT={REQUIRE_CHAT}  SEND_DELAY={SEND_DELAY}  "
        f"MAX_PER_SCAN={MAX_PER_SCAN}",
        flush=True,
    )

    if ANNOUNCE_STARTUP:
        send_telegram("🚀 Bot is LIVE — scanning pump.fun for fresh coins…")

    while True:
        try:
            coins = get_coins()
            now = time.time()

            if not coins:
                time.sleep(POLL_INTERVAL)
                continue

            # Walk oldest-eligible -> newest so the channel reads chronologically.
            eligible = []
            for c in coins:
                mint = c.get("mint")
                if not mint or mint in SENT:
                    continue

                created_ts = (c.get("created_timestamp") or 0) / 1000
                age_secs = now - created_ts
                if age_secs > MAX_AGE_SECS or age_secs < 0:
                    continue

                reply_count = c.get("reply_count") or 0
                if reply_count < MIN_REPLIES:
                    continue

                eligible.append((c, age_secs))

            # Send oldest first for steady chronology.
            eligible.sort(key=lambda x: x[1], reverse=True)

            sent_this_tick = 0
            for c, age_secs in eligible:
                if sent_this_tick >= MAX_PER_SCAN:
                    break

                mint = c["mint"]
                chat_url = get_invite_link(mint)
                if REQUIRE_CHAT and not chat_url:
                    continue

                msg = build_message(c, age_secs, chat_url)
                name = c.get("name", "Unknown")
                symbol = c.get("symbol", "")
                print(
                    f"📨 {name} ({symbol}) | MC={format_mc(c.get('usd_market_cap') or 0)} "
                    f"| age={format_age(age_secs)} | chat={'yes' if chat_url else 'no'}",
                    flush=True,
                )

                if send_telegram(msg):
                    remember_sent(mint)
                    sent_this_tick += 1

            print(
                f"👀 Scanned {len(coins)} | eligible {len(eligible)} | sent {sent_this_tick} | tracked {len(SENT)}",
                flush=True,
            )

            time.sleep(POLL_INTERVAL)

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
