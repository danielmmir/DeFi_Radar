import asyncio
import json
import os
import requests
import websockets
from typing import List

# =====================================================
# CONFIGURAÇÕES GERAIS
# =====================================================

RPC_HTTP = "https://api.mainnet-beta.solana.com"
RPC_WS   = "wss://api.mainnet-beta.solana.com"

# Pode monitorar UMA ou VÁRIAS carteiras
TARGET_WALLETS: List[str] = [
    "9wXNBdnGWHHLnzntZVGTU7t1HZMGHiGNZWnrknreueqr",
    "6sjpfFfs28qi5xHi1KVVbwgexGJE4RZvToXPyANeHWKE",
]

# =====================================================
# TELEGRAM (via Secrets do Codespaces)
# =====================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    raise RuntimeError("Telegram secrets não configurados no Codespaces")

TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

def send_telegram(msg: str):
    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        requests.post(TELEGRAM_URL, json=payload, timeout=10)
    except Exception as e:
        print("Erro ao enviar Telegram:", e)

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
# SWAP DETECTOR (heurística)
# =====================================================

def detect_swap(tx: dict, wallet: str):
    if not tx or "meta" not in tx:
        return None

    meta = tx["meta"]
    pre  = meta.get("preTokenBalances", [])
    post = meta.get("postTokenBalances", [])

    def map_balances(arr):
        d = {}
        for b in arr:
            if b.get("owner") == wallet:
                mint = b.get("mint")
                amt = b.get("uiTokenAmount", {}).get("uiAmount", 0)
                d[mint] = amt
        return d

    pre_map  = map_balances(pre)
    post_map = map_balances(post)

    changes = []
    for mint, post_amt in post_map.items():
        pre_amt = pre_map.get(mint, 0)
        if pre_amt != post_amt:
            delta = post_amt - pre_amt
            changes.append((mint, delta))

    if len(changes) < 2:
        return None

    token_out = max(changes, key=lambda x: x[1])
    token_in  = min(changes, key=lambda x: x[1])

    signature = tx["transaction"]["signatures"][0]

    return {
        "wallet": wallet,
        "token_in": token_in[0],
        "amount_in": abs(token_in[1]),
        "token_out": token_out[0],
        "amount_out": token_out[1],
        "signature": signature,
    }

# =====================================================
# WEBSOCKET LISTENER
# =====================================================

async def listen_wallet(wallet: str):
    async with websockets.connect(RPC_WS) as ws:
        sub = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [{"mentions": [wallet]}, {"commitment": "confirmed"}],
        }
        await ws.send(json.dumps(sub))
        print(f"🔍 Monitorando carteira: {wallet}")

        while True:
            msg = json.loads(await ws.recv())

            if msg.get("method") != "logsNotification":
                continue

            signature = msg["params"]["result"].get("signature")
            if not signature:
                continue

            tx = fetch_transaction(signature)
            swap = detect_swap(tx, wallet)

            if not swap:
                continue

            text = (
                f"🔄 *Swap Detectado*\n\n"
                f"👛 Carteira:\n`{swap['wallet']}`\n\n"
                f"📤 Token IN:\n`{swap['token_in']}`\n"
                f"Quantidade: `{swap['amount_in']}`\n\n"
                f"📥 Token OUT:\n`{swap['token_out']}`\n"
                f"Quantidade: `{swap['amount_out']}`\n\n"
                f"🔗 Tx:\nhttps://solscan.io/tx/{swap['signature']}"
            )

            send_telegram(text)
            print("✅ Swap notificado:", signature)

# =====================================================
# MAIN
# =====================================================

async def main():
    tasks = [listen_wallet(w) for w in TARGET_WALLETS]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())

#Para parar de monitorar, control + c