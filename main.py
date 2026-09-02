import os
import time
import json
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import websockets

# Переменные окружения из панели Render
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Настройки стратегии
MIN_DROP_PERCENT = 1.00
MAX_DROP_PERCENT = 5.00
LOOKBACK_MINUTES = 15
ALERT_COOLDOWN_MINUTES = 15

price_history = {}
last_alert_time = {}

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot status: OK")

    def log_message(self, format, *args):
        return

def start_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

def send_telegram_alert(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ОШИБКА: TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code != 200:
            print(f"Ошибка Telegram API ({r.status_code}): {r.text}")
    except Exception as e:
        print(f"Ошибка сети Telegram: {e}")

async def binance_ws_listener():
    # Поток со всеми мини-тиками фьючерсов Binance
    url = "wss://fstream.binance.com/ws/!miniTicker@arr"
    
    while True:
        try:
            print("Подключение к Binance WebSocket...")
            async with websockets.connect(url) as ws:
                send_telegram_alert("⚡ *WebSocket бот успешно запущен!* Прямой поток цен Binance активен 24/7 без лимитов.")
                
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    current_time = time.time()

                    for item in data:
                        symbol = item.get('s', '')
                        
                        # Фильтр: только USDT фьючерсы без основных монет
                        if not symbol.endswith('USDT') or any(b in symbol for b in ['BTCUSDT', 'ETHUSDT', 'USDCUSDT', 'FDUSDUSDT']):
                            continue

                        try:
                            last_price = float(item.get('c', 0))
                        except (ValueError, TypeError):
                            continue

                        if last_price <= 0:
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
                            if symbol in last_alert_time and (current_time - last_alert_time[symbol]) < (ALERT_COOLDOWN_MINUTES * 60):
                                continue

                            drop_abs = abs(percent_change)
                            alert_msg = f"🚨 *Binance Futures:* `{symbol}` упал на -{drop_abs:.2f}%\nТекущая цена: `{last_price}`"
                            send_telegram_alert(alert_msg)
                            last_alert_time[symbol] = current_time

        except Exception as e:
            print(f"Ошибка WebSocket: {e}. Переподключение через 5 секунд...")
            await asyncio.sleep(5)

if __name__ == '__main__':
    threading.Thread(target=start_health_check_server, daemon=True).start()
    asyncio.run(binance_ws_listener())
