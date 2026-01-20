import asyncio
import json
import os
import requests
import websockets
from typing import List
from datetime import datetime
from dotenv import load_dotenv

# =====================================================
# LOAD ENV
# =====================================================

load_dotenv()

# =====================================================
# CONFIGURAÇÕES
# =====================================================

RPC_HTTP = "https://api.mainnet-beta.solana.com"
RPC_WS   = "wss://api.mainnet-beta.solana.com"

TARGET_WALLETS: List[str] = [
    "9wXNBdnGWHHLnzntZVGTU7t1HZMGHiGNZWnrknreueqr",
    "HfrBNatNwzSNxhW6yPNsiLitDzgsHw6y2s8o7bJXAYf6",
]

# =====================================================
# TELEGRAM
# =====================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    raise RuntimeError("❌ Variáveis TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não encontradas no .env")

TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

def send_telegram(message: str):
    requests.post(
        TELEGRAM_URL,
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        },
        timeout=10
    )

# =====================================================
# STARTUP MESSAGE
# =====================================================

def send_startup_message():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    wallets_text = "\n".join([f"• `{w}`" for w in TARGET_WALLETS])

    message = (
        "🟢 *Solana DeFi Monitor iniciado*\n\n"
        f"⏱ *Horário:* {now}\n\n"
        "👛 *Carteiras monitoradas:*\n"
        f"{wallets_text}\n\n"
        "_Bot está online e aguardando swaps..._"
    )

    send_telegram(message)

# =====================================================
# PREÇO SOL (USD)
# =====================================================

def get_sol_price_usd():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "solana", "vs_currencies": "usd"},
            timeout=10
        )
        return r.json()["solana"]["usd"]
    except:
        return None

# =====================================================
# RPC HELPERS
# =====================================================

def rpc_post(method: str, params: list):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(RPC_HTTP, json=payload, timeout=15)
    r.raise_for_status()
    return r.json().get("result")

def fetch_transaction(signature: str):
    return rpc_post(
        "getTransaction",
        [signature, {"encoding": "jsonParsed", "commitment": "confirmed"}]
    )

# =====================================================
# SWAP DETECTION
# =====================================================

def detect_swap(tx: dict, wallet: str):
    meta = tx.get("meta")
    if not meta:
        return None

    def map_balances(arr):
        d = {}
        for b in arr:
            if b.get("owner") == wallet:
                mint = b["mint"]
                amt  = b["uiTokenAmount"]["uiAmount"] or 0
                d[mint] = amt
        return d

    pre  = map_balances(meta.get("preTokenBalances", []))
    post = map_balances(meta.get("postTokenBalances", []))

    deltas = []
    for mint, post_amt in post.items():
        pre_amt = pre.get(mint, 0)
        if pre_amt != post_amt:
            deltas.append((mint, post_amt - pre_amt))

    if len(deltas) < 2:
        return None

    token_out = max(deltas, key=lambda x: x[1])
    token_in  = min(deltas, key=lambda x: x[1])

    return {
        "wallet": wallet,
        "token_in": token_in[0],
        "amount_in": abs(token_in[1]),
        "token_out": token_out[0],
        "amount_out": token_out[1],
        "signature": tx["transaction"]["signatures"][0],
    }

# =====================================================
# WEBSOCKET LISTENER
# =====================================================

async def listen_wallet(wallet: str):
    async with websockets.connect(RPC_WS) as ws:
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [{"mentions": [wallet]}, {"commitment": "confirmed"}],
        }))

        print("🔍 Monitorando carteira:", wallet)

        while True:
            msg = json.loads(await ws.recv())
            if msg.get("method") != "logsNotification":
                continue

            sig = msg["params"]["result"].get("signature")
            if not sig:
                continue

            tx = fetch_transaction(sig)
            swap = detect_swap(tx, wallet)
            if not swap:
                continue

            sol_price = get_sol_price_usd()

            usd_in  = swap["amount_in"]  * sol_price if sol_price else None
            usd_out = swap["amount_out"] * sol_price if sol_price else None

            text = (
                f"🔄 *Swap DeFi Detectado*\n\n"
                f"👛 `{wallet}`\n\n"
                f"📤 Token IN:\n`{swap['token_in']}`\n"
                f"Qtd: `{swap['amount_in']:.6f}` SOL\n"
                f"≈ `${usd_in:.2f}` USD\n\n"
                f"📥 Token OUT:\n`{swap['token_out']}`\n"
                f"Qtd: `{swap['amount_out']:.6f}` SOL\n"
                f"≈ `${usd_out:.2f}` USD\n\n"
                f"🔗 https://solscan.io/tx/{swap['signature']}"
            )

            send_telegram(text)
            print("✅ Swap notificado:", sig)

# =====================================================
# MAIN
# =====================================================

async def main():
    send_startup_message()  # 👈 mensagem enviada AO INICIAR
    await asyncio.gather(*(listen_wallet(w) for w in TARGET_WALLETS))

if __name__ == "__main__":
    asyncio.run(main())