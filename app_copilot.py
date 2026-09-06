import streamlit as st
import ccxt
import json
import time
import pandas as pd
from openai import OpenAI

# Konfigurasi Halaman
st.set_page_config(page_title="Hermes AI Copilot", layout="wide")

# 1. Inisialisasi Market Data Provider (Kraken - Bebas Blokir Cloud)
@st.cache_resource
def get_exchange():
    return ccxt.kraken({'enableRateLimit': True})

market_exchange = get_exchange()

ai_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=st.secrets["OPENROUTER_API_KEY"]
)

# State Storage
if "position" not in st.session_state:
    st.session_state.position = None
if "logs" not in st.session_state:
    st.session_state.logs = []

# 2. Ambil Data Pasar dari Kraken
def get_market_data():
    ohlcv = market_exchange.fetch_ohlcv("BTC/USDT", timeframe="15m", limit=30)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['sma_20'] = df['close'].rolling(window=20).mean()
    current_price = float(df['close'].iloc[-1])
    return {
        "symbol": "BTC/USDT",
        "current_price": current_price,
        "support": float(df['low'].min()),
        "resistance": float(df['high'].max()),
        "sma_20": float(df['sma_20'].iloc[-1]),
        "last_volume": float(df['volume'].iloc[-1]),
        "avg_volume": float(df['volume'].mean())
    }

# 3. Analisis AI Guardrail
def check_with_ai(market_data, action_intent):
    prompt = f"""
User ingin melakukan aksi: {action_intent}
Data Pasar saat ini:
{json.dumps(market_data, indent=2)}

Aturan:
Evaluasi apakah aksi {action_intent} ini AMAN/BAGUS dilakukan saat ini.
Kembalikan JSON persis seperti ini (tanpa markdown):
{{
  "allow": true/false,
  "reason": "alasan analisis mendalam"
}}
"""
    try:
        res = ai_client.chat.completions.create(
            model="minimax/minimax-m3:free",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        cleaned = res.choices[0].message.content.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception as e:
        return {"allow": False, "reason": f"AI Error/Timeout: {str(e)}"}

# TAMPILAN DASHBOARD
st.title("🤖 Hermes AI Trading Copilot & Risk Guardrail")
st.caption("Mode: Cloud Live Interceptor")

try:
    market = get_market_data()
    
    # Metrics Header
    col1, col2, col3 = st.columns(3)
    col1.metric("Harga BTC/USDT", f"${market['current_price']:,.2f}")
    col2.metric("Status Server", "Online (Cloud Ready)")
    pos_status = "KOSONG" if not st.session_state.position else f"BOUGHT @ ${st.session_state.position['entry']:,.2f}"
    col3.metric("Status Posisi", pos_status)

    st.divider()

    # KONTROL MANUAL DENGAN INTERCEPTOR AI
    st.subheader("🎯 Panel Eksekusi Manual (Di-intercept AI)")
    c_buy, c_sell = st.columns(2)

    if c_buy.button("🟢 TEKAN BUY BTC ($50 USDT)", use_container_width=True):
        with st.spinner("AI sedang menganalisis kondisi pasar sebelum eksekusi..."):
            ai_eval = check_with_ai(market, "BUY")
            
            if ai_eval["allow"]:
                qty = 50.0 / market['current_price']
                st.session_state.position = {"entry": market['current_price'], "qty": qty}
                st.success(f"✅ **ORDER DISETUJUI & DIEKSEKUSI!**\n\n**Alasan AI:** {ai_eval['reason']}")
                st.session_state.logs.append(f"[{time.strftime('%H:%M:%S')}] BUY EXEC: {ai_eval['reason']}")
            else:
                st.error(f"🛑 **ORDER DITAHAN OLEH AI! (Analisis Buruk)**\n\n**Alasan AI:** {ai_eval['reason']}")
                st.session_state.logs.append(f"[{time.strftime('%H:%M:%S')}] BUY BLOCKED: {ai_eval['reason']}")

    if c_sell.button("🔴 TEKAN CUT LOSS / SELL MANUAL", use_container_width=True):
        if st.session_state.position:
            st.session_state.position = None
            st.info("Posisi ditutup manual.")
        else:
            st.warning("Tidak ada posisi aktif.")

    # AUTO-GUARDIAN BACKGROUND CHECK
    if st.session_state.position:
        st.divider()
        st.subheader("🛡️ AI Auto-Guardian (Monitoring Pola Aktif)")
        with st.spinner("AI memantau kerusakan pola pasar..."):
            ai_exit_check = check_with_ai(market, "EVALUATE_HOLD_POSITION")
            if not ai_exit_check["allow"]:
                st.session_state.position = None
                st.error(f"🚨 **POLA PASAR JELEK! AI OTOMATIS TUKAR KE STOP/SELL!**\n\n**Alasan AI:** {ai_exit_check['reason']}")
                st.session_state.logs.append(f"[{time.strftime('%H:%M:%S')}] AUTO-EXIT: {ai_exit_check['reason']}")

    # LOGS PANEL
    st.divider()
    st.subheader("📜 System Logs")
    for l in reversed(st.session_state.logs):
        st.text(l)

except Exception as err:
    st.error(f"Gagal memuat data pasar: {str(err)}")