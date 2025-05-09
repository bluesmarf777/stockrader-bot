
import yfinance as yf
import pandas as pd
import requests
import json
from datetime import datetime
from telegram import Bot
import asyncio
import logging
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import utc
import os

# 설정
logging.basicConfig(level=logging.INFO)
TOKEN = "7958883184:AAF3Q4WBjShZZZu4KMPFGiZe_vIBVDA_C_8"
CHAT_ID = 7631224187
bot = Bot(token=TOKEN)
app = FastAPI()
scheduler = AsyncIOScheduler(timezone=utc)

PRICE_FILE = "coin_prices.json"

def save_coin_prices(prices):
    try:
        with open(PRICE_FILE, "w") as f:
            json.dump(prices, f)
    except Exception as e:
        print("가격 저장 실패:", e)

def load_coin_prices():
    if os.path.exists(PRICE_FILE):
        try:
            with open(PRICE_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def get_korean_stocks():
    try:
        url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download"
        df = pd.read_html(url, header=0)[0]
        df = df[['회사명', '종목코드']]
        df['종목코드'] = df['종목코드'].astype(str).str.zfill(6)
        return {row['회사명']: row['종목코드'] for _, row in df.iterrows()}
    except:
        return {}

def load_us_name_to_code():
    try:
        nasdaq = pd.read_csv("https://raw.githubusercontent.com/datasets/nasdaq-listings/master/data/nasdaq-listed-symbols.csv")
        nyse = pd.read_csv("https://raw.githubusercontent.com/datasets/nyse-listed-symbols/master/data/nyse-listed.csv")
        combined = pd.concat([nasdaq, nyse])
        return {row['Company Name']: row['Symbol'] for _, row in combined.iterrows()}
    except:
        return {}

krx_name_to_code = get_korean_stocks()
us_name_to_code = load_us_name_to_code()

def is_jump_stock(ticker):
    try:
        data = yf.download(ticker, period="6d", interval="1d", progress=False)
        if data.shape[0] < 6:
            return None
        close_today = data['Close'].iloc[-1]
        close_yesterday = data['Close'].iloc[-2]
        rate = ((close_today - close_yesterday) / close_yesterday) * 100
        avg_vol = data['Volume'].iloc[-6:-1].mean()
        today_vol = data['Volume'].iloc[-1]
        amount = close_today * today_vol

        reasons = []
        if rate >= 15:
            reasons.append("폭등률")
        if today_vol >= avg_vol * 3:
            reasons.append("거래량")
        if amount >= 1e11:
            reasons.append("거래대금")

        if reasons:
            return f"{ticker} +{rate:.2f}% ({', '.join(reasons)})"
        return None
    except:
        return None

def analyze_upbit():
    try:
        m_url = "https://api.upbit.com/v1/market/all"
        t_url = "https://api.upbit.com/v1/ticker?markets="
        markets = requests.get(m_url).json()
        krw = [m['market'] for m in markets if m['market'].startswith("KRW-")]
        current = {coin['market']: coin['trade_price'] for coin in requests.get(t_url + ",".join(krw)).json()}

        prev = load_coin_prices()
        save_coin_prices(current)

        if not prev:
            return "이전 데이터 없음 (초기 수집 중)"

        result = {
            "+10% 이상": [], "+5~+10%": [], "+3~+5%": [],
            "-3~-5%": [], "-5~-10%": [], "-10% 이하": []
        }

        for market, now_price in current.items():
            if market not in prev:
                continue
            before = prev[market]
            if before == 0:
                continue
            change = ((now_price - before) / before) * 100
            name = market.split("-")[1]
            if change >= 10: result["+10% 이상"].append(name)
            elif 5 <= change < 10: result["+5~+10%"].append(name)
            elif 3 <= change < 5: result["+3~+5%"].append(name)
            elif -5 < change <= -3: result["-3~-5%"].append(name)
            elif -10 < change <= -5: result["-5~-10%"].append(name)
            elif change <= -10: result["-10% 이하"].append(name)

        return result
    except Exception as e:
        return f"코인 분석 오류: {e}"

async def send_alert():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] send_alert 작동 시작")

    msg = "[📊 StockRadar 자동 알림]\n\n"

    krx_jump = [res for t in [f"{code}.KS" for code in krx_name_to_code.values()] if (res := is_jump_stock(t))]
    msg += "🇰🇷 한국 급등 종목\n" + ("\n".join(krx_jump) if krx_jump else "없음") + "\n\n"

    us_jump = [res for t in us_name_to_code.values() if (res := is_jump_stock(t))]
    msg += "🇺🇸 미국 급등 종목\n" + ("\n".join(us_jump) if us_jump else "없음") + "\n\n"

    coins = analyze_upbit()
    msg += "🪙 코인 10분간 급등/급락\n"
    if isinstance(coins, dict):
        for k, v in coins.items():
            if v:
                msg += f"{k}: {', '.join(v[:5])}\n"
    else:
        msg += coins  # 오류 메시지나 초기화 상태

    try:
        bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        print("텔레그램 전송 오류:", e)

@app.get("/")
async def root():
    return {"message": "StockRadar bot is running."}

@app.get("/start")
async def trigger_alert():
    await send_alert()
    return {"message": "Alert sent manually."}

@app.on_event("startup")
async def startup_event():
    scheduler.add_job(lambda: asyncio.create_task(send_alert()), 'interval', minutes=10)
    scheduler.start()
    print("스케줄러 시작됨")
