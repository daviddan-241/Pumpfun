import os
import json
import requests
import time
from collections import deque
from threading import Lock, Thread
from flask import Flask

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8768676919:AAFbHfcNAU_x899JeIIiduOBKEdj1xHw404")
CHAT_ID = os.environ.get("CHAT_ID", "-1003908847150")

# Only consider coins newer than this many seconds. Wider window = more
# candidates that have had time to spin up a community chat.
MAX_AGE_SECS = int(os.environ.get("MAX_AGE_SECS", "1800"))

# Minimum replies to qualify (pump.fun's listing endpoint usually reports 0,
# so leave this at 0 unless you really want to gate on it).
MIN_REPLIES = int(os.environ.get("MIN_REPLIES", "0"))

# If "1", only send coins that already have an active community chat.
# Default "1" — user only wants coins that have a real group attached.
REQUIRE_CHAT = os.environ.get("REQUIRE_CHAT", "1") == "1"

# Seconds to remember a "no chat yet" result so we don't hammer the chat API.
NO_CHAT_TTL = int(os.environ.get("NO_CHAT_TTL", "90"))

# Throttle Telegram sends so the channel gets a steady drip, not a burst.
SEND_DELAY = float(os.environ.get("SEND_DELAY", "4"))

# Max coins to send per scan tick (extra ones get caught on the next tick).
MAX_PER_SCAN = int(os.environ.get("MAX_PER_SCAN", "3"))

# Polling cadence for the pump.fun listing endpoint.
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "8"))

# How many coins to pull per listing call.
LISTING_LIMIT = int(os.environ.get("LISTING_LIMIT", "100"))

# Self-ping interval (keeps the server alive on Render / UptimeRobot).
PING_INTERVAL = int(os.environ.get("PING_INTERVAL", "240"))

# Send the "bot is live" message on startup.
ANNOUNCE_STARTUP = os.environ.get("ANNOUNCE_STARTUP", "1") == "1"

# Persist sent mints to disk so restarts don't re-send the same coins.
SENT_FILE = os.environ.get("SENT_FILE", "sent_mints.json")
# Bounded so dedupe state always fits in a single Telegram message (~4096 chars).
# 44-char mints + JSON overhead → ~80 mints fits comfortably.
SENT_MAX = int(os.environ.get("SENT_MAX", "80"))

# Marker that lets us recognize our own dedupe message in the channel's pinned slot.
STATE_MARKER = "__PUMPFUN_BOT_DEDUPE_STATE__"

app = Flask(__name__)

# Cap the dedupe set so memory stays bounded over long runs.
SENT = set()
SENT_ORDER = deque(maxlen=SENT_MAX)
# Same-name copycat suppression: blocks repeats of the same (name, symbol).
SENT_NAMES = set()
SENT_NAMES_ORDER = deque(maxlen=SENT_MAX)
SENT_LOCK = Lock()

# Telegram message ID of the pinned dedupe state message (None = not yet created).
state_msg_id = None
# Whether the bot has admin/pin perms in the channel. Detected at startup.
remote_persistence_ok = True

# Cache "no chat yet" lookups so we don't recheck the same mint every 8s.
# mint -> unix_timestamp_when_we_can_recheck
NO_CHAT_CACHE = {}

last_send_time = 0.0


def _state_text():
    """Render the dedupe state as a single Telegram message body."""
    payload = json.dumps(
        {"mints": list(SENT_ORDER), "names": list(SENT_NAMES_ORDER)},
        separators=(",", ":"),
    )
    return f"{STATE_MARKER}\n{payload}"


def _parse_state_text(text):
    """
    Parse a state message body. Returns (mints, names) tuple, or (None, None)
    if the text isn't ours. Backward-compatible with the old list-only format.
    """
    if not text or not text.startswith(STATE_MARKER):
        return None, None
    try:
        body = text[len(STATE_MARKER):].strip()
        data = json.loads(body)
        if isinstance(data, list):
            return [m for m in data if isinstance(m, str)], []
        if isinstance(data, dict):
            mints = [m for m in data.get("mints", []) if isinstance(m, str)]
            names = [n for n in data.get("names", []) if isinstance(n, str)]
            return mints, names
    except Exception:
        return None, None
    return None, None


def _name_key(coin):
    """Stable lower-cased (name, symbol) key for copycat detection."""
    name = (coin.get("name") or "").strip().lower()
    sym = (coin.get("symbol") or "").strip().lower()
    return f"{name}|{sym}"


def load_sent_from_disk():
    """Local cache — fast in normal operation but wiped on Render restarts."""
    try:
        with open(SENT_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            mints, names = data, []
        elif isinstance(data, dict):
            mints = data.get("mints", [])
            names = data.get("names", [])
        else:
            return 0
        for m in mints[-SENT_MAX:]:
            if m not in SENT:
                SENT.add(m)
                SENT_ORDER.append(m)
        for n in names[-SENT_MAX:]:
            if n not in SENT_NAMES:
                SENT_NAMES.add(n)
                SENT_NAMES_ORDER.append(n)
        return len(mints)
    except FileNotFoundError:
        return 0
    except Exception as e:
        print(f"⚠️ Could not load {SENT_FILE}: {e}", flush=True)
    return 0


def save_sent_to_disk():
    """Persist the dedupe list to disk (atomic write)."""
    try:
        tmp = SENT_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(
                {"mints": list(SENT_ORDER), "names": list(SENT_NAMES_ORDER)},
                f,
            )
        os.replace(tmp, SENT_FILE)
    except Exception as e:
        print(f"⚠️ Could not save {SENT_FILE}: {e}", flush=True)


def load_sent_from_telegram():
    """
    Restore dedupe state from the channel's pinned message.
    Returns the number of mints loaded, or -1 if the bot can't access the chat
    (no admin / wrong CHAT_ID / token bad).
    """
    global state_msg_id
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat"
        r = requests.get(url, params={"chat_id": CHAT_ID}, timeout=15)
        if r.status_code != 200:
            print(f"⚠️ getChat failed: {r.status_code} {r.text[:200]}", flush=True)
            return -1
        result = r.json().get("result", {})
        pinned = result.get("pinned_message")
        if not pinned:
            return 0
        text = pinned.get("text") or pinned.get("caption") or ""
        mints, names = _parse_state_text(text)
        if mints is None:
            print("ℹ️ Pinned message is not our dedupe state — leaving it alone.", flush=True)
            return 0
        state_msg_id = pinned.get("message_id")
        with SENT_LOCK:
            for m in mints[-SENT_MAX:]:
                if m not in SENT:
                    SENT.add(m)
                    SENT_ORDER.append(m)
            for n in (names or [])[-SENT_MAX:]:
                if n not in SENT_NAMES:
                    SENT_NAMES.add(n)
                    SENT_NAMES_ORDER.append(n)
        return len(mints)
    except Exception as e:
        print(f"⚠️ load_sent_from_telegram error: {e}", flush=True)
        return -1


def refresh_state_from_telegram():
    """
    Lightweight pre-send refresh. Pulls the latest pinned dedupe message so
    multiple bot instances (Replit + Render running together) don't double-send.
    """
    if not remote_persistence_ok:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat"
        r = requests.get(url, params={"chat_id": CHAT_ID}, timeout=10)
        if r.status_code != 200:
            return
        pinned = r.json().get("result", {}).get("pinned_message") or {}
        text = pinned.get("text") or ""
        mints, names = _parse_state_text(text)
        if mints is None:
            return
        with SENT_LOCK:
            for m in mints[-SENT_MAX:]:
                if m not in SENT:
                    SENT.add(m)
                    SENT_ORDER.append(m)
            for n in (names or [])[-SENT_MAX:]:
                if n not in SENT_NAMES:
                    SENT_NAMES.add(n)
                    SENT_NAMES_ORDER.append(n)
    except Exception:
        # Silent — this is just an optimization to avoid duplicates.
        pass


def save_sent_to_telegram():
    """
    Edit (or create + pin) the dedupe state message in the channel so the
    state survives Render restarts and free-tier disk wipes.
    """
    global state_msg_id, remote_persistence_ok
    if not remote_persistence_ok:
        return

    text = _state_text()

    # Try editing the existing pinned state message first.
    if state_msg_id is not None:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
            r = requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "message_id": state_msg_id,
                    "text": text,
                    "disable_web_page_preview": "true",
                },
                timeout=15,
            )
            if r.status_code == 200:
                return
            # "message is not modified" = same content, fine.
            if "not modified" in r.text:
                return
            # Anything else: fall through to recreating the state msg.
            print(f"ℹ️ editMessageText failed ({r.status_code}); will re-create state msg", flush=True)
            state_msg_id = None
        except Exception as e:
            print(f"⚠️ editMessageText error: {e}", flush=True)
            state_msg_id = None

    # Create + pin a new state message.
    try:
        send_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        sr = requests.post(
            send_url,
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "disable_notification": "true",
                "disable_web_page_preview": "true",
            },
            timeout=15,
        )
        if sr.status_code != 200:
            print(f"⚠️ sendMessage(state) failed: {sr.text[:200]}", flush=True)
            remote_persistence_ok = False
            return
        new_id = sr.json().get("result", {}).get("message_id")
        if not new_id:
            return
        state_msg_id = new_id

        pin_url = f"https://api.telegram.org/bot{BOT_TOKEN}/pinChatMessage"
        pr = requests.post(
            pin_url,
            data={
                "chat_id": CHAT_ID,
                "message_id": new_id,
                "disable_notification": "true",
            },
            timeout=15,
        )
        if pr.status_code != 200:
            # Pinning failed — bot likely lacks pin permission. Disable remote
            # persistence so we don't spam the channel with extra state msgs.
            print(
                f"⚠️ pinChatMessage failed ({pr.status_code}): {pr.text[:200]}\n"
                "   → Make the bot a channel admin with 'Pin messages' permission "
                "for restart-proof dedupe.",
                flush=True,
            )
            remote_persistence_ok = False
    except Exception as e:
        print(f"⚠️ save_sent_to_telegram error: {e}", flush=True)
        remote_persistence_ok = False

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
            url = (
                "https://frontend-api-v3.pump.fun/coins"
                f"?offset=0&limit={LISTING_LIMIT}&sort=created_timestamp&order=DESC&includeNsfw=true"
            )
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
def remember_sent(mint, name_key=None):
    with SENT_LOCK:
        # When the deque hits maxlen, the leftmost is auto-evicted on append.
        # Mirror that eviction in the SENT set so memory stays bounded.
        if len(SENT_ORDER) == SENT_ORDER.maxlen and SENT_ORDER:
            evicted = SENT_ORDER[0]
            SENT.discard(evicted)
        SENT_ORDER.append(mint)
        SENT.add(mint)

        if name_key:
            if (
                len(SENT_NAMES_ORDER) == SENT_NAMES_ORDER.maxlen
                and SENT_NAMES_ORDER
            ):
                SENT_NAMES.discard(SENT_NAMES_ORDER[0])
            SENT_NAMES_ORDER.append(name_key)
            SENT_NAMES.add(name_key)

        save_sent_to_disk()
    # Telegram update happens outside the lock — network call shouldn't block scans.
    save_sent_to_telegram()


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
        "✨ New active coin found",
        "",
        f"🆕 {name} (${symbol})",
        f"💰 MC: {format_mc(usd_mc)}",
        f"⏱ Age: {format_age(age_secs)}",
        f"💬 Replies: {reply_count}",
        "",
        f"🔗 {coin_url}",
    ]
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

            # Garbage-collect expired no-chat cache entries.
            for k in [m for m, exp in NO_CHAT_CACHE.items() if exp <= now]:
                NO_CHAT_CACHE.pop(k, None)

            sent_this_tick = 0
            chat_checks = 0
            cache_skips = 0
            name_skips = 0

            for c, age_secs in eligible:
                if sent_this_tick >= MAX_PER_SCAN:
                    break

                mint = c["mint"]

                # Skip recheck if we recently saw "no chat yet".
                if mint in NO_CHAT_CACHE:
                    cache_skips += 1
                    continue

                # Skip same-name copycat coins (different mint, same name+symbol).
                nkey = _name_key(c)
                if nkey in SENT_NAMES:
                    name_skips += 1
                    continue

                chat_url = get_invite_link(mint)
                chat_checks += 1

                if REQUIRE_CHAT and not chat_url:
                    NO_CHAT_CACHE[mint] = now + NO_CHAT_TTL
                    continue

                # CRITICAL: refresh state from the pinned Telegram message right
                # before sending so a parallel bot instance can't double-fire
                # the same coin. This is the cross-instance lock.
                refresh_state_from_telegram()
                if mint in SENT or nkey in SENT_NAMES:
                    print(
                        f"⏭️ {c.get('name')} ({c.get('symbol')}) — "
                        f"already sent by another instance",
                        flush=True,
                    )
                    continue

                msg = build_message(c, age_secs, chat_url)
                name = c.get("name", "Unknown")
                symbol = c.get("symbol", "")
                print(
                    f"📨 {name} ({symbol}) | MC={format_mc(c.get('usd_market_cap') or 0)} "
                    f"| age={format_age(age_secs)} | chat=yes",
                    flush=True,
                )

                if send_telegram(msg):
                    remember_sent(mint, name_key=nkey)
                    NO_CHAT_CACHE.pop(mint, None)
                    sent_this_tick += 1

            print(
                f"👀 Scanned {len(coins)} | eligible {len(eligible)} | "
                f"chat-checks {chat_checks} | cache-skips {cache_skips} | "
                f"name-skips {name_skips} | sent {sent_this_tick} | "
                f"tracked {len(SENT)} | names {len(SENT_NAMES)} | "
                f"no-chat-cache {len(NO_CHAT_CACHE)}",
                flush=True,
            )

            time.sleep(POLL_INTERVAL)

        except Exception as e:
            print(f"Loop crash: {e}", flush=True)
            time.sleep(5)


# ================= START =================
if __name__ == "__main__":
    print("🔥 SYSTEM STARTING", flush=True)

    # 1) Local cache (fast, but wiped on Render restarts)
    n_disk = load_sent_from_disk()
    if n_disk:
        print(f"📂 Loaded {n_disk} mints from disk cache ({SENT_FILE})", flush=True)

    # 2) Restart-proof source of truth: pinned dedupe message in the channel
    n_remote = load_sent_from_telegram()
    if n_remote > 0:
        print(f"☁️ Loaded {n_remote} mints from pinned Telegram state msg", flush=True)
    elif n_remote == 0:
        print("☁️ No pinned dedupe state yet — will create one on first send", flush=True)
    else:
        print("☁️ Telegram dedupe disabled (couldn't read channel state)", flush=True)
        remote_persistence_ok = False

    print(
        f"🧠 Total tracked at startup: {len(SENT)} mints, {len(SENT_NAMES)} names",
        flush=True,
    )

    Thread(target=run_flask, daemon=True).start()
    time.sleep(2)

    Thread(target=self_ping, daemon=True).start()

    bot_loop()
