import os
import requests
import time
import re
from flask import Flask
from threading import Thread

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8768676919:AAFbHfcNAU_x899JeIIiduOBKEdj1xHw404")
CHAT_ID = os.environ.get("CHAT_ID", "-5191938939")

app = Flask(__name__)

WATCHLIST = {}
SENT = set()

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Accept-Encoding": "gzip, deflate, br",
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
    for attempt in range(3):
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            r = requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)

            if r.status_code != 200:
                print(f"Telegram Error (attempt {attempt+1}):", r.text[:200], flush=True)
            else:
                print("✅ Telegram message sent successfully", flush=True)
                return

        except Exception as e:
            print(f"Telegram Exception (attempt {attempt+1}):", e, flush=True)
            time.sleep(2)


# ================= COIN FETCH (v3 API) =================
def get_coins():
    retries = 3
    delay = 2
    for attempt in range(retries):
        try:
            url = "https://frontend-api-v3.pump.fun/coins?offset=0&limit=50&sort=created_timestamp&order=DESC&includeNsfw=true"
            r = session.get(url, timeout=15)

            if r.status_code != 200:
                print(f"API blocked (status {r.status_code}), retrying...", flush=True)
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
            if isinstance(data, list):
                return data
            return data.get("coins", data) if isinstance(data, dict) else []

        except Exception as e:
            print(f"API error (attempt {attempt + 1}/{retries}): {e}", flush=True)
            time.sleep(delay)
            delay *= 2

    print("API requests failed after retries", flush=True)
    return []


# ================= PUMP.FUN PAGE CHAT DETECTOR =================
def get_pumpfun_chat(mint):
    try:
        url = f"https://pump.fun/{mint}"
        r = session.get(url, timeout=10)
        match = re.search(r"https://pump\.fun/chat/[a-zA-Z0-9]+", r.text)
        if match:
            return match.group(0)
    except Exception as e:
        print(f"Chat page error: {e}", flush=True)
    return None


# ================= BOT LOOP =================
def bot_loop():
    print("🔥 BOT LOOP STARTED", flush=True)
    send_telegram("🚀 Pump.fun bot LIVE — scanning for new coins with chat links...")

    while True:
        try:
            coins = get_coins()
            now = time.time()

            if coins:
                print(f"👀 Scanning {len(coins)} coins...", flush=True)
            else:
                print("⚠️ No coins returned, will retry next cycle", flush=True)

            for c in coins:
                mint = c.get("mint")
                name = c.get("name", "Unknown")
                symbol = c.get("symbol", "")
                telegram_link = c.get("telegram") or ""
                twitter_link = c.get("twitter") or ""
                description = c.get("description", "")

                if not mint:
                    continue

                # Track new coins
                if mint not in WATCHLIST:
                    WATCHLIST[mint] = now
                    print(f"📌 New coin: {name} ({symbol}) | TG: {'yes' if telegram_link else 'no'}", flush=True)

                # Only track within 10-minute window
                if now - WATCHLIST[mint] > 600:
                    continue

                if mint in SENT:
                    continue

                chat_link = None

                # Method 1: Direct Telegram link from API response
                if telegram_link and telegram_link.startswith("http"):
                    chat_link = telegram_link
                    print(f"💬 Telegram link found in API for: {name}", flush=True)

                # Method 2: pump.fun internal chat page
                if not chat_link:
                    pf_chat = get_pumpfun_chat(mint)
                    if pf_chat:
                        chat_link = pf_chat
                        print(f"💬 Pump.fun chat found for: {name}", flush=True)

                if chat_link:
                    SENT.add(mint)

                    lines = [
                        "🚨 <b>NEW PUMP.FUN COIN WITH CHAT</b>",
                        "",
                        f"🪙 <b>Name:</b> {name} (${symbol})",
                        f"📋 <b>CA:</b> <code>{mint}</code>",
                    ]

                    if description:
                        lines.append(f"📝 {description[:100]}")

                    lines += [
                        "",
                        f"💬 <b>Chat:</b> {chat_link}",
                    ]

                    if twitter_link:
                        lines.append(f"🐦 <b>Twitter:</b> {twitter_link}")

                    lines += [
                        "",
                        f"🔗 https://pump.fun/{mint}",
                        f"📊 https://dexscreener.com/solana/{mint}",
                    ]

                    msg = "\n".join(lines)
                    print(f"📨 Sending to Telegram: {name} ({symbol})", flush=True)
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
