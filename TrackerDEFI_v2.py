import os
import json
import asyncio
import requests
import websockets
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# ============================================
# CONFIGURAÇÕES DE TIMEZONE
# ============================================

TZ_SP = ZoneInfo("America/Sao_Paulo")

def now_sp():
    return datetime.now(TZ_SP).strftime("%d/%m/%Y %H:%M:%S")

# ============================================
# LOAD .ENV
# ============================================

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não encontrados no .env")

# ============================================
# SOLANA RPC
# ============================================

RPC_HTTP = "https://api.mainnet-beta.solana.com"
RPC_WS   = "wss://api.mainnet-beta.solana.com"

# ============================================
# CARTEIRAS MONITORADAS
# ============================================

MONITORED_WALLETS = [
    "6sjpfFfs28qi5xHi1KVVbwgexGJE4RZvToXPyANeHWKE",
    "9wXNBdnGWHHLnzntZVGTU7t1HZMGHiGNZWnrknreueqr"
]

# ============================================
# TELEGRAM
# ============================================

def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload, timeout=10)

def send_startup_message():
    wallets = "\n".join(f"• `{w}`" for w in MONITORED_WALLETS)

    message = (
        "🟢 *Solana Monitor DEFI iniciado*\n\n"
        f"🕒 *Horário :* `{now_sp()}`\n\n"
        "🪙 *Carteiras monitoradas:*\n"
        f"{wallets}"
    )

    send_telegram_message(message)

# ============================================
# RPC HELPERS
# ============================================

def rpc_post(method, params):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }
    r = requests.post(RPC_HTTP, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()

def fetch_transaction(signature):
    res = rpc_post(
        "getTransaction",
        [signature, {"encoding": "jsonParsed", "commitment": "confirmed"}]
    )
    return res.get("result")

# ============================================
# SWAP DETECTION (heurística simples)
# ============================================

def detect_swap(tx, wallet):
    if not tx:
        return None

    meta = tx.get("meta", {})
    pre = meta.get("preTokenBalances", [])
    post = meta.get("postTokenBalances", [])

    def balances(arr):
        out = {}
        for b in arr:
            if b.get("owner") == wallet:
                out[b["mint"]] = b["uiTokenAmount"]["uiAmount"]
        return out

    pre_map = balances(pre)
    post_map = balances(post)

    changes = []
    for mint, post_amt in post_map.items():
        pre_amt = pre_map.get(mint, 0)
        if pre_amt != post_amt:
            changes.append((mint, pre_amt, post_amt))

    if len(changes) < 2:
        return None

    return {
        "signature": tx["transaction"]["signatures"][0],
        "changes": changes
    }

# ============================================
# WEBSOCKET LISTENER
# ============================================

async def listen_wallet(wallet):
    async with websockets.connect(RPC_WS) as ws:
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [
                {"mentions": [wallet]},
                {"commitment": "confirmed"}
            ]
        }))

        while True:
            msg = json.loads(await ws.recv())

            if msg.get("method") != "logsNotification":
                continue

            signature = msg["params"]["result"].get("signature")
            if not signature:
                continue

            tx = fetch_transaction(signature)
            swap = detect_swap(tx, wallet)

            if swap:
                text = (
                    "🔄 *Possível swap detectado*\n\n"
                    f"👛 Carteira: `{wallet}`\n"
                    f"🕒 Horário (SP): `{now_sp()}`\n"
                    f"🧾 Tx: `{swap['signature']}`"
                )
                send_telegram_message(text)

# ============================================
# MAIN
# ============================================

async def main():
    send_startup_message()
    await asyncio.gather(*(listen_wallet(w) for w in MONITORED_WALLETS))

if __name__ == "__main__":
    asyncio.run(main())