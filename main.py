import os
import time
import json
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import websockets

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MIN_DROP_PERCENT = 0.20
MAX_DROP_PERCENT = 50.00
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
        print("ОШИБКА: TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы!", flush=True)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code != 200:
            print(f"Ошибка Telegram API ({r.status_code}): {r.text}", flush=True)
    except Exception as e:
        print(f"Ошибка сети Telegram: {e}", flush=True)

async def binance_ws_listener():
    url = "wss://fstream.binance.com/ws/!miniTicker@arr"
    last_log_time = time.time()
    
    while True:
        try:
            print("Подключение к Binance WebSocket...", flush=True)
            async with websockets.connect(url) as ws:
                send_telegram_alert("⚡ *WebSocket бот запущен!* Анализ просадок от 15-мин максимумов активен.")
                
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    current_time = time.time()

                    # Периодический статус в логи Render раз в 5 минут
                    if current_time - last_log_time > 300:
                        print(f"[{time.strftime('%H:%M:%S')}] WebSocket активен. Анализируются фьючерсы...", flush=True)
                        last_log_time = current_time

                    for item in data:
                        symbol = item.get('s', '')
                        
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

                        # Сравниваем с МАКСИМАЛЬНОЙ ценой за окно в 15 минут
                        max_price = max(p[1] for p in price_history[symbol])
                        percent_change = ((last_price - max_price) / max_price) * 100

                        if -MAX_DROP_PERCENT <= percent_change <= -MIN_DROP_PERCENT:
                            if symbol in last_alert_time and (current_time - last_alert_time[symbol]) < (ALERT_COOLDOWN_MINUTES * 60):
                                continue

                            drop_abs = abs(percent_change)
                            alert_msg = (
                                f"🚨 *Binance Futures:* `{symbol}`\n"
                                f"Падение: *-{drop_abs:.2f}%* от 15-мин пика (`{max_price:.4f}`)\n"
                                f"Текущая цена: `{last_price:.4f}`"
                            )
                            send_telegram_alert(alert_msg)
                            last_alert_time[symbol] = current_time

        except Exception as e:
            print(f"Ошибка WebSocket: {e}. Переподключение через 5 секунд...", flush=True)
            await asyncio.sleep(5)

if __name__ == '__main__':
    threading.Thread(target=start_health_check_server, daemon=True).start()
    asyncio.run(binance_ws_listener())
