import os
import discord
from discord.ext import commands
import yfinance as yf
import pandas as pd
import ta
import mplfinance as mpf
from datetime import datetime
import pytz
import asyncio
from flask import Flask
from threading import Thread

# --- DUMMY WEB SERVER FOR RENDER FREE TIER ---
app = Flask('')

@app.route('/')
def home():
    return "PSX Bot is Alive and Running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- TRADINGVIEW TA INTEGRATION ---
try:
    from tradingview_ta import TA_Handler, Interval
    tv_available = True
except ImportError:
    tv_available = False

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Secure Environment Fallback Token
TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN_HERE")

def get_pkt_time():
    pkt = pytz.timezone('Asia/Karachi')
    return datetime.now(pkt).strftime("%d %b %Y | %I:%M %p PKT")

def get_tv_analysis(symbol):
    """TradingView Technical Recommendation Fetcher"""
    if not tv_available:
        return None
    try:
        tv_symbol = "KSE100" if symbol.upper() in ["KSE100", "KSE-100"] else symbol.upper()
        handler = TA_Handler(
            symbol=tv_symbol,
            screener="pakistan",
            exchange="PSX",
            interval=Interval.INTERVAL_1_DAY
        )
        return handler.get_analysis().summary
    except Exception as e:
        print(f"TradingView TA Error for {symbol}: {e}")
        return None

def fetch_yfinance_sync(symbol, period, interval):
    """Multi-ticker retry for PSX Stocks & KSE100 Index"""
    symbol_upper = symbol.strip().upper()
    
    if symbol_upper in ["KSE100", "KSE-100"]:
        tickers_to_try = ["^KSE100", "KSE100.KA", "^KSE", "MZNPETF.KA", "NITGIETFO.KA"]
    elif symbol_upper in ["KSE30", "KSE-30"]:
        tickers_to_try = ["^KSE30", "KSE30.KA"]
    else:
        tickers_to_try = [f"{symbol_upper}.KA", symbol_upper] if not symbol_upper.endswith(".KA") else [symbol_upper, symbol_upper.replace(".KA", "")]

    for t in tickers_to_try:
        try:
            print(f"🔄 Trying Yahoo Ticker: {t}...")
            df = yf.download(t, period=period, interval=interval, progress=False)
            if not df.empty and len(df) >= 2:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                print(f"✅ Downloaded {len(df)} rows using {t}")
                return df, t
        except Exception:
            continue
            
    return pd.DataFrame(), None

async def fetch_data_async(symbol, period, interval):
    """Async wrapper to keep Discord event loop active"""
    return await asyncio.to_thread(fetch_yfinance_sync, symbol, period, interval)

@bot.event
async def on_ready():
    activity = discord.Activity(type=discord.ActivityType.watching, name="PSX Market & KSE100 | !psx")
    await bot.change_presence(status=discord.Status.online, activity=activity)
    print("══════════════════════════════════════════════════")
    print(f"✅ {bot.user.name} Pro Technical Dashboard Online!")
    print(f"🕒 PKT Time: {get_pkt_time()}")
    print("🤖 Full Indicators & Visual Chart Engine Ready")
    print("══════════════════════════════════════════════════")

# --- COMMAND 1: PRO TECHNICAL ANALYSIS ---
@bot.command(name="psx")
async def psx_analysis(ctx, symbol: str, timeframe: str = "1d"):
    raw_symbol = symbol.strip().upper()
    current_pkt = get_pkt_time()
    
    timeframe_map = {
        "1m": ("1d", "1m"), "5m": ("5d", "5m"), "15m": ("1mo", "15m"),
        "30m": ("1mo", "30m"), "1h": ("2mo", "60m"), "1d": ("6mo", "1d"),
        "7d": ("1y", "1d"), "1w": ("2y", "1wk"), "1mon": ("5y", "1mo"), "1y": ("5y", "1mo")
    }
    
    tf = timeframe.lower()
    if tf not in timeframe_map:
        await ctx.send("⚠️ Invalid timeframe! Options: `1m`, `5m`, `15m`, `30m`, `1h`, `1d`, `7d`, `1w`, `1mon`, `1y`")
        return

    period, interval = timeframe_map[tf]

    try:
        await ctx.send(f"⏳ Generating Pro Technical Dashboard for **{raw_symbol}**...")
        
        df, successful_ticker = await fetch_data_async(raw_symbol, period, interval)
        tv_summary = await asyncio.to_thread(get_tv_analysis, raw_symbol)

        if df.empty or len(df) < 2:
            msg = f"❌ `{raw_symbol}` ka chart data filhal sync nahi ho saka."
            if tv_summary:
                msg += f"\n📊 **TradingView Summary Rating:** `{tv_summary.get('RECOMMENDATION', 'N/A')}`"
            await ctx.send(msg)
            return

        data_len = len(df)

        df['RSI'] = ta.momentum.rsi(df['Close'], window=min(14, data_len - 1)) if data_len > 14 else pd.Series([50]*data_len, index=df.index)
        df['EMA9'] = ta.trend.ema_indicator(df['Close'], window=min(9, data_len - 1)) if data_len > 9 else df['Close']
        df['EMA20'] = ta.trend.ema_indicator(df['Close'], window=min(20, data_len - 1)) if data_len > 20 else df['Close']
        df['EMA50'] = ta.trend.ema_indicator(df['Close'], window=50) if data_len >= 50 else pd.Series(index=df.index, dtype='float64')
        df['EMA200'] = ta.trend.ema_indicator(df['Close'], window=200) if data_len >= 200 else pd.Series(index=df.index, dtype='float64')

        if data_len >= 26:
            macd_obj = ta.trend.MACD(df['Close'], window_slow=26, window_fast=12, window_sign=9)
            df['MACD'] = macd_obj.macd()
            df['MACD_Signal'] = macd_obj.macd_signal()
        else:
            df['MACD'] = pd.Series(index=df.index, dtype='float64')
            df['MACD_Signal'] = pd.Series(index=df.index, dtype='float64')

        if data_len >= 20:
            bb_obj = ta.volatility.BollingerBands(df['Close'], window=20, window_dev=2)
            df['BB_High'] = bb_obj.bollinger_hband()
            df['BB_Low'] = bb_obj.bollinger_lband()
            df['Vol_SMA20'] = df['Volume'].rolling(window=20).mean() if 'Volume' in df.columns else pd.Series(index=df.index, dtype='float64')
        else:
            df['BB_High'] = pd.Series(index=df.index, dtype='float64')
            df['BB_Low'] = pd.Series(index=df.index, dtype='float64')
            df['Vol_SMA20'] = pd.Series(index=df.index, dtype='float64')

        curr_price = float(df['Close'].iloc[-1])
        open_price = float(df['Open'].iloc[-1])
        high_price = float(df['High'].iloc[-1])
        low_price = float(df['Low'].iloc[-1])
        volume = int(df['Volume'].iloc[-1]) if 'Volume' in df.columns and not pd.isna(df['Volume'].iloc[-1]) else 0
        avg_volume = int(df['Vol_SMA20'].dropna().iloc[-1]) if not df['Vol_SMA20'].dropna().empty else 1

        curr_rsi = float(df['RSI'].dropna().iloc[-1]) if not df['RSI'].dropna().empty else 50.0
        curr_ema9 = float(df['EMA9'].dropna().iloc[-1]) if not df['EMA9'].dropna().empty else curr_price
        curr_ema20 = float(df['EMA20'].dropna().iloc[-1]) if not df['EMA20'].dropna().empty else curr_price
        curr_ema50 = float(df['EMA50'].dropna().iloc[-1]) if not df['EMA50'].dropna().empty else None
        curr_ema200 = float(df['EMA200'].dropna().iloc[-1]) if not df['EMA200'].dropna().empty else None

        curr_macd = float(df['MACD'].dropna().iloc[-1]) if not df['MACD'].dropna().empty else None
        curr_macd_sig = float(df['MACD_Signal'].dropna().iloc[-1]) if not df['MACD_Signal'].dropna().empty else None
        bb_high = float(df['BB_High'].dropna().iloc[-1]) if not df['BB_High'].dropna().empty else None
        bb_low = float(df['BB_Low'].dropna().iloc[-1]) if not df['BB_Low'].dropna().empty else None

        lookback = min(50, data_len)
        resistance = float(df['High'].tail(lookback).max())
        support = float(df['Low'].tail(lookback).min())

        dist_from_support_pct = ((curr_price - support) / support) * 100 if support > 0 else 0.0
        dist_from_resistance_pct = ((resistance - curr_price) / curr_price) * 100 if curr_price > 0 else 0.0

        market_colors = mpf.make_marketcolors(
            up='#26a69a', down='#ef5350', edge='inherit',
            wick={'up':'#26a69a', 'down':'#ef5350'}, volume={'up':'#26a69a', 'down':'#ef5350'}
        )
        custom_style = mpf.make_mpf_style(
            marketcolors=market_colors, gridstyle=':', gridcolor='#2d3142',
            facecolor='#131722', figcolor='#131722',
            rc={'font.family': 'sans-serif', 'text.color': '#d1d4dc', 'axes.labelcolor': '#d1d4dc'}
        )

        chart_filename = f"{raw_symbol}_{tf}_chart.png"
        
        add_plots = []
        if not df['EMA9'].dropna().empty:
            add_plots.append(mpf.make_addplot(df['EMA9'], color='#ffeb3b', width=1.0))
        if not df['EMA20'].dropna().empty:
            add_plots.append(mpf.make_addplot(df['EMA20'], color='#ff9800', width=1.2))
        if curr_ema50 and not df['EMA50'].dropna().empty:
            add_plots.append(mpf.make_addplot(df['EMA50'], color='#00e5ff', width=1.2))
        if curr_ema200 and not df['EMA200'].dropna().empty:
            add_plots.append(mpf.make_addplot(df['EMA200'], color='#e040fb', width=1.5))
            
        if bb_high and not df['BB_High'].dropna().empty:
            add_plots.append(mpf.make_addplot(df['BB_High'], color='#787b86', linestyle='--', width=0.8))
            add_plots.append(mpf.make_addplot(df['BB_Low'], color='#787b86', linestyle='--', width=0.8))

        mpf.plot(
            df, type='candle', volume=True if volume > 0 else False,
            style=custom_style, addplot=add_plots if add_plots else None,
            title=f"\n{raw_symbol} ({tf.upper()}) - Pro Technical Chart [{current_pkt}]",
            savefig=chart_filename
        )

        bullish_score = 0
        bearish_score = 0

        if curr_rsi <= 32 or (bb_low and curr_price <= bb_low * 1.01):
            valuation_status = "💎 UNDERVALUED / ACCUMULATION ZONE 🟢"
            bullish_score += 2
        elif curr_rsi >= 68 or (bb_high and curr_price >= bb_high * 0.99):
            valuation_status = "⚠️ OVERVALUED / PROFIT TAKING ZONE 🔴"
            bearish_score += 2
        else:
            valuation_status = "⚖️ FAIR VALUE / NEUTRAL 🟡"

        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0
        if vol_ratio >= 1.5 and dist_from_resistance_pct <= 1.5:
            vol_status = f"🔥 HIGH VOLUME BREAKOUT CONFIRMED ({vol_ratio:.1f}x Avg)"
            bullish_score += 2
        elif vol_ratio >= 1.5:
            vol_status = f"⚡ Volume Spike ({vol_ratio:.1f}x Avg)"
            bullish_score += 1
        else:
            vol_status = f"Normal ({vol_ratio:.1f}x Avg)"

        if curr_macd is not None and curr_macd_sig is not None:
            if curr_macd > curr_macd_sig:
                macd_status = "Bullish Crossover 🟢 (MACD > Signal)"
                bullish_score += 1
            else:
                macd_status = "Bearish Crossover 🔴 (MACD < Signal)"
                bearish_score += 1
        else:
            macd_status = "N/A"

        if curr_price > curr_ema20:
            ema_alignment = "Short-Term Uptrend 🟢 (Price > EMA20)"
            bullish_score += 1
        else:
            ema_alignment = "Short-Term Downtrend 🔴 (Price < EMA20)"
            bearish_score += 1

        if bullish_score >= 3:
            overall_signal = "STRONG BUY / BULLISH BREAKOUT 🟢🟢"
        elif bullish_score >= 2:
            overall_signal = "ACCUMULATE / BUY 🟢"
        elif bearish_score >= 3:
            overall_signal = "STRONG SELL / DOWNTREND 🔴🔴"
        elif bearish_score >= 2:
            overall_signal = "CAUTION / SELL 🔴"
        else:
            overall_signal = "NEUTRAL / WAIT & WATCH 🟡"

        price_change = curr_price - open_price
        change_pct = (price_change / open_price) * 100 if open_price != 0 else 0.0
        direction_icon = "🟢" if price_change >= 0 else "🔴"

        tv_rec = tv_summary.get('RECOMMENDATION', 'N/A') if tv_summary else "N/A"

        embed = discord.Embed(
            title=f"📊 PSX PRO ANALYZER: {raw_symbol} [{tf.upper()}]", 
            description=(
                f"🕒 **Signal Timestamp:** `{current_pkt}`\n"
                f"🎯 **Overall Signal:** `{overall_signal}`\n"
                f"💎 **Valuation:** `{valuation_status}`\n"
                f"📊 **TradingView Rating:** `{tv_rec}`\n"
                f"────────────────────────────────"
            ),
            color=0x26a69a if price_change >= 0 else 0xef5350
        )
        
        price_text = (
            f"• **Current Price / Index:** {curr_price:,.2f} ({direction_icon} {change_pct:+.2f}%)\n"
            f"• **Day High / Low:** {high_price:,.2f} / {low_price:,.2f}\n"
            f"• **Volume Activity:** {volume:,} | {vol_status}"
        )
        embed.add_field(name="💰 Price Action & Volume", value=price_text, inline=False)

        ema_levels_str = f"9: `{curr_ema9:,.2f}` | 20: `{curr_ema20:,.2f}`"
        if curr_ema50:
            ema_levels_str += f" | 50: `{curr_ema50:,.2f}`"
        if curr_ema200:
            ema_levels_str += f" | 200: `{curr_ema200:,.2f}`"

        tech_text = (
            f"• **RSI (14):** `{curr_rsi:.2f}`\n"
            f"• **MACD Engine:** {macd_status}\n"
            f"• **EMA Trend:** {ema_alignment}\n"
            f"• **EMA Levels:** {ema_levels_str}\n"
            f"• **Bollinger Range:** Upper `{bb_high:,.2f}` | Lower `{bb_low:,.2f}`" if bb_high else "• **Bollinger Range:** N/A"
        )
        embed.add_field(name="📈 Technical Indicators", value=tech_text, inline=False)

        levels_text = (
            f"• **{lookback}-Bar Resistance:** PKR {resistance:,.2f} *(Away by {dist_from_resistance_pct:.2f}%)*\n"
            f"• **{lookback}-Bar Support:** PKR {support:,.2f} *(Above by {dist_from_support_pct:.2f}%)*"
        )
        embed.add_field(name="🎯 Key Levels & Proximity", value=levels_text, inline=False)

        embed.set_footer(text=f"PSX Pro Analyzer • Realtime Market Signal • {current_pkt}")

        file = discord.File(chart_filename, filename=chart_filename)
        embed.set_image(url=f"attachment://{chart_filename}")

        await ctx.send(file=file, embed=embed)

        if os.path.exists(chart_filename):
            os.remove(chart_filename)

    except Exception as e:
        await ctx.send(f"⚠️ Error: `{str(e)}`")
        print(f"💥 [ERROR] {str(e)}")

# --- COMMAND 2: INTRADAY 1-HOUR BACKTESTING ENGINE ---
@bot.command(name="backtest")
async def backtest_strategy(ctx, symbol: str):
    raw_symbol = symbol.strip().upper()
    current_pkt = get_pkt_time()
    await ctx.send(f"⏳ Running 1-Hour Intraday Backtest Simulation for **{raw_symbol}**...")

    try:
        df, successful_ticker = await fetch_data_async(raw_symbol, period="60d", interval="60m")

        if df.empty or len(df) < 5:
            await ctx.send(f"❌ `{raw_symbol}` ka 1-hour historical data nahi mila.")
            return

        data_len = len(df)
        df['RSI'] = ta.momentum.rsi(df['Close'], window=min(14, data_len - 1))
        df['EMA20'] = ta.trend.ema_indicator(df['Close'], window=min(20, data_len - 1))

        initial_capital = 100000.0
        cash = initial_capital
        position = 0
        buy_price = 0.0
        trades = []

        for i in range(min(20, data_len - 1), data_len):
            price = float(df['Close'].iloc[i])
            prev_price = float(df['Close'].iloc[i-1])
            rsi = float(df['RSI'].iloc[i])
            ema = float(df['EMA20'].iloc[i])
            prev_ema = float(df['EMA20'].iloc[i-1])

            if pd.isna(rsi) or pd.isna(ema):
                continue

            buy_signal = (rsi < 45) or (prev_price < prev_ema and price > ema)

            if position == 0 and buy_signal:
                position = cash // price
                buy_price = price
                cash -= position * buy_price

            elif position > 0:
                pnl_pct = ((price - buy_price) / buy_price) * 100
                if rsi > 65 or pnl_pct <= -2.0 or pnl_pct >= 2.5:
                    cash += position * price
                    trades.append(pnl_pct)
                    position = 0

        if position > 0:
            final_price = float(df['Close'].iloc[-1])
            cash += position * final_price
            pnl_pct = ((final_price - buy_price) / buy_price) * 100
            trades.append(pnl_pct)

        total_trades = len(trades)
        winning_trades = [t for t in trades if t > 0]
        win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0.0
        total_return_pct = ((cash - initial_capital) / initial_capital) * 100

        embed = discord.Embed(
            title=f"🧪 1-Hour Intraday Backtest: {raw_symbol}",
            description=f"🕒 **Run Time:** `{current_pkt}`\n**Strategy:** RSI + EMA20 Crossover\n───────────────",
            color=0x26a69a if total_return_pct >= 0 else 0xef5350
        )

        embed.add_field(name="💰 Initial Capital", value="PKR 100,000", inline=True)
        embed.add_field(name="🏁 Final Portfolio", value=f"PKR {cash:,.2f}", inline=True)
        embed.add_field(name="📈 Total Return", value=f"**{total_return_pct:+.2f}%**", inline=True)
        embed.add_field(name="📊 Trades Executed", value=str(total_trades), inline=True)
        embed.add_field(name="🎯 Win Rate", value=f"**{win_rate:.1f}%**", inline=True)

        embed.set_footer(text=f"PSX Pro Analyzer • 1H Intraday Backtest Engine • {current_pkt}")
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"⚠️ Backtest Error: `{str(e)}`")

# Start Flask Web Server
keep_alive()

# Run Discord Bot
bot.run(TOKEN)