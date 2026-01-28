import os
import time
import requests
from datetime import datetime
from dotenv import load_dotenv
import pytz

# =====================================================
# CONFIG
# =====================================================

load_dotenv()

HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

WALLETS = [
    "HfrBNatNwzSNxhW6yPNsiLitDzgsHw6y2s8o7bJXAYf6",
    "9wXNBdnGWHHLnzntZVGTU7t1HZMGHiGNZWnrknreueqr",
]

CHECK_INTERVAL = 120  # segundos
TX_LIMIT = 5          # ECONÔMICO
BACKOFF_TIME = 600    # 10 min se estourar limite

BRT = pytz.timezone("America/Sao_Paulo")

HELIUS_URL = "https://api.helius.xyz/v0/addresses/{wallet}/transactions"

# =====================================================
# UTILS
# =====================================================

def now_brt():
    return datetime.now(BRT).strftime("%d/%m %H:%M:%S")

def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload, timeout=10)

def get_sol_price():
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
# CORE
# =====================================================

def fetch_transactions(wallet, before=None):
    params = {
        "api-key": HELIUS_API_KEY,
        "limit": TX_LIMIT
    }
    if before:
        params["before"] = before

    r = requests.get(HELIUS_URL.format(wallet=wallet), params=params, timeout=20)

    if r.status_code == 429 or "max usage" in r.text.lower():
        raise RuntimeError("RATE_LIMIT")

    r.raise_for_status()
    return r.json()

def parse_swap(tx):
    if tx.get("type") != "SWAP":
        return None

    source = tx.get("source", "").upper()
    transfers = tx.get("tokenTransfers", [])

    sol_in = 0
    sol_out = 0
    token_in = None
    token_out = None

    for t in transfers:
        mint = t.get("mint")
        amount = t.get("tokenAmount", 0)

        if mint == "So11111111111111111111111111111111111111112":
            if t.get("toUserAccount"):
                sol_out += amount
            else:
                sol_in += amount
        else:
            if not token_in:
                token_in = mint
            else:
                token_out = mint

    sol_amount = max(sol_in, sol_out)

    return {
        "dex": source,
        "sol": sol_amount,
        "token_in": token_in,
        "token_out": token_out,
        "signature": tx.get("signature"),
        "timestamp": tx.get("timestamp")
    }

# =====================================================
# MAIN LOOP
# =====================================================

def main():
    last_signature = {w: None for w in WALLETS}

    send_telegram(
        f"🟢 *Bot iniciado*\n"
        f"🕒 {now_brt()}\n"
        f"📡 Monitorando {len(WALLETS)} carteira(s)"
    )

    while True:
        sol_price = get_sol_price()

        for wallet in WALLETS:
            try:
                txs = fetch_transactions(wallet, last_signature[wallet])

                if not txs:
                    continue

                for tx in reversed(txs):
                    last_signature[wallet] = tx["signature"]

                    swap = parse_swap(tx)
                    if not swap:
                        continue

                    usd = (
                        f"${swap['sol'] * sol_price:.2f}"
                        if sol_price else "N/A"
                    )

                    msg = (
                        f"🔄 *Novo Swap*\n"
                        f"DEX: `{swap['dex']}`\n"
                        f"SOL: `{swap['sol']:.4f}` (~{usd})\n"
                        f"🕒 {now_brt()}\n"
                        f"[Solscan](https://solscan.io/tx/{swap['signature']})"
                    )

                    send_telegram(msg)

            except RuntimeError:
                send_telegram("⚠️ *Rate limit atingido*. Entrando em backoff.")
                time.sleep(BACKOFF_TIME)

            except Exception as e:
                send_telegram(f"❌ Erro: `{str(e)}`")

        time.sleep(CHECK_INTERVAL)

# =====================================================
# ENTRY
# =====================================================

if __name__ == "__main__":
    main()