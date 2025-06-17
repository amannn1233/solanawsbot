import os
import json
import asyncio
import requests
import websockets

from dotenv        import load_dotenv
from datetime      import datetime, timezone

# ─── CONFIG ───────────────────────────────────────────────────────────────

load_dotenv()  # expects TELEGRAM_BOT_TOKEN & TELEGRAM_USER_ID
BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN")
USER_ID      = os.getenv("TELEGRAM_USER_ID")

RPC_WS       = "wss://api.mainnet-beta.solana.com/"
WALLETS      = [
    "dUJNHh9Nm9rsn7ykTViG7N7BJuaoJJD9H635B8BVifa",
    "HvfLxsruaPW4uYZiXk6FBm9brCc78LL5Si9No92iJkSw",
]
THRESHOLD_LAMPORTS = int(20 * 1e9)   # 20 SOL

sub_to_wallet = {}
last_balances  = {}

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def send_telegram(text: str):
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    res  = requests.post(url, data={"chat_id": USER_ID, "text": text})
    if res.status_code != 200:
        print(f"[{utc_now()}] ⚠️ Telegram error:", res.text)

async def subscribe_all(ws):
    """Subscribe each wallet; populate sub_to_wallet & init balances."""
    for i, addr in enumerate(WALLETS, start=1):
        req = {
            "jsonrpc": "2.0",
            "id": i,
            "method": "accountSubscribe",
            "params": [addr, {"encoding": "base64"}]
        }
        await ws.send(json.dumps(req))
        resp = json.loads(await ws.recv())
        sub_id = resp.get("result")
        sub_to_wallet[sub_id] = addr
        last_balances[addr] = None

async def listen():
    async with websockets.connect(RPC_WS, ping_interval=30) as ws:
        await subscribe_all(ws)
        print(f"[{utc_now()}] ✅ Subscribed to {len(WALLETS)} wallets.")
        async for message in ws:
            msg = json.loads(message)
            if msg.get("method") != "accountNotification":
                continue

            params   = msg["params"]
            sub_id   = params["subscription"]
            info     = params["result"]["value"]
            lamports = info["lamports"]
            wallet   = sub_to_wallet[sub_id]

            # init
            if last_balances[wallet] is None:
                last_balances[wallet] = lamports
                continue

            delta = lamports - last_balances[wallet]
            last_balances[wallet] = lamports

            if delta < 0 and abs(delta) >= THRESHOLD_LAMPORTS:
                sol_sent = abs(delta) / 1e9
                ts       = utc_now()
                text     = (
                    f"🚨 {sol_sent:.2f} SOL sent from {wallet}\n"
                    f"Time: {ts}\n"
                    f"https://solscan.io/tx/{info.get('owner') or wallet}"
                )
                send_telegram(text)
                print(f"[{ts}] Alert: {wallet} → {sol_sent:.2f} SOL")

async def listen_forever():
    backoff = 1
    while True:
        try:
            await listen()
        except Exception as e:
            print(f"[{utc_now()}] 🔁 WS error: {e!r} — reconnecting in {backoff}s…")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)  # cap at 60s
        else:
            backoff = 1  # reset on clean exit

def main():
    print(f"[{utc_now()}] Starting Solana WS monitor…")
    asyncio.run(listen_forever())

if __name__ == "__main__":
    main()
    import threading
from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    # start your Solana listener in a daemon thread
    t = threading.Thread(target=lambda: asyncio.run(listen_forever()), daemon=True)
    t.start()
    # start an HTTP server on $PORT
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
