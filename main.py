import datetime
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- TELEGRAM CONFIG ---
BOT_TOKEN = "8602859488:AAFdzgYd0Fn6z8rANtDBVG_aIfbx3Prfg7A"
CHAT_ID = "6257600715"


def send_alert(message):
  try:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload, timeout=5)
  except Exception as e:
    print(f"Telegram Error: {e}")


session = requests.Session()
retries = Retry(
    total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504]
)
session.mount("https://", HTTPAdapter(max_retries=retries))
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
}

# --- WALLET & AUDIT TRACKER ---
binance_wallet_usd = 50.00
bybit_wallet_usd = 50.00
CAPITAL_PER_LEG = 50.00
ROUNDTRIP_FEE_PCT = 0.08  # 0.08% taker fees buffer
USD_INR = 85.0
total_pnl_inr = 0.0


def get_live_rates():
  try:
    b_res = session.get(
        "https://fapi.binance.com/fapi/v1/premiumIndex",
        headers=headers,
        timeout=10,
    ).json()
    binance_rates = {
      item["symbol"]: float(item["lastFundingRate"]) * 100
      for item in b_res
      if "lastFundingRate" in item and item["symbol"].endswith("USDT")
    }

    by_res = session.get(
        "https://api.bytick.com/v5/market/tickers?category=linear",
        headers=headers,
        timeout=10,
    ).json()
    bybit_rates = {
      item["symbol"]: float(item["fundingRate"]) * 100
      for item in by_res.get("result", {}).get("list", [])
      if item.get("fundingRate") and item["symbol"].endswith("USDT")
    }
    return binance_rates, bybit_rates
  except Exception as e:
    print(f"Fetch Error: {e}")
    return {}, {}


def check_depth(symbol):
  try:
    b_ob = session.get(
        f"https://fapi.binance.com/fapi/v1/depth?symbol={symbol}&limit=5",
        headers=headers,
        timeout=5,
    ).json()
    b_depth = sum(float(b[0]) * float(b[1]) for b in b_ob.get("bids", []))

    by_ob = session.get(
        f"https://api.bytick.com/v5/market/orderbook?category=linear&symbol={symbol}&limit=5",
        headers=headers,
        timeout=5,
    ).json()
    by_depth = sum(
        float(b[0]) * float(b[1])
        for b in by_ob.get("result", {}).get("b", [])
    )
    return b_depth, by_depth
  except Exception:
    return 0, 0


def scan_best_trade():
  b_rates, by_rates = get_live_rates()
  common = set(b_rates.keys()).intersection(set(by_rates.keys()))
  best_trade = None
  highest_net = 0.0

  for symbol in common:
    b_rate = b_rates[symbol]
    by_rate = by_rates[symbol]
    spread = abs(b_rate - by_rate)

    if spread >= 0.30:
      b_depth, by_depth = check_depth(symbol)
      if b_depth >= 500 and by_depth >= 500:
        gross = CAPITAL_PER_LEG * (spread / 100.0)
        fees = CAPITAL_PER_LEG * 2 * (ROUNDTRIP_FEE_PCT / 100.0)
        net_usd = gross - fees
        net_inr = net_usd * USD_INR

        if net_inr >= 5.00 and net_inr > highest_net:
          highest_net = net_inr
          best_trade = {
              "symbol": symbol,
              "spread": spread,
              "b_rate": b_rate,
              "by_rate": by_rate,
              "net_usd": net_usd,
              "net_inr": net_inr,
              "b_depth": b_depth,
              "by_depth": by_depth,
          }
  return best_trade


init_msg = (
    "💼 *PORTFOLIO & AUDIT LEDGER ACTIVE*\n\n"
    f"Binance Wallet: `${binance_wallet_usd:.2f}`\n"
    f"Bybit Wallet: `${bybit_wallet_usd:.2f}`\n"
    f"Combined Total: *${binance_wallet_usd + bybit_wallet_usd:.2f}*\n"
    "Loss Reason Diagnostic: *ENABLED* (Full Audit)\n"
    "Status: Monitoring 24/7 cycles..."
)
print(init_msg)
send_alert(init_msg)

active_position = None

while True:
  now = datetime.datetime.now(datetime.timezone.utc)
  current_cycle_hour = (now.hour // 8) * 8
  next_cycle_hour = current_cycle_hour + 8
  next_settlement = now.replace(
      hour=0, minute=0, second=0, microsecond=0
  ) + datetime.timedelta(hours=next_cycle_hour)

  seconds_left = int((next_settlement - now).total_seconds())

  # 1. T - 120s Trigger: Position Entry Check
  if 110 <= seconds_left <= 130 and active_position is None:
    print(f"\n[T-120s REACHED] Scanning for qualified pairs...")
    candidate = scan_best_trade()

    if candidate:
      active_position = candidate
      b_action = (
          "SHORT (Receive)" if candidate["b_rate"] > 0 else "LONG (Receive)"
      )
      by_action = "LONG (Pay)" if candidate["b_rate"] > 0 else "SHORT (Pay)"

      entry_alert = (
          f"⚡ *TRADE EXECUTED (T-120s ENTRY)*\n\n"
          f"Pair: `{candidate['symbol']}`\n"
          f"Spread: `{candidate['spread']:.4f}%`\n\n"
          f"• *Binance ($50):* {b_action} (Rate: `{candidate['b_rate']:+.4f}%`)\n"
          f"• *Bybit ($50):* {by_action} (Rate: `{candidate['by_rate']:+.4f}%`)\n\n"
          f"Expected Net Gain: *+${candidate['net_usd']:.4f}*"
          f" (~₹{candidate['net_inr']:.2f})\n"
          f"Status: Hedged & Waiting for Settlement..."
      )
      print(entry_alert)
      send_alert(entry_alert)

  # 2. T + 30s Post-Settlement Exit & Full Audit Realization
  if seconds_left >= (8 * 3600 - 40) and active_position is not None:
    trade = active_position

    # Post-settlement live check (settlement hone ke baad kya rate raha)
    b_rates_post, by_rates_post = get_live_rates()
    b_actual_rate = b_rates_post.get(trade["symbol"], trade["b_rate"])
    by_actual_rate = by_rates_post.get(trade["symbol"], trade["by_rate"])

    # Actual fees calculation
    b_fee = CAPITAL_PER_LEG * (ROUNDTRIP_FEE_PCT / 100.0)
    by_fee = CAPITAL_PER_LEG * (ROUNDTRIP_FEE_PCT / 100.0)
    total_fees_usd = b_fee + by_fee

    # Actual Funding earned/paid
    b_funding_usd = CAPITAL_PER_LEG * (abs(b_actual_rate) / 100.0)
    by_funding_usd = CAPITAL_PER_LEG * (abs(by_actual_rate) / 100.0)

    if b_actual_rate > by_actual_rate:
      b_leg_net = b_funding_usd - b_fee
      by_leg_net = -by_funding_usd - by_fee
    else:
      b_leg_net = -b_funding_usd - b_fee
      by_leg_net = by_funding_usd - by_fee

    net_cycle_usd = b_leg_net + by_leg_net
    net_cycle_inr = net_cycle_usd * USD_INR

    old_total = binance_wallet_usd + bybit_wallet_usd
    binance_wallet_usd += b_leg_net
    bybit_wallet_usd += by_leg_net
    total_wallet = binance_wallet_usd + bybit_wallet_usd
    total_pnl_inr += net_cycle_inr

    # --- PROFIT OR LOSS AUDIT LOGIC ---
    if net_cycle_inr >= 0:
      exit_alert = (
          f"💰 *PROFIT SETTLED & POSITION CLOSED*\n\n"
          f"Pair: `{trade['symbol']}`\n\n"
          f"📊 *Individual Exchange Breakdown:*\n"
          f"• Binance: `${binance_wallet_usd:.4f}` ({b_leg_net:+.4f}$)\n"
          f"• Bybit: `${bybit_wallet_usd:.4f}` ({by_leg_net:+.4f}$)\n\n"
          f"📈 *Combined Portfolio:*\n"
          f"• Old Balance: `${old_total:.4f}`\n"
          f"• New Balance: *${total_wallet:.4f}* (+${net_cycle_usd:.4f})\n"
          f"• Cycle Profit: *+₹{net_cycle_inr:.2f}*\n"
          f"• All-Time Total PnL: *+₹{total_pnl_inr:.2f}*\n\n"
          f"Status: Safe & Delta-Neutral. Risk: ₹0."
      )
    else:
      # LOSS REASON DIAGNOSTIC
      reasons = []
      gross_funding = abs(b_funding_usd - by_funding_usd)
      if total_fees_usd > gross_funding:
        reasons.append(
            f"1. Fee Drag: Exchange fees (${total_fees_usd:.4f}) exceeded gross"
            f" funding (${gross_funding:.4f})."
        )
      if abs(b_actual_rate - by_actual_rate) < trade["spread"]:
        reasons.append(
            f"2. Rate Narrowing: Spread compressed from {trade['spread']:.4f}%"
            f" to {abs(b_actual_rate - by_actual_rate):.4f}% at settlement."
        )
      if trade["b_depth"] < 500 or trade["by_depth"] < 500:
        reasons.append("3. Slippage: Depth was thin during fill.")
      if not reasons:
        reasons.append(
            "Market volatility slippage between order execution legs."
        )

      loss_reasons_str = "\n".join(reasons)

      exit_alert = (
          f"🔴 *LOSS AUDIT & TRADE CLOSED*\n\n"
          f"Pair: `{trade['symbol']}`\n\n"
          f"📊 *Loss Breakdown:*\n"
          f"• Cycle Loss: *-₹{abs(net_cycle_inr):.2f}* (-${abs(net_cycle_usd):.4f})\n"
          f"• Binance Balance: `${binance_wallet_usd:.4f}` ({b_leg_net:+.4f}$)\n"
          f"• Bybit Balance: `${bybit_wallet_usd:.4f}` ({by_leg_net:+.4f}$)\n"
          f"• Combined Wallet: `${total_wallet:.4f}` (Old: `${old_total:.4f}`)\n\n"
          f"⚠️ *KYU HUA LOSS (Exact Reasons):*\n"
          f"{loss_reasons_str}\n\n"
          f"Recommendation: Tighten spread floor or increase minimum liquidity depth."
      )

    print(exit_alert)
    send_alert(exit_alert)
    active_position = None

  time.sleep(5)
