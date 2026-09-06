import json
import pandas as pd
import ccxt
import urllib3
from openai import OpenAI

# Matikan peringatan SSL Warning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. Konfigurasi Client 9Router
client = OpenAI(
    base_url="http://localhost:20128/v1",
    api_key="sk-bdf988d6029ade8f-vr99bs-77414883",
    timeout=30.0  # Batas waktu maksimal 30 detik agar tidak stuck
)

# 2. Fungsi Ambil Data Pasar dengan Multi-Exchange Fallback
def get_market_data(symbol="BTC/USDT", timeframe="15m", limit=50):
    exchanges = [
        ccxt.gate({'verify': False, 'enableRateLimit': True}),
        ccxt.kucoin({'verify': False, 'enableRateLimit': True}),
        ccxt.mexc({'verify': False, 'enableRateLimit': True}),
        ccxt.okx({'verify': False, 'enableRateLimit': True}),
    ]
    
    ohlcv = None
    used_exchange = None
    
    for ex in exchanges:
        try:
            ex.load_markets()
            if symbol in ex.symbols:
                ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                used_exchange = ex.id
                break
        except Exception:
            continue
            
    if not ohlcv:
        raise Exception("Gagal mengambil data dari seluruh provider. Periksa koneksi internet.")
        
    print(f"Berhasil mengambil data dari provider: {used_exchange.upper()}")
    
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['sma_20'] = df['close'].rolling(window=20).mean()
    
    recent_low = float(df['low'].tail(20).min())
    recent_high = float(df['high'].tail(20).max())
    current_price = float(df['close'].iloc[-1])
    last_volume = float(df['volume'].iloc[-1])
    avg_volume = float(df['volume'].tail(20).mean())
    sma_20_val = float(df['sma_20'].iloc[-1])
    
    market_summary = {
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": current_price,
        "support_level": recent_low,
        "resistance_level": recent_high,
        "sma_20": round(sma_20_val, 2),
        "last_volume": last_volume,
        "avg_volume_20": round(avg_volume, 2),
        "volume_status": "ABOVE_AVERAGE" if last_volume > avg_volume else "NORMAL_OR_LOW",
        "trend_sma": "BULLISH" if current_price > sma_20_val else "BEARISH"
    }
    
    return market_summary

# 3. Minta Analisis ke Hermes
def analyze_with_hermes(market_data):
    system_prompt = """
Kamu adalah Hermes Trading Agent. Tugasmu menganalisis data pasar dan memberikan keputusan.
Aturan:
1. Keputusan wajib salah satu dari: BUY, WAIT, atau EXIT.
2. BUY bukan jaminan harga pasti naik.
3. Kembalikan respons HANYA dalam format JSON valid tanpa teks tambahan di luar JSON:
{
  "decision": "BUY/WAIT/EXIT",
  "confidence_score": 0.0-1.0,
  "analysis": {
    "trend": "penjelasan singkat trend",
    "momentum": "penjelasan volume & momentum",
    "support_resistance": "posisi harga terhadap S/R",
    "risk_reward": "penilaian rasio risiko"
  },
  "reasons_for_entry": ["alasan 1", "alasan 2"],
  "reasons_against_entry": ["risiko 1", "risiko 2"],
  "invalidation_condition": "kondisi yang membatalkan analisis"
}
"""

    user_prompt = f"Data pasar terbaru:\n{json.dumps(market_data, indent=2)}\n\nBerikan analisis mendalammu."

    try:
        response = client.chat.completions.create(
            model="openrouter/minimax/minimax-m3:free",  # Ubah jika nama route di 9Router berbeda
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"\n[ERROR 9ROUTER / HERMES]: {str(e)}"

# 4. Eksekusi Utama
if __name__ == "__main__":
    print("Mengambil data pasar real-time...")
    data = get_market_data(symbol="BTC/USDT", timeframe="15m")
    
    print("Mengirim data ke Hermes...")
    result = analyze_with_hermes(data)
    
    print("\n=== HASIL ANALISIS HERMES ===")
    print(result)