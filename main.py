
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from telegram import Bot
import asyncio
import logging
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import utc

# 설정
logging.basicConfig(level=logging.INFO)
TOKEN = "7958883184:AAF3Q4WBjShZZZu4KMPFGiZe_vIBVDA_C_8"
CHAT_ID = 7631224187
bot = Bot(token=TOKEN)
app = FastAPI()
scheduler = AsyncIOScheduler(timezone=utc)

# 한국 주식 목록
def get_korean_stocks():
    try:
        url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download"
        df = pd.read_html(url, header=0)[0]
        df = df[['회사명', '종목코드']]
        df['종목코드'] = df['종목코드'].astype(str).str.zfill(6)
        return {row['회사명']: row['종목코드'] for _, row in df.iterrows()}
    except:
        return {}

krx_name_to_code = get_korean_stocks()

# 미국 주식 목록
def load_us_name_to_code():
    try:
        nasdaq = pd.read_csv("https://raw.githubusercontent.com/datasets/nasdaq-listings/master/data/nasdaq-listed-symbols.csv")
        nyse = pd.read_csv("https://raw.githubusercontent.com/datasets/nyse-listed-symbols/master/data/nyse-listed.csv")
        combined = pd.concat([nasdaq, nyse])
        return {row['Company Name']: row['Symbol'] for _, row in combined.iterrows()}
    except:
        return {}

us_name_to_code = load_us_name_to_code()

# 급등 판단
def is_jump_stock(ticker):
    try:
        data = yf.download(ticker, period="6d", interval="1d", progress=False)
        if data.shape[0] < 6:
            return None
        close_today = data['Close'].iloc[-1]
        close_yesterday = data['Close'].iloc[-2]
        rate = ((close_today - close_yesterday) / close_yesterday) * 100
        if rate < 15:
            return None
        avg_vol = data['Volume'].iloc[-6:-1].mean()
        today_vol = data['Volume'].iloc[-1]
        if today_vol < avg_vol * 3:
            return None
        amount = close_today * today_vol
        if amount < 1e11:
            return None
        return f"{ticker} +{rate:.2f}%"
    except:
        return None

# 업비트 분석
def analyze_upbit():
    try:
        m_url = "https://api.upbit.com/v1/market/all"
        t_url = "https://api.upbit.com/v1/ticker?markets="
        markets = requests.get(m_url).json()
        krw = [m['market'] for m in markets if m['market'].startswith("KRW-")]
        tickers = requests.get(t_url + ",".join(krw)).json()
        groups = {
            "+10% 이상": [], "+5~+10%": [], "+3~+5%": [],
            "-3~-5%": [], "-5~-10%": [], "-10% 이하": []
        }
        for coin in tickers:
            chg = coin['signed_change_rate'] * 100
            name = coin['market'].split("-")[1]
            if chg >= 10: groups["+10% 이상"].append(name)
            elif 5 <= chg < 10: groups["+5~+10%"].append(name)
            elif 3 <= chg < 5: groups["+3~+5%"].append(name)
            elif -5 < chg <= -3: groups["-3~-5%"].append(name)
            elif -10 < chg <= -5: groups["-5~-10%"].append(name)
            elif chg <= -10: groups["-10% 이하"].append(name)
        return groups
    except:
        return None

# 메인 알림 함수
async def send_alert():
    msg = "[📊 StockRadar 자동 알림]\n\n"

    krx_jump = [res for t in [f"{code}.KS" for code in krx_name_to_code.values()] if (res := is_jump_stock(t))]
    msg += "🇰🇷 한국 급등 종목\n" + ("\n".join(krx_jump) if krx_jump else "없음") + "\n\n"

    us_jump = [res for t in us_name_to_code.values() if (res := is_jump_stock(t))]
    msg += "🇺🇸 미국 급등 종목\n" + ("\n".join(us_jump) if us_jump else "없음") + "\n\n"

    coins = analyze_upbit()
    msg += "🪙 코인 급등/급락\n"
    if coins:
        for k, v in coins.items():
            if v:
                msg += f"{k}: {', '.join(v[:5])}\n"
    else:
        msg += "정보 없음"

    bot.send_message(chat_id=CHAT_ID, text=msg)

# FastAPI 라우터
@app.get("/")
async def root():
    return {"message": "StockRadar bot is running."}

# 스케줄러 스타트
@app.on_event("startup")
async def startup_event():
    scheduler.add_job(lambda: asyncio.create_task(send_alert()), 'interval', minutes=10)
    scheduler.start()
