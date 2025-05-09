import requests
import json
import os
from datetime import datetime
from telegram import Bot
import asyncio
import logging
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import utc
import aiohttp

# 설정
logging.basicConfig(level=logging.INFO)
TOKEN = "7958883184:AAF3Q4WBjShZZZu4KMPFGiZe_vIBVDA_C_8"
CHAT_ID = 7631224187
bot = Bot(token=TOKEN)
app = FastAPI()
scheduler = AsyncIOScheduler(timezone=utc)

PRICE_FILE = "coin_prices.json"
RENDER_URL = "https://stockrader-bot.onrender.com/"

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

def analyze_upbit():
    try:
        m_url = "https://api.upbit.com/v1/market/all"
        t_url = "https://api.upbit.com/v1/ticker?markets="
        markets = requests.get(m_url).json()
        krw = [m['market'] for m in markets if m['market'].startswith("KRW-")]
        tickers = requests.get(t_url + ",".join(krw)).json()
        current = {coin['market']: coin.get('trade_price') for coin in tickers}

        prev = load_coin_prices()
        save_coin_prices(current)

        if not prev:
            return "이전 데이터 없음 (초기 수집 중)"

        result = {
            "+10% 이상": [], "+5~+10%": [], "+3~+5%": [],
            "-3~-5%": [], "-5~-10%": [], "-10% 이하": []
        }

        for market in krw:
            now_price = current.get(market)
            before = prev.get(market)
            if before in [None, 0] or now_price is None:
                continue
            change = ((now_price - before) / before) * 100
            name = market.split("-")[1]
            if change >= 10:
                result["+10% 이상"].append(name)
            elif 5 <= change < 10:
                result["+5~+10%"].append(name)
            elif 3 <= change < 5:
                result["+3~+5%"].append(name)
            elif -5 < change <= -3:
                result["-3~-5%"].append(name)
            elif -10 < change <= -5:
                result["-5~-10%"].append(name)
            elif change <= -10:
                result["-10% 이하"].append(name)

        return result
    except Exception as e:
        return f"코인 분석 오류: {e}"

async def send_alert():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] send_alert 작동 시작")

    msg = "[📊 StockRadar 코인 알림]\n\n"
    msg += "🪙 코인 10분간 급등/급락\n"

    result = analyze_upbit()

    if isinstance(result, dict):
        has_any = False
        prev = load_coin_prices()
        m_url = "https://api.upbit.com/v1/market/all"
        t_url = "https://api.upbit.com/v1/ticker?markets="
        markets = requests.get(m_url).json()
        krw = [m['market'] for m in markets if m['market'].startswith("KRW-")]
        tickers = requests.get(t_url + ",".join(krw)).json()
        current = {coin['market']: coin.get('trade_price') for coin in tickers}

        for label, coin_list in result.items():
            if coin_list:
                has_any = True
                msg += f"{label}: {', '.join(coin_list)}\n"

        if not has_any:
            price_diff = []
            for market in krw:
                before = prev.get(market)
                now_price = current.get(market)
                if before in [None, 0] or now_price is None:
                    continue
                change = ((now_price - before) / before) * 100
                name = market.split("-")[1]
                price_diff.append((change, name))

            if price_diff:
                price_diff.sort()
                most_down = price_diff[0]
                most_up = price_diff[-1]
                msg += "\n※ 참고용 최대 상승 종목: {} ({:.2f}%)\n".format(most_up[1], most_up[0])
                msg += "※ 참고용 최대 하락 종목: {} ({:.2f}%)\n".format(most_down[1], most_down[0])
            else:
                msg += "\n※ 분석 가능한 코인 데이터 없음\n"

    else:
        msg += result

    try:
        bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        print("텔레그램 전송 오류:", e)

async def keep_alive():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RENDER_URL) as resp:
                    print("Keep-alive ping sent")
        except Exception as e:
            print("Keep-alive ping failed:", e)
        await asyncio.sleep(600)

@app.get("/")
async def root():
    return {"message": "StockRadar bot (코인 전용) is running."}

@app.get("/start")
async def trigger_alert():
    await send_alert()
    return {"message": "Alert sent manually."}

@app.on_event("startup")
async def startup_event():
    scheduler.add_job(send_alert, 'interval', minutes=10)
    scheduler.start()
    asyncio.create_task(keep_alive())
    print("스케줄러 시작됨")

