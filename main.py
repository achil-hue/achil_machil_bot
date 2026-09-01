import time
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import ccxt

# Данные для уведомлений
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = "1424991373"

# Заглушка веб-сервера для бесплатного тарифа Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")

    def log_message(self, format, *args):
        return

def start_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Подключение к фьючерсам Binance
exchange = ccxt.binance({'options': {'defaultType': 'future'}, 'enableRateLimit': True})
MIN_DROP_PERCENT = 1.00
MAX_DROP_PERCENT = 5.00
CHECK_INTERVAL = 60
LOOKBACK_MINUTES = 10

price_history = {}
last_alert_time = {}

def send_telegram_alert(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Ошибка Telegram: {e}")

def monitor():
    current_time = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] Проверка фьючерсов Binance...")
    try:
        tickers = exchange.fetch_tickers()
    except Exception as e:
        print(f"Ошибка биржи: {e}")
        return

    for symbol, ticker in tickers.items():
        # Подходят все USDT-фьючерсы (формат CCXT: SYMBOL/USDT:USDT)
        if 'USDT' not in symbol or any(b in symbol for b in ['BTC/', 'ETH/', 'USDC/', 'FDUSD/']):
            continue

        last_price = ticker.get('last')
        if not last_price:
            continue

        if symbol not in price_history:
            price_history[symbol] = []

        price_history[symbol].append((current_time, last_price))
        cutoff = current_time - (LOOKBACK_MINUTES * 60)
        price_history[symbol] = [p for p in price_history[symbol] if p[0] >= cutoff]

        if len(price_history[symbol]) < 2:
            continue

        old_time, old_price = price_history[symbol][0]
        percent_change = ((last_price - old_price) / old_price) * 100

        if -MAX_DROP_PERCENT <= percent_change <= -MIN_DROP_PERCENT:
            # Защита от частых повторных алертов по одной монете
            if symbol in last_alert_time and (current_time - last_alert_time[symbol]) < (ALERT_COOLDOWN_MINUTES * 60):
                continue

            drop_abs = abs(percent_change)
            msg = f"🚨 *Binance Futures:* `{symbol}` упал на -{drop_abs:.2f}%\nТекущая цена: `{last_price}`"
            send_telegram_alert(msg)
            last_alert_time[symbol] = current_time

if __name__ == '__main__':
    threading.Thread(target=start_health_check_server, daemon=True).start()
    send_telegram_alert("🚀 Бот (Futures) успешно запущен на Render! Мониторинг 24/7 активен.")
    while True:
        monitor()
        time.sleep(CHECK_INTERVAL)
