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

# Рабочие настройки стратегии
MIN_DROP_PERCENT = 0.80       # Порог падения в % от 15-мин пика
MAX_DROP_PERCENT = 50.00      # Максимальное падение
LOOKBACK_MINUTES = 15         # Окно анализа (минуты)
ALERT_COOLDOWN_MINUTES = 15   # Кулдаун алертов по одной монете

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

async def send_telegram_alert(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ОШИБКА: TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы!", flush=True)
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    def _post():
        # Попытка 1: Отправка с HTML форматированием
        payload_html = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        try:
            r = requests.post(url, json=payload_html, timeout=5)
            if r.status_code == 200:
                return
            print(f"Предупреждение Telegram HTML ({r.status_code}): {r.text}", flush=True)
        except Exception as e:
            print(f"Ошибка сети Telegram: {e}", flush=True)

        # Попытка 2: Резервная отправка без разметки (чистый текст), если HTML был отклонен
        plain_text = text.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
        payload_plain = {"chat_id": TELEGRAM_CHAT_ID, "text": plain_text}
        try:
            requests.post(url, json=payload_plain, timeout=5)
        except Exception as e:
            print(f"Ошибка резервной отправки Telegram: {e}", flush=True)

    await asyncio.to_thread(_post)

async def binance_ws_listener():
    url = "wss://fstream.binance.com/ws/!miniTicker@arr"
    last_log_time = time.time()
    
    while True:
        try:
            print("Подключение к Binance WebSocket...", flush=True)
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                await send_telegram_alert("⚡ <b>WebSocket бот успешно запущен!</b> Мониторинг просадок активен 24/7.")
                
                while True:
                    msg = await ws.recv()
                    
                    try:
                        data = json.loads(msg)
                    except Exception:
                        continue

                    if not isinstance(data, list):
                        continue

                    current_time = time.time()

                    if current_time - last_log_time > 600:
                        print(f"[{time.strftime('%H:%M:%S')}] WebSocket активен. Монет в отслеживании: {len(price_history)}", flush=True)
                        last_log_time = current_time

                    for item in data:
                        if not isinstance(item, dict):
                            continue

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

                        max_price = max(p[1] for p in price_history[symbol])
                        percent_change = ((last_price - max_price) / max_price) * 100

                        if -MAX_DROP_PERCENT <= percent_change <= -MIN_DROP_PERCENT:
                            if symbol in last_alert_time and (current_time - last_alert_time[symbol]) < (ALERT_COOLDOWN_MINUTES * 60):
                                continue

                            drop_abs = abs(percent_change)
                            alert_msg = (
                                f"🚨 <b>Binance Futures:</b> <code>{symbol}</code>\n"
                                f"Падение: <b>-{drop_abs:.2f}%</b> от пика (<code>{max_price:.4f}</code>)\n"
                                f"Текущая цена: <code>{last_price:.4f}</code>"
                            )
                            last_alert_time[symbol] = current_time
                            asyncio.create_task(send_telegram_alert(alert_msg))

        except Exception as e:
            print(f"Ошибка WebSocket: {e}. Переподключение через 5 секунд...", flush=True)
            await asyncio.sleep(5)

if __name__ == '__main__':
    threading.Thread(target=start_health_check_server, daemon=True).start()
    asyncio.run(binance_ws_listener())
