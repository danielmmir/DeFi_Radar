import os
import time
import requests
from datetime import datetime
import pytz
from dotenv import load_dotenv

# =========================
# ENV / CONFIG
# =========================
load_dotenv()

HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

WALLETS = [w.strip() for w in os.getenv("WALLETS").split(",")]

CHECK_INTERVAL = 30  # segundos
SOL_MINT = "So11111111111111111111111111111111111111112"

SP_TZ = pytz.timezone("America/Sao_Paulo")

SEEN_SIGNATURES = set()

# =========================
# TELEGRAM
# =========================
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Erro Telegram:", e)

# =========================
# HELIUS
# =========================
def fetch_transactions(wallet, limit=20):
    url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
    params = {
        "api-key": HELIUS_API_KEY,
        "limit": limit
    }
    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200:
        print("Erro Helius:", r.text)
        return []
    return r.json()

# =========================
# PARSER DE TRADE (DEX-AGNOSTIC)
# =========================
def parse_trade(tx, wallet):
    sol_change = tx.get("nativeBalanceChange", 0)
    token_changes = tx.get("tokenBalanceChanges", [])

    if sol_change == 0 or not token_changes:
        return None

    token = None
    token_amount = 0

    for t in token_changes:
        if t.get("userAccount") != wallet:
            continue

        mint = t.get("mint")
        if mint == SOL_MINT:
            continue

        token = t.get("symbol") or mint[:6]
        token_amount = abs(t.get("amount", 0))
        break

    if not token:
        return None

    trade_type = "BUY" if sol_change < 0 else "SELL"

    return {
        "type": trade_type,
        "token": token,
        "token_amount": token_amount,
        "sol_amount": abs(sol_change),
        "signature": tx.get("signature"),
        "timestamp": tx.get("timestamp"),
        "source": tx.get("source", "UNKNOWN")
    }

# =========================
# FORMATADOR
# =========================
def format_message(trade, wallet):
    ts = datetime.fromtimestamp(trade["timestamp"], SP_TZ).strftime("%d/%m %H:%M:%S")

    return (
        "🔥 <b>Novo trade detectado</b>\n\n"
        f"📍 <b>Carteira:</b>\n<code>{wallet}</code>\n\n"
        f"🔄 <b>Tipo:</b> {trade['type']}\n"
        f"🪙 <b>Token:</b> {trade['token']}\n"
        f"💰 <b>SOL:</b> {trade['sol_amount']:.4f}\n"
        f"📊 <b>Quantidade:</b> {trade['token_amount']:.4f}\n\n"
        f"🧩 <b>Fonte:</b> {trade['source']}\n"
        f"🕒 <b>Horário:</b> {ts}"
    )

# =========================
# STARTUP MESSAGE
# =========================
def send_startup_message():
    now = datetime.now(SP_TZ).strftime("%d/%m %H:%M:%S")
    wallets_text = "\n".join([f"• <code>{w}</code>" for w in WALLETS])

    msg = (
        "✅ <b>Solana Monitor DEFI iniciado</b>\n\n"
        f"🕒 <b>Horário:</b> {now}\n\n"
        "🪙 <b>Carteiras monitoradas:</b>\n"
        f"{wallets_text}"
    )
    send_telegram(msg)

# =========================
# LOOP PRINCIPAL
# =========================
def main():
    send_startup_message()

    while True:
        try:
            for wallet in WALLETS:
                txs = fetch_transactions(wallet)

                for tx in txs:
                    sig = tx.get("signature")
                    if not sig or sig in SEEN_SIGNATURES:
                        continue

                    trade = parse_trade(tx, wallet)
                    if trade:
                        send_telegram(format_message(trade, wallet))

                    SEEN_SIGNATURES.add(sig)

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print("Erro loop principal:", e)
            time.sleep(10)

# =========================
# ENTRYPOINT
# =========================
if __name__ == "__main__":
    main()