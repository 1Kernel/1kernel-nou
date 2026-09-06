import json
import os
import time
import pandas as pd
import ccxt
import urllib3
import requests
from openai import OpenAI

# Matikan warning SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Konfigurasi Telegram
TELEGRAM_BOT_TOKEN = "8629341568:AAE8HdxgjE_RKIzsSNnpN3YAD5V3zNHWs0g"
TELEGRAM_CHAT_ID = "7065697546"

# Inisialisasi Binance Testnet API
exchange = ccxt.binance({
    'apiKey': 'zjC7OoNkjoYN7mRiD60pPEhUKPgy6gLVy9374KdoG2pToknJKiXT3Il5FgOSMFt0',
    'secret': 'gxIpBeuxicV6bUWpI5xSA9fl2Tgm7Z4gWeCaYB3RPtHmmDTc3l0IOrIP8xelB8eH',
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})
exchange.set_sandbox_mode(True)  # Wajib True untuk mengarahkan ke Testnet server

# Configuration Risk Engine
STATE_FILE = "live_position_state.json"
HARD_STOP_LOSS_PCT = 0.015
HARD_TAKE_PROFIT_PCT = 0.030
CHECK_INTERVAL_SECONDS = 60
LAST_UPDATE_ID = 0

client = OpenAI(
    base_url="http://localhost:20128/v1",
    api_key="sk-bdf988d6029ade8f-vr99bs-77414883",
    timeout=30.0,  # Dinaikkan dari 10.0 ke 30.0 detik
    max_retries=2
)

# 1. Telegram Service
def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"  [ERROR TELEGRAM]: {str(e)}")

# 2. Local State Manager untuk Mengunci Metadata Risk Engine (SL/TP)
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"position": None}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)

# 3. Query Saldo Riil dari Binance Testnet
def get_exchange_balances():
    balance = exchange.fetch_balance()
    usdt = float(balance['free'].get('USDT', 0))
    btc = float(balance['free'].get('BTC', 0))
    return usdt, btc

# 4. Listener Perintah Telegram
def check_telegram_commands():
    global LAST_UPDATE_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"offset": LAST_UPDATE_ID + 1, "timeout": 1}
    
    try:
        response = requests.get(url, params=params, timeout=2).json()
        if response.get("ok"):
            for update in response.get("result", []):
                LAST_UPDATE_ID = update["update_id"]
                message = update.get("message", {})
                text = message.get("text", "").strip().lower()
                chat_id = str(message.get("chat", {}).get("id"))
                
                if chat_id == TELEGRAM_CHAT_ID:
                    usdt, btc = get_exchange_balances()
                    state = load_state()
                    pos = state.get("position")
                    
                    if text in ["/status", "/saldo", "/portfolio"]:
                        pos_info = "KOSONG" if not pos else f"BOUGHT @ ${pos['entry_price']:,.2f} | Amount: {pos['btc_qty']:.5f} BTC"
                        reply = (
                            f"🌐 *BINANCE TESTNET PORTOFOLIO*\n\n"
                            f"• *Saldo USDT Free*: ${usdt:,.2f}\n"
                            f"• *Saldo BTC Free*: {btc:.5f} BTC\n"
                            f"• *Status Posisi Bot*: {pos_info}"
                        )
                        send_telegram(reply)
                    elif text in ["/start", "/help"]:
                        reply = (
                            "🤖 *HERMES BINANCE TESTNET BOT*\n\n"
                            "• `/status` atau `/saldo` - Cek saldo Testnet & posisi aktif\n"
                            "• `/help` - Bantuan"
                        )
                        send_telegram(reply)
    except Exception:
        pass

# 5. Fetch Market Data dari Binance Testnet
def get_market_data(symbol="BTC/USDT", timeframe="15m", limit=50):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['sma_20'] = df['close'].rolling(window=20).mean()
    
    current_price = float(df['close'].iloc[-1])
    recent_low = float(df['low'].tail(20).min())
    recent_high = float(df['high'].tail(20).max())
    last_volume = float(df['volume'].iloc[-1])
    avg_volume = float(df['volume'].tail(20).mean())
    sma_20_val = float(df['sma_20'].iloc[-1])
    
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "exchange_provider": "BINANCE_TESTNET",
        "current_price": current_price,
        "support_level": recent_low,
        "resistance_level": recent_high,
        "sma_20": round(sma_20_val, 2),
        "last_volume": last_volume,
        "avg_volume_20": round(avg_volume, 2),
        "volume_status": "ABOVE_AVERAGE" if last_volume > avg_volume else "NORMAL_OR_LOW",
        "trend_sma": "BULLISH" if current_price > sma_20_val else "BEARISH"
    }

# 6. Hermes AI Decision
def analyze_with_hermes(market_data, current_position=None):
    system_prompt = """
Kamu adalah Hermes Trading Agent. Analisis pasar dan berikan keputusan trading.
Aturan:
1. Keputusan WAJIB salah satu: BUY, WAIT, atau EXIT.
2. Kembalikan respons HANYA format JSON valid tanpa tanda markdown (```json):
{
  "decision": "BUY/WAIT/EXIT",
  "confidence_score": 0.8,
  "analysis_reason": "alasan singkat"
}
"""
    prompt_payload = {"market_data": market_data, "current_position": current_position}
    print("  [INFO] Mengirim data ke Hermes AI... Mohon tunggu...")
    
    try:
        response = client.chat.completions.create(
            model="openrouter/minimax/minimax-m3:free",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Data saat ini:\n{json.dumps(prompt_payload, indent=2)}"}
            ],
            temperature=0.2
        )
        raw_text = response.choices[0].message.content
        cleaned_text = raw_text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned_text)
    except Exception as e:
        print(f"  [ERROR AI]: {str(e)}")
        return {"decision": "WAIT", "analysis_reason": f"Fallback error: {str(e)}"}

# 7. Eksekusi Order Riil di Binance Testnet
def execute_testnet_buy(symbol, usdt_amount, price, reason):
    try:
        btc_qty = usdt_amount / price
        # Kirim Market Buy Order ke Binance Testnet
        order = exchange.create_market_buy_order(symbol, btc_qty)
        
        executed_qty = float(order.get('filled', btc_qty))
        hard_sl = price * (1 - HARD_STOP_LOSS_PCT)
        hard_tp = price * (1 + HARD_TAKE_PROFIT_PCT)
        
        state = {
            "position": {
                "symbol": symbol,
                "entry_price": price,
                "btc_qty": executed_qty,
                "invested_usdt": usdt_amount,
                "hard_stop_loss": hard_sl,
                "hard_take_profit": hard_tp,
                "order_id": order.get('id')
            }
        }
        save_state(state)
        
        msg = (
            f"🟢 *BINANCE TESTNET BUY ORDER EXECUTED*\n\n"
            f"• Asset: {symbol}\n"
            f"• Entry Price: ${price:,.2f}\n"
            f"• Filled Qty: {executed_qty:.5f} BTC\n"
            f"• Invested: ${usdt_amount:.2f} USDT\n"
            f"• Stop Loss: ${hard_sl:,.2f} (-1.5%)\n"
            f"• Take Profit: ${hard_tp:,.2f} (+3.0%)\n"
            f"• Alasan: {reason}"
        )
        print(msg)
        send_telegram(msg)
    except Exception as e:
        print(f"  [ERROR TESTNET BUY]: {str(e)}")

def execute_testnet_sell(symbol, exit_price, reason):
    state = load_state()
    pos = state.get("position")
    if not pos:
        return
        
    try:
        btc_qty = pos['btc_qty']
        # Kirim Market Sell Order ke Binance Testnet
        order = exchange.create_market_sell_order(symbol, btc_qty)
        
        pnl_usdt = (exit_price - pos['entry_price']) * btc_qty
        pnl_pct = ((exit_price - pos['entry_price']) / pos['entry_price']) * 100
        
        state["position"] = None
        save_state(state)
        
        usdt, _ = get_exchange_balances()
        status_icon = "🔴" if pnl_usdt < 0 else "🟢"
        msg = (
            f"{status_icon} *BINANCE TESTNET POSITION CLOSED*\n\n"
            f"• Exit Price: ${exit_price:,.2f}\n"
            f"• PnL: ${pnl_usdt:+.4f} USDT ({pnl_pct:+.2f}%)\n"
            f"• Alasan: {reason}\n"
            f"• Saldo USDT Free Saat Ini: ${usdt:,.2f}"
        )
        print(msg)
        send_telegram(msg)
    except Exception as e:
        print(f"  [ERROR TESTNET SELL]: {str(e)}")

# 8. Main Loop Tick
def run_live_tick():
    usdt_bal, btc_bal = get_exchange_balances()
    market = get_market_data()
    price = market['current_price']
    state = load_state()
    pos = state.get("position")
    
    pos_status = "KOSONG" if not pos else f"BOUGHT @ ${pos['entry_price']:,.2f}"
    
    print(f"\n[{time.strftime('%H:%M:%S')}] Pengecekan Binance Testnet...")
    print("==================================================")
    print(f"Harga BTC/USDT : ${price:,.2f}")
    print(f"Saldo Free USDT: ${usdt_bal:,.2f} USDT")
    print(f"Saldo Free BTC : {btc_bal:.5f} BTC")
    print(f"Status Posisi  : {pos_status}")
    print("==================================================")
    
    if pos:
        entry = pos['entry_price']
        if price <= pos['hard_stop_loss']:
            execute_testnet_sell(market['symbol'], price, "HARD_STOP_LOSS")
            return
        if price >= pos['hard_take_profit']:
            execute_testnet_sell(market['symbol'], price, "HARD_TAKE_PROFIT")
            return
            
        ai_res = analyze_with_hermes(market, pos)
        print(f"[HERMES DECISION]: {ai_res['decision']} | Reason: {ai_res.get('analysis_reason')}")
        
        if ai_res['decision'] == "EXIT":
            execute_testnet_sell(market['symbol'], price, f"HERMES_EXIT ({ai_res.get('analysis_reason')})")
    else:
        ai_res = analyze_with_hermes(market)
        print(f"[HERMES DECISION]: {ai_res['decision']} | Reason: {ai_res.get('analysis_reason')}")
        
        if ai_res['decision'] == "BUY":
            trade_amount_usdt = min(50.0, usdt_bal)
            if trade_amount_usdt < 10.0:
                print("Saldo USDT di Binance Testnet tidak mencukupi untuk entri.")
                return
            execute_testnet_buy(market['symbol'], trade_amount_usdt, price, ai_res.get('analysis_reason'))

# 9. Execution Routine
if __name__ == "__main__":
    print("==================================================")
    print("Memulai Bot Trading Live - Binance Testnet Server")
    print("==================================================")
    
    # Tes Koneksi Awal
    try:
        u_bal, b_bal = get_exchange_balances()
        print(f"[SUCCESS] Terhubung ke Binance Testnet! Saldo: ${u_bal:,.2f} USDT")
        send_telegram("🚀 *Hermes Binance Testnet Bot Online!* Siap melakukan eksekusi order.")
    except Exception as err:
        print(f"[ERROR KONEKSI API]: {str(err)}")
        exit()

    try:
        while True:
            run_live_tick()
            for _ in range(CHECK_INTERVAL_SECONDS):
                check_telegram_commands()
                time.sleep(1)
    except KeyboardInterrupt:
        send_telegram("🛑 *Hermes Binance Testnet Bot Offline!*")
        print("\n[STOP] Bot dihentikan.")