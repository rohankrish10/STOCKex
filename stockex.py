"""
STOCKex — The Ultimate Trading Challenge
=================================================
Run:   python stockex.py
Open:  http://localhost:8080          <- Player view
Admin: http://localhost:8080/admin   <- Admin panel

Set STOCKEX_ADMIN_PASSWORD to use a stable admin password.
If unset, a random password is generated and shown in the server console.
No external dependencies — Python standard library only.
"""

import http.server
import html
import secrets
import socketserver
import json
import threading
import webbrowser
import random
import urllib.parse
import os
import sqlite3
import time
import copy
from pathlib import Path
from datetime import datetime
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 260" role="img">
  <rect x="240" y="20" width="200" height="220" rx="16" fill="#0f1117"/>
  <rect x="240" y="50" width="200" height="190" rx="16" fill="none" stroke="#3b82f6" stroke-width="1.5"/>
  <rect x="268" y="158" width="28" height="66" rx="3" fill="#22c55e"/>
  <rect x="306" y="128" width="28" height="96" rx="3" fill="#3b82f6"/>
  <rect x="344" y="106" width="28" height="118" rx="3" fill="#3b82f6"/>
  <rect x="382" y="138" width="28" height="86" rx="3" fill="#ef4444"/>
  <polyline points="268,158 306,128 344,106 382,138" fill="none" stroke="#f59e0b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="268" cy="158" r="4" fill="#f59e0b"/>
  <circle cx="306" cy="128" r="4" fill="#f59e0b"/>
  <circle cx="344" cy="106" r="4" fill="#f59e0b"/>
  <circle cx="382" cy="138" r="4" fill="#f59e0b"/>
</svg>"""

HOST = os.environ.get("STOCKEX_HOST", "0.0.0.0")
PORT = int(os.environ.get("STOCKEX_PORT", "8080"))
# Set STOCKEX_ADMIN_PASSWORD in the environment for a stable password.
# If omitted, generate a one-run password and print it to the server console.
ADMIN_PASSWORD_FROM_ENV = bool(os.environ.get("STOCKEX_ADMIN_PASSWORD"))
ADMIN_PASSWORD = os.environ.get("STOCKEX_ADMIN_PASSWORD") or secrets.token_urlsafe(18)
STARTING_CASH = 100000.0
MAX_REQUEST_BYTES = 1024 * 1024


# Persistent storage. The game state is kept in memory for speed, but is
# checkpointed to SQLite so a process/server restart does not erase the game.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
DB_PATH = os.path.join(DATA_DIR, "stockex.db")
BACKUP_INTERVAL = 30  # seconds
STATE_CHECKPOINT_INTERVAL = 3  # seconds; keeps disk I/O off player requests

os.makedirs(BACKUP_DIR, exist_ok=True)

# ── Price volatility config ───────────────────────────────────────────────────
# Each ticker gets its own volatility (% max drift per tick) and mean-reversion strength
VOLATILITY = {
    "ARSR": 0.004, "SGIN": 0.003, "UNSA": 0.006,
    "GLDC": 0.005, "PRAD": 0.004, "SNXA": 0.009,
    "CCBK": 0.002, "SPFN": 0.007, "VTCS": 0.008,
    "FTSG": 0.005, "GHBK": 0.004, "BRSK": 0.006,
}
MEAN_REVERSION = 0.015   # pull back toward base per tick
TICK_INTERVAL  = 2       # seconds between price ticks

# ── Shared game state ─────────────────────────────────────────────────────────
state = {
    "players":       {},       # token → {name, team, balance, portfolio, trades, joined_at}
    "admin_sessions": set(),
    "game_active":   False,
    "news_feed":     [],
    "price_history": {},       # ticker → list of (timestamp_str, price)  (last 30 ticks)
    "prices": {
        "ARSR": {"name": "Alpine ReSecure", "base": 1800, "current": 1800, "color": "#3b82f6"},
        "SGIN": {"name": "SummitGuard Insurance", "base": 700, "current": 700, "color": "#22c55e"},
        "UNSA": {"name": "UnityShield Assurance", "base": 950, "current": 950, "color": "#f97316"},
        "GLDC": {"name": "Golden Crest Capital", "base": 2400, "current": 2400, "color": "#a855f7"},
        "PRAD": {"name": "Pinnacle Risk Advisor", "base": 900, "current": 900, "color": "#eab308"},
        "SNXA": {"name": "Strategic Nexus Advisors", "base": 1100, "current": 1100, "color": "#ef4444"},
        "CCBK": {"name": "Capital Crest Bank", "base": 1250, "current": 1250, "color": "#42f9f9"},
        "SPFN": {"name": "Sterling Peak Financial", "base": 1900, "current": 1900, "color": "#ef2864"},
        "VTCS": {"name": "Vertex Consulting Solutions", "base": 1450, "current": 1450, "color": "#a30542"},
        "FTSG": {"name": "FortiSure Insurance Group", "base": 550, "current": 550, "color": "#bee610"},
        "GHBK": {"name": "Global Horizon Bank", "base": 850, "current": 850, "color": "#70b0e0"},
        "BRSK": {"name": "Bavaria Risk ReSecure", "base": 1600, "current": 1600, "color": "#d15536"},
    },
    "news_pool": [
        {"id":"N01","title":"Climate Catastrophe Alert","category":"Natural Disaster",
         "description":"Global reinsurers warn that insured losses from natural catastrophes could exceed $150 billion this year as hurricanes and floods become more frequent.",
         "impacts":{"ARSR":-8,"BRSK":-8,"SGIN":-5,"FTSG":-6,"UNSA":-3}},
        {"id":"N02","title":"Underwriting Excellence","category":"Earnings Report",
         "description":"A leading insurer reports a sharp rise in quarterly profits after maintaining one of the industry's best combined ratios and disciplined underwriting standards.",
         "impacts":{"SGIN":+10,"UNSA":+3,"FTSG":+2,"ARSR":+1,"BRSK":+1}},
        {"id":"N03","title":"Strategic Divestment Pays Off","category":"Corporate Action",
         "description":"A European financial services giant records a significant profit boost after divesting a stake in one of its Asian insurance ventures.",
         "impacts":{"UNSA":+9,"GHBK":+2,"VTCS":+1}},
        {"id":"N04","title":"Dealmaking Revival","category":"Banking",
         "description":"Central banks signal interest rates may remain elevated for longer, while mergers and acquisitions activity rebounds globally.",
         "impacts":{"GLDC":+8,"CCBK":+7,"SPFN":+7,"GHBK":+5,"VTCS":+2}},
        {"id":"N05","title":"Cyber Threat Escalation","category":"Cybersecurity",
         "description":"A wave of sophisticated cyberattacks on multinational corporations leads businesses to dramatically increase spending on cyber risk advisory and insurance services.",
         "impacts":{"PRAD":+10,"VTCS":+6,"SNXA":+4,"SGIN":3,"UNSA":+2}},
        {"id":"N06","title":"Regulatory Crackdown","category":"Regulation",
         "description":"Regulators launch an investigation into audit quality and consulting independence across several major professional services firms.",
         "impacts":{"SNXA":-10,"VTCS":-3,"PRAD":-2}},
        {"id":"N07","title":"Trading Boom","category":"Financial Markets",
         "description":"One of the world's largest banks reports record trading revenues as market volatility drives increased client activity.",
         "impacts":{"CCBK":+9,"GLDC":+8,"SPFN":+7,"GHBK":+3}},
        {"id":"N08","title":"Wealth Surge","category":"Wealth Management",
         "description":"Global wealth creation reaches an all-time high, pushing assets under management at major wealth-management firms to record levels.",
         "impacts":{"SPFN":+10,"CCBK":5,"GHBK":4,"GLDC":3}},
        {"id":"N09","title":"AI Spending Frenzy","category":"Technology",
         "description":"Governments and Fortune 500 companies announce billions of dollars in spending on artificial intelligence transformation and cloud modernization projects.",
         "impacts":{"VTCS":+10,"SNXA":5,"PRAD":2,"CCBK":1}},
        {"id":"N10","title":"Wildfire Crisis","category":"Natural Disaster",
         "description":"An unusually severe wildfire season causes insured losses across several provinces, leading analysts to revise claim estimates upward.",
         "impacts":{"FTSG":-10,"SGIN":-6,"UNSA":-4,"ARSR":-3,"BRSK":-3}},
        {"id":"N11","title":"Capital Strength Recorded","category":"Corporate Finance",
         "description":"A major international bank unveils a multi-billion-dollar share buyback after exceeding capital adequacy requirements.",
         "impacts":{"GHBK":+9,"CCBK":+3,"SPFN":+2,"GLDC":+2}},
        {"id":"N12","title":"Reinsurance Price Surge","category":"Insurance Market",
         "description":"Property and casualty reinsurance rates rise sharply during annual renewals as insurers seek protection against increasing catastrophe losses.",
         "impacts":{"BRSK":+10,"ARSR":+10,"SGIN":-3,"FTSG":-4,"UNSA":-2}},
        {"id":"N13","title":"Asian Growth Opportunity","category":"Emerging Markets",
         "description":"A rapidly growing middle class in Asia drives strong demand for life insurance and retirement planning products.",
         "impacts":{"UNSA":+8,"GHBK":+7,"PRAD":+2}},
        {"id":"N14","title":"Mega Brokerage Deal","category":"Brokerage",
         "description":"Several large corporations consolidate their insurance brokerage relationships under a single global risk advisory provider.",
         "impacts":{"PRAD":+10,"SGIN":2,"UNSA":+2}},
        {"id":"N15","title":"Banking Rules Relaxed","category":"Regulation",
         "description":"Financial regulators ease restrictions on investment banking activities to stimulate economic growth.",
         "impacts":{"GLDC":+10,"SPFN":+8,"CCBK":+7,"GHBK":+3}},
        {"id":"N16","title":"IPO Freeze","category":"Economic Slowdown",
         "description":"Economic uncertainty causes corporations to delay acquisitions and public listings worldwide.",
         "impacts":{"GLDC":-10,"SPFN":-8,"CCBK":-6,"GHBK":-2}},
    ],
    "lock": threading.Lock(),
    "checkpoint_event": threading.Event(),
}


# ── Participant Company Directory ─────────────────────────────────────────────
# Source: STOCKEX Company Directory & Investor's Market Guide.
# Kept inside the application so participants can read the guide without leaving STOCKEX.
COMPANY_DIRECTORY = [
    {"ticker":"ARSR","name":"Alpine ReSecure","sector":"Insurance","industry":"Global Reinsurance","base":1800,"volatility":"0.4%",
     "snapshot":"A global reinsurer that provides risk capacity to primary insurers rather than selling most policies directly to retail customers. Its role is to absorb part of the losses arising from large and complex insured events.",
     "business_model":"Property and catastrophe reinsurance; large-loss risk sharing; global insurer risk transfer.","customers":"Primary insurers seeking protection against severe or concentrated claims.",
     "earnings":"Reinsurance pricing, renewal terms, catastrophe frequency and severity, underwriting discipline, and the overall insurance cycle.","metrics":"Underwriting profitability, loss experience, renewal pricing, catastrophe exposure, and premium growth.","catalysts":"Higher reinsurance rates, disciplined underwriting, strong renewal pricing, and demand for catastrophe protection."},
    {"ticker":"BRSK","name":"Bavaria Risk ReSecure","sector":"Insurance","industry":"Catastrophe & Property Reinsurance","base":1600,"volatility":"0.6%",
     "snapshot":"A specialist international reinsurer focused on catastrophe and property risks. It provides insurers with protection against high-value claims arising from severe weather and other large-loss events.",
     "business_model":"Catastrophe reinsurance; property risk transfer; high-severity loss protection.","customers":"Property insurers and other carriers looking to transfer concentrated catastrophe exposures.",
     "earnings":"Hurricanes, floods, earthquakes and wildfires; demand for reinsurance; renewal pricing; contract profitability.","metrics":"Reinsurance rates, catastrophe losses, contract margins, premium growth, and claims experience.","catalysts":"Rising reinsurance rates, greater demand for catastrophe protection, and disciplined pricing."},
    {"ticker":"UNSA","name":"UnityShield Assurance","sector":"Insurance","industry":"Diversified Insurance & Financial Services","base":950,"volatility":"0.6%",
     "snapshot":"A diversified insurer combining life, health, retirement and general insurance with broader financial-protection and wealth-related services.",
     "business_model":"Life and health insurance; retirement solutions; general insurance; financial protection.","customers":"Individuals, families and businesses seeking insurance and long-term financial protection.",
     "earnings":"Insurance demand, emerging-market growth, underwriting performance, investment income, and strategic portfolio decisions.","metrics":"Premium growth, underwriting result, investment income, claims experience, and geographic expansion.","catalysts":"Strong insurance demand, emerging-market growth, successful restructuring, and favorable investment conditions."},
    {"ticker":"SGIN","name":"SummitGuard Insurance","sector":"Insurance","industry":"Property & Casualty Insurance","base":700,"volatility":"0.3%",
     "snapshot":"A property-and-casualty insurer serving commercial and personal customers, with a focus on disciplined underwriting and specialty insurance opportunities.",
     "business_model":"Commercial property and casualty; personal insurance; specialty and cyber coverage.","customers":"Businesses and individuals requiring property, casualty, cyber and specialty protection.",
     "earnings":"Combined ratio, catastrophe claims, commercial insurance demand, cyber risk, and premium pricing.","metrics":"Combined ratio, premium growth, claims ratio, underwriting margin, and specialty-market growth.","catalysts":"Strong underwriting, attractive pricing, rising demand for cyber coverage, and resilient commercial demand."},
    {"ticker":"FTSG","name":"FortiSure Insurance Group","sector":"Insurance","industry":"General Insurance","base":550,"volatility":"0.5%",
     "snapshot":"A multi-region general insurer offering property, automobile and commercial insurance solutions. Its earnings are closely linked to claims, pricing and underwriting profitability.",
     "business_model":"Property insurance; motor insurance; commercial insurance.","customers":"Households, vehicle owners and commercial enterprises.",
     "earnings":"Catastrophic weather, claim frequency, premium pricing, and overall underwriting profitability.","metrics":"Claims ratio, combined ratio, premium growth, average claim cost, and underwriting result.","catalysts":"Improved premium pricing, lower claims, disciplined underwriting, and growth in commercial coverage."},
    {"ticker":"CCBK","name":"Capital Crest","sector":"Banking & Investment","industry":"Commercial & Investment Banking","base":1250,"volatility":"0.2%",
     "snapshot":"A diversified banking group combining retail banking, corporate lending, investment banking and capital-market activities.",
     "business_model":"Retail deposits and lending; corporate credit; investment banking; capital markets.","customers":"Consumers, corporates and institutional clients.",
     "earnings":"Interest rates, trading revenue, capital requirements, corporate lending activity and economic growth.","metrics":"Net interest income, loan growth, credit quality, trading revenue, capital strength, and return on equity.","catalysts":"Healthy economic growth, stronger capital-market activity, robust trading volumes, and favorable lending conditions."},
    {"ticker":"GLDC","name":"Goldcrest Capital","sector":"Banking & Investment","industry":"Investment Banking","base":2400,"volatility":"0.5%",
     "snapshot":"A specialist investment bank advising companies on mergers, acquisitions, capital raising and financial markets.",
     "business_model":"M&A advisory; IPO and capital raising; strategic finance; financial-market services.","customers":"Corporates, sponsors, investors and institutions undertaking major transactions.",
     "earnings":"M&A activity, IPO markets, trading performance, regulation and corporate confidence.","metrics":"Advisory fees, transaction volumes, underwriting revenue, trading performance, and pipeline strength.","catalysts":"M&A revival, active IPO markets, deregulation, market volatility and stronger corporate confidence."},
    {"ticker":"SPFN","name":"Sterling Peak Financial","sector":"Banking & Investment","industry":"Wealth Management & Investment Banking","base":1900,"volatility":"0.7%",
     "snapshot":"A financial-services firm combining wealth management for high-net-worth and institutional clients with investment-banking capabilities.",
     "business_model":"Wealth management; institutional investment services; investment banking.","customers":"High-net-worth individuals, institutions and corporate clients.",
     "earnings":"Assets under management, global wealth creation, capital-market performance and investment-banking activity.","metrics":"Assets under management, fee revenue, net inflows, advisory revenue, and investment performance.","catalysts":"Rising global wealth, strong markets, M&A activity, and favorable investment-banking conditions."},
    {"ticker":"GHBK","name":"Global Horizon Bank","sector":"Banking & Investment","industry":"International Banking","base":850,"volatility":"0.4%",
     "snapshot":"An international banking franchise providing commercial banking, trade finance, cross-border services and wealth management across multiple markets.",
     "business_model":"Commercial banking; international finance; trade services; wealth management.","customers":"Consumers, businesses, exporters/importers and international wealth clients.",
     "earnings":"Interest rates, banking regulation, capital strength, international growth and loan demand.","metrics":"Loan growth, net interest income, capital adequacy, credit quality, transaction volumes and wealth assets.","catalysts":"Economic expansion, stronger international trade, capital strength, and healthy lending demand."},
    {"ticker":"VTCS","name":"Vertex Consulting Solutions","sector":"Strategy & Consulting","industry":"Technology & Business Consulting","base":1450,"volatility":"0.8%",
     "snapshot":"A technology-led consulting firm helping organizations with digital transformation, cloud adoption, cybersecurity and artificial-intelligence initiatives.",
     "business_model":"Digital transformation; cloud; cybersecurity; AI consulting and implementation.","customers":"Large enterprises, governments and organizations modernizing technology infrastructure.",
     "earnings":"Enterprise technology spending, AI and cloud adoption, large contracts and digital-transformation budgets.","metrics":"Consulting bookings, contract pipeline, revenue growth, utilization, margins and recurring client relationships.","catalysts":"AI investment surges, cloud modernization, major consulting wins, and rising corporate technology budgets."},
    {"ticker":"SNXA","name":"Strategic Nexus Advisors","sector":"Strategy & Consulting","industry":"Strategy & Management Consulting","base":1100,"volatility":"0.9%",
     "snapshot":"A strategy and management consultancy advising governments and multinational corporations on strategy, organizational transformation and operational excellence.",
     "business_model":"Corporate strategy; government advisory; transformation; operational improvement.","customers":"Governments, multinational corporations and large organizations undergoing strategic change.",
     "earnings":"Consulting demand, government projects, corporate restructuring and regulatory oversight.","metrics":"Consulting bookings, project pipeline, utilization, fee income, margins and major-account retention.","catalysts":"Corporate restructuring, government advisory spending, transformation programs and stronger consulting demand."},
    {"ticker":"PRAD","name":"Pinnacle Risk Advisors","sector":"Strategy & Consulting","industry":"Insurance Brokerage & Risk Advisory","base":900,"volatility":"0.4%",
     "snapshot":"A global insurance broker and risk consultant helping businesses identify risks, arrange insurance and build enterprise risk-management programs.",
     "business_model":"Insurance brokerage; enterprise risk advisory; cyber-risk consulting; risk management.","customers":"Large and mid-sized businesses with complex commercial risk exposures.",
     "earnings":"Corporate insurance demand, cyber risk, brokerage contracts and growth in commercial insurance.","metrics":"Brokerage revenue, client retention, new business wins, commission income and risk-advisory pipeline.","catalysts":"Cyberattacks, large brokerage mandates, rising commercial insurance demand and stronger enterprise-risk spending."},
]
COMPANY_DIRECTORY_BY_TICKER = {c["ticker"]: c for c in COMPANY_DIRECTORY}


# ── Persistent game state (SQLite) ────────────────────────────────────────────

def _db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn

def _json_safe_state():
    # The threading.Lock cannot be serialized; everything else here is JSON-safe.
    return {
        "players": state["players"],
        "game_active": state["game_active"],
        "news_feed": state["news_feed"],
        "price_history": state["price_history"],
        "prices": state["prices"],
    }

def init_database():
    conn = _db_connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()

def _write_state_snapshot(snapshot):
    """Write an already-captured state snapshot to SQLite. Never holds the game lock."""
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    conn = _db_connect()
    try:
        conn.execute(
            """INSERT INTO game_state(id, state_json, updated_at)
               VALUES(1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 state_json=excluded.state_json,
                 updated_at=excluded.updated_at""",
            (payload, datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
    finally:
        conn.close()

def capture_state_snapshot():
    """Capture a consistent JSON-safe snapshot while holding the short game lock."""
    with state["lock"]:
        return copy.deepcopy(_json_safe_state())

def save_state():
    """Compatibility helper: capture under lock, then write after releasing it."""
    _write_state_snapshot(capture_state_snapshot())

def request_checkpoint():
    """Mark that in-memory state should be checkpointed by the background saver."""
    state["checkpoint_event"].set()

def load_state():
    conn = _db_connect()
    try:
        row = conn.execute(
            "SELECT state_json FROM game_state WHERE id=1"
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return False

    saved = json.loads(row[0])

    # Restore only the mutable game state. Keep the current code's lock/admin
    # session objects intact.
    state["players"] = saved.get("players", {})
    state["game_active"] = saved.get("game_active", False)
    state["news_feed"] = saved.get("news_feed", [])
    state["price_history"] = saved.get("price_history", {})
    state["prices"] = saved.get("prices", state["prices"])

    # Defensive defaults for players created by older versions.
    for p in state["players"].values():
        p.setdefault("portfolio", {})
        p.setdefault("avg_cost", {})
        p.setdefault("trades", 0)

    # Make sure every current ticker has a history list.
    for ticker in state["prices"]:
        state["price_history"].setdefault(ticker, [])

    return True

def backup_database():
    """Create a consistent SQLite backup without stopping the game."""
    if not os.path.exists(DB_PATH):
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = os.path.join(BACKUP_DIR, f"stockex_{stamp}.db")
    source = sqlite3.connect(DB_PATH, timeout=10)
    dest = sqlite3.connect(destination)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()

    # Keep the newest 20 backups.
    backups = sorted(
        Path(BACKUP_DIR).glob("stockex_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    for old in backups[20:]:
        try:
            old.unlink()
        except OSError:
            pass

def persistence_loop():
    """Persist periodically without ever holding the game lock during SQLite I/O."""
    last_backup = time.monotonic()
    while True:
        # Wake early when a state-changing request asks for a checkpoint, but
        # coalesce bursts so 100 simultaneous trades do not cause 100 SQLite writes.
        state["checkpoint_event"].wait(STATE_CHECKPOINT_INTERVAL)
        state["checkpoint_event"].clear()
        try:
            _write_state_snapshot(capture_state_snapshot())
            if time.monotonic() - last_backup >= BACKUP_INTERVAL:
                backup_database()
                last_backup = time.monotonic()
        except Exception as exc:
            print(f"[PERSISTENCE] backup error: {exc}")

init_database()
load_state()

# Initialise price history
for _t in state["prices"]:
    state["price_history"].setdefault(_t, [])

# If this is a brand-new database, create the first checkpoint.
if not os.path.exists(DB_PATH):
    save_state()

threading.Thread(target=persistence_loop, daemon=True, name="stockex-backup").start()

# ── Helpers ───────────────────────────────────────────────────────────────────

def esc(value):
    """Escape untrusted text before placing it in server-rendered HTML."""
    return html.escape(str(value), quote=True)

def generate_token():
    return secrets.token_urlsafe(32)

def get_player(token):
    # Return the actual in-memory player object. Callers that mutate it must
    # hold state["lock"]; read-only rendering is safe enough for this workload.
    return state["players"].get(token)

def portfolio_value(player):
    total = player["balance"]
    for ticker, qty in player["portfolio"].items():
        total += state["prices"].get(ticker, {}).get("current", 0) * qty
    return round(total, 2)

def apply_news_impact(news_item):
    for ticker, pct in news_item["impacts"].items():
        if ticker in state["prices"]:
            state["prices"][ticker]["current"] = round(
                state["prices"][ticker]["current"] * (1 + pct / 100), 2)

def do_full_reset():
    """Reset everything except admin sessions and news pool."""
    with state["lock"]:
        state["players"].clear()
        state["news_feed"].clear()
        state["game_active"] = False
        for ticker, p in state["prices"].items():
            p["current"] = p["base"]
        for ticker in state["price_history"]:
            state["price_history"][ticker].clear()
    request_checkpoint()

# ── Background price fluctuation thread ──────────────────────────────────────

def price_tick():
    """Runs every TICK_INTERVAL seconds, nudges prices with mean-reversion Brownian motion."""
    while True:
        import time; time.sleep(TICK_INTERVAL)
        if not state["game_active"]:
            continue
        ts = datetime.now().strftime("%H:%M:%S")
        with state["lock"]:
            for ticker, p in state["prices"].items():
                vol  = VOLATILITY.get(ticker, 0.005)
                base = p["base"]
                cur  = p["current"]
                # Gaussian shock
                shock = random.gauss(0, vol)
                # Mean reversion: nudge back toward base proportionally
                reversion = MEAN_REVERSION * (base - cur) / base
                new_price = cur * (1 + shock + reversion)
                # Hard floor at 40% of base, ceiling at 250% of base
                new_price = max(base * 0.40, min(base * 2.50, new_price))
                p["current"] = round(new_price, 2)
                # Store history (keep last 40 ticks)
                hist = state["price_history"][ticker]
                hist.append((ts, p["current"]))
                if len(hist) > 40:
                    hist.pop(0)
        request_checkpoint()

threading.Thread(target=price_tick, daemon=True, name="stockex-price-engine").start()

# ── CSS ───────────────────────────────────────────────────────────────────────

COMMON_CSS = """
:root{
  --bg:#0f1117;--bg2:#161a24;--bg3:#1e2330;
  --card:#1a1f2e;--card2:#222840;
  --border:rgba(255,255,255,0.07);--border2:rgba(255,255,255,0.16);
  --text:#e8eaed;--text2:#8c94a8;--text3:#555f78;
  --blue:#3b82f6;--blue2:#1d4ed8;--blue-glow:rgba(59,130,246,0.15);
  --green:#22c55e;--green-dim:#14532d;
  --red:#ef4444;--red-dim:#7f1d1d;
  --orange:#f97316;--gold:#f59e0b;
  --radius:8px;--radius-lg:14px;
  --font:'Inter',system-ui,-apple-system,sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--font);background:var(--bg);color:var(--text);line-height:1.6;min-height:100vh}
a{color:var(--blue);text-decoration:none}
input,select{font-family:inherit}
.btn{display:inline-flex;align-items:center;gap:6px;padding:10px 20px;border-radius:var(--radius);border:none;font-size:14px;font-weight:500;cursor:pointer;transition:all .15s}
.btn-primary{background:var(--blue);color:#fff}.btn-primary:hover{opacity:.88}
.btn-success{background:var(--green);color:#fff}.btn-success:hover{opacity:.88}
.btn-danger{background:var(--red);color:#fff}.btn-danger:hover{opacity:.88}
.btn-ghost{background:transparent;border:1px solid var(--border2);color:var(--text)}.btn-ghost:hover{background:var(--bg3)}
.btn-warn{background:var(--gold);color:#000}.btn-warn:hover{opacity:.88}
.btn-sm{padding:6px 14px;font-size:13px}
.btn:disabled{opacity:.35;cursor:not-allowed}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:24px}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:500}
.badge-up{background:var(--green-dim);color:var(--green)}
.badge-dn{background:var(--red-dim);color:var(--red)}
.badge-neu{background:var(--bg3);color:var(--text2)}
.badge-blue{background:var(--blue-glow);color:var(--blue)}
.up{color:var(--green)}.dn{color:var(--red)}
.label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--text3);font-weight:500}
.flash{padding:12px 16px;border-radius:var(--radius);font-size:14px;margin-bottom:16px}
.flash-err{background:var(--red-dim);border:1px solid var(--red);color:#fca5a5}
.flash-ok{background:var(--green-dim);border:1px solid var(--green);color:#86efac}
.flash-warn{background:#451a03;border:1px solid var(--gold);color:#fde68a}
"""

def page(title, body):
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title} — STOCK EX</title>
<style>{COMMON_CSS}</style>
</head><body>{body}</body></html>"""

# ── Register page ─────────────────────────────────────────────────────────────

def render_register(flash="", flash_type="err"):
    fh = f'<div class="flash flash-{flash_type}">{flash}</div>' if flash else ""
    badge = ('<span class="badge badge-up">🟢 Game Live — join now!</span>'
             if state["game_active"] else
             '<span class="badge badge-neu">⏳ Waiting for admin to start</span>')
    return page("Register", f"""
<style>
body{{display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px}}
.wrap{{width:100%;max-width:420px}}
.logo{{font-size:28px;font-weight:700;letter-spacing:-.03em;text-align:center;margin-bottom:3px}}
.logo em{{font-style:normal;color:var(--blue)}}
.logo .ex{{font-size:20px}}
.sub{{text-align:center;color:var(--text2);font-size:14px;margin-bottom:14px}}
.field{{margin-bottom:16px}}
.field label{{display:block;font-size:13px;color:var(--text2);margin-bottom:6px;font-weight:500}}
.field input{{width:100%;background:var(--bg3);border:1px solid var(--border2);border-radius:var(--radius);padding:10px 14px;color:var(--text);font-size:15px;outline:none}}
.field input:focus{{border-color:var(--blue)}}
</style>
<div class="wrap">
  <div style="text-align:center">{LOGO_SVG}</div>
  <div class="logo"><em>STOCK</em><span class="ex">EX</span></div>
  <div class="sub">The Ultimate Trading Challenge</div>
  <div style="text-align:center;margin-bottom:24px">{badge}</div>
  {fh}
  <div class="card">
    <form method="POST" action="/register">
      <div class="field"><label>Your name</label><input name="name" placeholder="e.g. Arjun Sharma" required autocomplete="off"/></div>
      <div class="field"><label>Team name</label><input name="team" placeholder="e.g. RiskRaptors" required autocomplete="off"/></div>
      <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:12px">Join the game →</button>
    </form>
  </div>
  <div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-top:20px"><a href="/directory" class="btn btn-ghost btn-sm">View Company Directory</a><a href="/trade" class="btn btn-ghost btn-sm">Go to Trading Floor</a></div>
</div>""")


# ── Company Directory page ────────────────────────────────────────────────────

def render_directory(player=None):
    sectors = [
        ("Insurance", "Five insurers/reinsurers whose economics revolve around premiums, underwriting, claims, catastrophe exposure, and reinsurance pricing."),
        ("Banking & Investment", "Four financial firms exposed to interest rates, lending, trading, capital markets, wealth creation and regulation."),
        ("Strategy & Consulting", "Three professional-services businesses driven by corporate spending, technology transformation, risk advisory, deal activity, and regulation."),
    ]

    cards = ""
    for sector, sector_desc in sectors:
        companies = [c for c in COMPANY_DIRECTORY if c["sector"] == sector]
        cards += f"""
        <section class="dir-section">
          <div class="dir-section-head">
            <div>
              <div class="dir-section-title">{sector}</div>
              <div class="dir-section-desc">{sector_desc}</div>
            </div>
            <span class="badge badge-blue">{len(companies)} companies</span>
          </div>
          <div class="dir-grid">
        """
        for c in companies:
            cards += f"""
            <article class="dir-card" id="company-{c['ticker']}">
              <div class="dir-card-top">
                <div>
                  <div class="dir-ticker">{c['ticker']}</div>
                  <div class="dir-name">{c['name']}</div>
                </div>
                <div class="dir-price">₹{c['base']:,}</div>
              </div>
              <div class="dir-meta">
                <span>{c['industry']}</span>
                <span>Vol. {c['volatility']} / tick</span>
              </div>
              <p class="dir-snapshot">{c['snapshot']}</p>
              <details>
                <summary>View investor guide</summary>
                <div class="dir-details">
                  <div><span>Business Model</span><p>{c['business_model']}</p></div>
                  <div><span>Customer Base</span><p>{c['customers']}</p></div>
                  <div><span>What Drives Earnings</span><p>{c['earnings']}</p></div>
                  <div><span>Key Metrics to Watch</span><p>{c['metrics']}</p></div>
                  <div><span>Potential Catalysts</span><p>{c['catalysts']}</p></div>
                </div>
              </details>
            </article>
            """
        cards += "</div></section>"

    nav_right = (
        '<a href="/trade" class="btn btn-primary btn-sm">← Back to Trading</a>'
        if player else
        '<a href="/" class="btn btn-ghost btn-sm">← Registration</a>'
    )

    return page("Company Directory", f"""
    <style>
      body{{background:var(--bg)}}
      .dir-topbar{{background:var(--bg2);border-bottom:1px solid var(--border);padding:12px 20px;display:flex;align-items:center;justify-content:space-between;gap:14px;position:sticky;top:0;z-index:50;flex-wrap:wrap}}
      .dir-brand{{font-size:17px;font-weight:700}}.dir-brand em{{font-style:normal;color:var(--blue)}}.dir-brand .ex{{font-size:12px}}
      .dir-main{{max-width:1240px;margin:0 auto;padding:28px 20px 50px}}
      .dir-hero{{margin-bottom:28px}} .dir-hero h1{{font-size:30px;letter-spacing:-.02em;margin-bottom:6px}}
      .dir-hero p{{color:var(--text2);max-width:850px;font-size:14px}}
      .dir-note{{margin-top:14px;padding:12px 15px;background:var(--blue-glow);border:1px solid rgba(59,130,246,.25);border-radius:var(--radius);color:#c9dcff;font-size:13px}}
      .dir-section{{margin-top:30px}}
      .dir-section-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:14px}}
      .dir-section-title{{font-size:20px;font-weight:650}} .dir-section-desc{{color:var(--text2);font-size:13px;max-width:850px;margin-top:3px}}
      .dir-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}}
      .dir-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:19px;transition:border-color .15s,transform .15s}}
      .dir-card:hover{{border-color:var(--border2);transform:translateY(-1px)}}
      .dir-card-top{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}
      .dir-ticker{{font-size:12px;font-weight:700;color:var(--blue);letter-spacing:.08em}}
      .dir-name{{font-size:18px;font-weight:650;margin-top:2px}} .dir-price{{font-size:17px;font-weight:700;white-space:nowrap}}
      .dir-meta{{display:flex;justify-content:space-between;gap:10px;margin:12px 0;padding:8px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border);font-size:11px;color:var(--text3)}}
      .dir-snapshot{{font-size:13px;color:var(--text2);line-height:1.55;margin-bottom:12px}}
      details{{border-top:1px solid var(--border);padding-top:11px}} summary{{cursor:pointer;color:var(--blue);font-size:13px;font-weight:550}}
      .dir-details{{display:grid;gap:11px;margin-top:13px}}
      .dir-details span{{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--text3);font-weight:600;margin-bottom:3px}}
      .dir-details p{{font-size:12px;color:var(--text2);line-height:1.5}}
      @media(max-width:650px){{.dir-grid{{grid-template-columns:1fr}}.dir-main{{padding:22px 14px 40px}}.dir-hero h1{{font-size:25px}}}}
    </style>
    <div class="dir-topbar">
      <div class="dir-brand"><em>STOCK</em><span class="ex">EX</span> <span style="font-size:13px;color:var(--text3);font-weight:400">Company Directory</span></div>
      <div style="display:flex;gap:8px;align-items:center">{nav_right}</div>
    </div>
    <main class="dir-main">
      <div class="dir-hero">
        <h1>Company Directory</h1>
        <p>Use this guide to understand the 12 fictional companies before making trading decisions. Each profile explains the business model, customers, earnings drivers, key metrics and potential catalysts.</p>
        <div class="dir-note">Prices shown here are the <strong>base prices</strong>. Live prices may move during the simulation due to routine volatility, mean reversion and event shocks.</div>
      </div>
      {cards}
    </main>
    """)


# ── Trading Floor ─────────────────────────────────────────────────────────────

def render_trade(player, flash="", flash_type="err"):
    fh = f'<div class="flash flash-{flash_type}">{flash}</div>' if flash else ""
    pv   = portfolio_value(player)
    gain = pv - 100000
    gc   = "up" if gain >= 0 else "dn"
    gs   = "+" if gain >= 0 else ""

    price_cards = ""
    for ticker, p in state["prices"].items():
        chg  = round((p["current"] - p["base"]) / p["base"] * 100, 2)
        cc   = "up" if chg >= 0 else "dn"
        arrow = "▲" if chg >= 0 else "▼"
        held  = player["portfolio"].get(ticker, 0)
        sell_attr = '' if held > 0 else 'disabled'
        price_cards += f"""
<div class="p-card" id="pc-{ticker}" data-base="{p['base']}" data-color="{p['color']}">
  <div style="display:flex;justify-content:space-between;align-items:start">
    <div>
      <div class="label" style="color:{p['color']}">{ticker}</div>
      <div style="font-size:14px;font-weight:500;margin-top:3px;color:var(--text2)">{esc(p['name'])}</div>
    </div>
    <div style="text-align:right">
      <div class="pc-price" style="font-size:22px;font-weight:700;font-variant-numeric:tabular-nums">₹{p['current']:,.2f}</div>
      <div class="pc-chg {cc}" style="font-size:13px">{arrow} {abs(chg)}%</div>
    </div>
  </div>
  <canvas class="pc-spark" width="220" height="36" style="width:100%;margin:10px 0 2px;display:block"></canvas>
  <div style="padding-top:10px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;gap:8px">
    <span style="font-size:13px;color:var(--text2)">Held: <strong class="pc-held" style="color:var(--text)">{held}</strong></span>
    <div style="display:flex;gap:6px;align-items:center">
      <input type="number" class="qty-input" id="qty-{ticker}" min="1" value="1"
             style="width:58px;background:var(--bg3);border:1px solid var(--border2);border-radius:var(--radius);padding:5px 8px;color:var(--text);font-size:14px;text-align:center"/>
      <button class="btn btn-success btn-sm" onclick="doTrade('{ticker}','buy')">Buy</button>
      <button class="btn btn-danger btn-sm" id="sell-{ticker}" onclick="doTrade('{ticker}','sell')" {sell_attr}>Sell</button>
    </div>
  </div>
</div>"""

    news_html = ""
    if state["news_feed"]:
        for n in reversed(state["news_feed"]):
            impacts = ", ".join(f"{t} {'+' if v>0 else ''}{v}%" for t,v in n["impacts"].items())
            news_html += f"""
<div class="news-item">
  <div style="display:flex;justify-content:space-between;align-items:start;gap:10px">
    <div>
      <div style="font-weight:600;font-size:14px">{n['title']}</div>
      <div style="font-size:13px;color:var(--text2);margin-top:3px">{n['description']}</div>
    </div>
    <span class="badge badge-blue" style="white-space:nowrap;flex-shrink:0">{n['category']}</span>
  </div>
  <div style="margin-top:7px;font-size:12px;color:var(--text3)">{n['released_at']}</div>
</div>"""
    else:
        news_html = '<p style="color:var(--text3);font-size:14px;text-align:center;padding:20px 0">No news yet — stay tuned.</p>'

    port_rows = ""
    for ticker, qty in player["portfolio"].items():
        if qty > 0:
            cp = state["prices"][ticker]["current"]
            buy_price = player["avg_cost"].get(ticker, cp)
            val = round(cp * qty, 2)
            pchg = round((cp - buy_price) / buy_price * 100, 2) if buy_price else 0.0
            pcc = "up" if pchg >= 0 else "dn"
            parrow = "▲" if pchg >= 0 else "▼"
            port_rows += (f"<tr><td style='color:{state['prices'][ticker]['color']};font-weight:600'>{ticker}</td>"
                          f"<td>{state['prices'][ticker]['name']}</td><td>{qty}</td>"
                          f"<td>₹{buy_price:,.2f}</td><td>₹{cp:,.2f}</td>"
                          f"<td class='{pcc}'>{parrow} {abs(pchg)}%</td>"
                          f"<td>₹{val:,.2f}</td>"
                          f"<td><div style='display:flex;gap:5px;align-items:center'>"
                          f"<input type='number' class='qty-input' id='pqty-{ticker}' min='1' value='1' "
                          f"style='width:52px;background:var(--bg3);border:1px solid var(--border2);border-radius:var(--radius);padding:5px 6px;color:var(--text);font-size:13px;text-align:center'/>"
                          f"<button class='btn btn-success btn-sm' onclick=\"doPortTrade('{ticker}','buy')\">Buy</button>"
                          f"<button class='btn btn-danger btn-sm' onclick=\"doPortTrade('{ticker}','sell')\">Sell</button>"
                          f"</div></td></tr>")
    if not port_rows:
        port_rows = '<tr><td colspan="8" style="text-align:center;color:var(--text3);padding:20px">No positions yet.</td></tr>'

    game_banner = ""
    if not state["game_active"]:
        game_banner = '<div style="background:var(--bg3);border:1px solid var(--border2);border-radius:var(--radius);padding:12px 16px;font-size:14px;color:var(--text2);margin-bottom:16px;text-align:center">⏳ Game not started yet. Trading is disabled.</div>'

    # Serialize history for JS
    hist_json = json.dumps({t: state["price_history"][t] for t in state["prices"]})

    return page("Trading Floor", f"""
<style>
.topbar{{background:var(--bg2);border-bottom:1px solid var(--border);padding:12px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px;position:sticky;top:0;z-index:50;flex-wrap:wrap}}
.brand{{font-size:16px;font-weight:700}}.brand em{{font-style:normal;color:var(--blue)}}
.brand .ex{{font-size:12px}}
.pill{{background:var(--bg3);border-radius:var(--radius);padding:5px 12px;font-size:13px;display:flex;align-items:center;gap:6px}}
.main{{max-width:1240px;margin:0 auto;padding:20px;display:grid;grid-template-columns:1fr 300px;gap:20px}}
@media(max-width:820px){{.main{{grid-template-columns:1fr}}}}
.p-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}}
.p-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:16px;transition:border-color .2s}}
.p-card:hover{{border-color:var(--border2)}}
.sidebar{{display:flex;flex-direction:column;gap:16px}}
.news-item{{padding:12px 0;border-bottom:1px solid var(--border)}}.news-item:last-child{{border-bottom:none}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:8px 12px;background:var(--bg3);color:var(--text3);font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
td{{padding:9px 12px;border-bottom:1px solid var(--border)}}
.portfolio-table-wrap{{height:300px;overflow:auto;border-top:1px solid var(--border);scrollbar-gutter:stable}}
.portfolio-table-wrap table{{min-width:900px}}
.portfolio-table-wrap thead th{{position:sticky;top:0;z-index:2}}
@media(max-width:820px){{.portfolio-table-wrap{{height:280px}}}}
#toast{{position:fixed;bottom:20px;right:20px;background:var(--card2);border:1px solid var(--border2);border-radius:var(--radius);padding:11px 18px;font-size:14px;display:none;z-index:300;box-shadow:0 8px 32px rgba(0,0,0,.5);transition:opacity .3s}}
.qty-input{{outline:none}}
#newsModal{{position:fixed;inset:0;background:rgba(0,0,0,.75);display:none;align-items:center;justify-content:center;z-index:500;backdrop-filter:blur(4px)}}
#newsModal.show{{display:flex}}
.nm-box{{background:var(--card2);border:2px solid var(--blue);border-radius:var(--radius-lg);max-width:520px;width:92%;padding:26px;animation:popIn .35s cubic-bezier(.34,1.56,.64,1);box-shadow:0 20px 60px rgba(0,0,0,.6)}}
@keyframes popIn{{from{{transform:scale(.7);opacity:0}}to{{transform:scale(1);opacity:1}}}}
.nm-badge{{display:inline-block;background:var(--red);color:#fff;font-size:11px;font-weight:700;letter-spacing:.1em;padding:4px 10px;border-radius:4px;margin-bottom:12px}}
.nm-title{{font-size:22px;font-weight:700;margin-bottom:8px}}
.nm-cat{{font-size:12px;color:var(--text3);text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px}}
.nm-desc{{font-size:14px;color:var(--text2);line-height:1.55;margin-bottom:16px}}
.nm-impacts{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}}
.nm-imp{{background:var(--bg3);border:1px solid var(--border2);border-radius:6px;padding:6px 10px;font-size:13px;font-weight:600}}
.nm-imp.up{{color:var(--green)}}.nm-imp.dn{{color:var(--red)}}
</style>
<div class="topbar">
<div class="brand" style="display:flex;align-items:center">{LOGO_SVG.replace("viewBox=\"0 0 680 260\"", "viewBox=\"0 0 680 260\" style=\"height:36px;width:auto\"")}</div>
  <div class="brand"><em>STOCK</em><span class="ex">EX</span> <span style="font-size:13px;color:var(--text3);font-weight:400">Trading Floor</span></div>
   <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
     <a href="/directory" class="btn btn-ghost btn-sm">Company Directory</a>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <div class="pill">👤 {esc(player['name'])}</div>
    <div class="pill">🏷 {esc(player['team'])}</div>
    <div class="pill">💰 <strong id="live-bal">₹{player['balance']:,.2f}</strong></div>
    <div class="pill">📊 <strong id="live-pv" class="{gc}">₹{pv:,.2f}</strong></div>
    <div class="pill">P&L: <span id="live-pnl" class="{gc}">{gs}₹{abs(gain):,.2f}</span></div>
  </div>
</div>
{fh}
<div class="main">
  <div>
    {game_banner}
    <div class="label" style="margin-bottom:14px">STOCK<span style="font-size:8px">EX</span> Market</div>
    <div class="p-grid">{price_cards}</div>
    <div class="card portfolio-card" style="margin-top:20px;padding:0;overflow:hidden">
      <div class="label" style="padding:14px 16px 10px">My Portfolio</div>
      <div class="portfolio-table-wrap">
        <table>
          <thead><tr><th>Ticker</th><th>Stock</th><th>Qty</th><th>Buy Price</th><th>Current Price</th><th>Change</th><th>Value</th><th>Action</th></tr></thead>
          <tbody id="port-body">{port_rows}</tbody>
        </table>
      </div>
    </div>
  </div>
  <div class="sidebar">
    <div class="card">
      <div class="label" style="margin-bottom:10px">📰 News Feed</div>
      <div id="news-feed">{news_html}</div>
    </div>
  </div>
</div>
<div id="newsModal" onclick="closeNews(event)">
  <div class="nm-box" onclick="event.stopPropagation()">
    <div class="nm-badge">📢 BREAKING NEWS</div>
    <div class="nm-cat" id="nm-cat"></div>
    <div class="nm-title" id="nm-title"></div>
    <div class="nm-desc" id="nm-desc"></div>
    <button class="btn btn-primary" style="width:100%" onclick="closeNews()">Got it — back to trading</button>
  </div>
</div>
<div id="toast"></div>
<script>
const PRICES_META = {json.dumps({t:{"base":p["base"],"name":p["name"],"color":p["color"]} for t,p in state["prices"].items()})};
let priceHistory = {hist_json};
let lastNewsCount = {len(state["news_feed"])};
let newsFeedCache = {json.dumps(state["news_feed"])};

// ── Sparkline renderer ────────────────────────────────────────────────────────
function drawSpark(canvas, ticker, color) {{
  const hist = priceHistory[ticker];
  if (!hist || hist.length < 2) return;
  const vals = hist.map(h => h[1]);
  const min = Math.min(...vals), max = Math.max(...vals);
  const w = canvas.width, h = canvas.height;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, w, h);
  const range = max - min || 1;
  const pts = vals.map((v, i) => [i / (vals.length - 1) * w, h - ((v - min) / range) * (h - 4) - 2]);
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, color + '55');
  grad.addColorStop(1, color + '00');
  ctx.beginPath();
  ctx.moveTo(pts[0][0], h);
  pts.forEach(([x, y]) => ctx.lineTo(x, y));
  ctx.lineTo(pts[pts.length-1][0], h);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();
  ctx.beginPath();
  pts.forEach(([x, y], i) => i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y));
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.stroke();
}}

function drawAllSparks() {{
  document.querySelectorAll('.p-card').forEach(card => {{
    const ticker = card.id.replace('pc-', '');
    const canvas = card.querySelector('.pc-spark');
    const color = card.dataset.color;
    if (canvas) drawSpark(canvas, ticker, color);
  }});
}}

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(msg, ok=true) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.display = 'block';
  t.style.borderColor = ok ? 'var(--green)' : 'var(--red)';
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.style.display = 'none', 3200);
}}

// ── Trade ─────────────────────────────────────────────────────────────────────
async function doTrade(ticker, action) {{
  const qty = parseInt(document.getElementById('qty-' + ticker).value) || 1;
  const res = await fetch('/api/trade', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ticker, action, qty}})
  }});
  const d = await res.json();
  toast(d.msg, d.ok);
  if (d.ok) {{
    const y = window.scrollY;
    await refresh();
    window.scrollTo(0, y);
  }}
}}

// Trade triggered from the portfolio table (reads its own qty input)
async function doPortTrade(ticker, action) {{
  const el = document.getElementById('pqty-' + ticker);
  const qty = parseInt(el ? el.value : 1) || 1;
  const res = await fetch('/api/trade', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ticker, action, qty}})
  }});
  const d = await res.json();
  toast(d.msg, d.ok);
  if (d.ok) {{
    const y = window.scrollY;
    await refresh();
    window.scrollTo(0, y);
  }}
}}

// ── Refresh loop ──────────────────────────────────────────────────────────────
async function refresh() {{
  const r = await fetch('/api/state');
  const d = await r.json();
  if (!d.ok) return;
  // Prices & sparks
  priceHistory = d.price_history;
  Object.entries(d.prices).forEach(([t, p]) => {{
    const card = document.getElementById('pc-' + t);
    if (!card) return;
    const base = parseFloat(card.dataset.base);
    const chg  = ((p.current - base) / base * 100).toFixed(2);
    const up   = chg >= 0;
    card.querySelector('.pc-price').textContent = '₹' + p.current.toLocaleString('en-IN', {{minimumFractionDigits:2}});
    const chgEl = card.querySelector('.pc-chg');
    chgEl.textContent = (up ? '▲ ' : '▼ ') + Math.abs(chg) + '%';
    chgEl.className = 'pc-chg ' + (up ? 'up' : 'dn');
    const heldEl = card.querySelector('.pc-held');
    const held = d.player.portfolio[t] || 0;
    if (heldEl) heldEl.textContent = held;
    const sellBtn = document.getElementById('sell-' + t);
    if (sellBtn) sellBtn.disabled = held === 0;
  }});
  drawAllSparks();
  // Stats
  const bal = d.player.balance;
  const pv  = d.player.portfolio_value;
  const gain = pv - 100000;
  document.getElementById('live-bal').textContent = '₹' + bal.toLocaleString('en-IN', {{minimumFractionDigits:2}});
  const pvEl = document.getElementById('live-pv');
  pvEl.textContent = '₹' + pv.toLocaleString('en-IN', {{minimumFractionDigits:2}});
  pvEl.className = gain >= 0 ? 'up' : 'dn';
  const pnlEl = document.getElementById('live-pnl');
  pnlEl.textContent = (gain >= 0 ? '+' : '') + '₹' + Math.abs(gain).toLocaleString('en-IN', {{minimumFractionDigits:2}});
  pnlEl.className = gain >= 0 ? 'up' : 'dn';
  // Portfolio table
  const pb = document.getElementById('port-body');
  // Preserve any qty values the player has already typed into portfolio rows
  const prevQty = {{}};
  pb.querySelectorAll('input[id^="pqty-"]').forEach(inp => {{ prevQty[inp.id] = inp.value; }});
  if (Object.keys(d.player.portfolio).filter(t => d.player.portfolio[t] > 0).length === 0) {{
    pb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text3);padding:20px">No positions yet.</td></tr>';
  }} else {{
    pb.innerHTML = Object.entries(d.player.portfolio).filter(([,q]) => q > 0).map(([t, q]) => {{
      const pr = d.prices[t].current;
      const buyPrice = (d.player.avg_cost && d.player.avg_cost[t]) || pr;
      const pchg = ((pr - buyPrice) / buyPrice * 100).toFixed(2);
      const pup  = pchg >= 0;
      const val = (pr * q).toLocaleString('en-IN', {{minimumFractionDigits:2}});
      const qv = prevQty['pqty-' + t] || 1;
      return `<tr><td style="color:${{d.prices[t].color}};font-weight:600">${{t}}</td><td>${{PRICES_META[t].name}}</td><td>${{q}}</td><td>₹${{buyPrice.toLocaleString('en-IN',{{minimumFractionDigits:2}})}}</td><td>₹${{pr.toLocaleString('en-IN',{{minimumFractionDigits:2}})}}</td><td class="${{pup ? 'up' : 'dn'}}">${{pup ? '▲' : '▼'}} ${{Math.abs(pchg)}}%</td><td>₹${{val}}</td><td><div style="display:flex;gap:5px;align-items:center"><input type="number" class="qty-input" id="pqty-${{t}}" min="1" value="${{qv}}" style="width:52px;background:var(--bg3);border:1px solid var(--border2);border-radius:var(--radius);padding:5px 6px;color:var(--text);font-size:13px;text-align:center"/><button class="btn btn-success btn-sm" onclick="doPortTrade('${{t}}','buy')">Buy</button><button class="btn btn-danger btn-sm" onclick="doPortTrade('${{t}}','sell')">Sell</button></div></td></tr>`;
    }}).join('');
  }}
  // News popup
  const feed = d.news_feed || [];
  if (feed.length > lastNewsCount) {{
    const latest = feed[feed.length - 1];
    showNewsModal(latest);
    lastNewsCount = feed.length;
    newsFeedCache = feed;
    setTimeout(() => location.reload(), 8000);
  }}
}}


function showNewsModal(n) {{
  document.getElementById('nm-cat').textContent = n.category || '';
  document.getElementById('nm-title').textContent = n.title || '';
  document.getElementById('nm-desc').textContent = n.description || '';
  document.getElementById('newsModal').classList.add('show');
  try {{
    const ctx = new (window.AudioContext||window.webkitAudioContext)();
    const o = ctx.createOscillator(); const g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination);
    o.frequency.value = 880; g.gain.value = 0.08;
    o.start(); o.frequency.exponentialRampToValueAtTime(440, ctx.currentTime+0.25);
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime+0.4);
    o.stop(ctx.currentTime+0.4);
  }} catch(e) {{}}
}}
function closeNews(e) {{
  if (e && e.target.id !== 'newsModal' && e.type === 'click') {{}}
  document.getElementById('newsModal').classList.remove('show');
}}

drawAllSparks();
setInterval(refresh, 3500);
</script>""")

# ── Admin Panel ───────────────────────────────────────────────────────────────

def render_admin(flash="", flash_type="ok"):
    fh = f'<div class="flash flash-{flash_type}">{flash}</div>' if flash else ""
    game_active = state["game_active"]
    toggle_label = "⏸ Pause Game" if game_active else "▶ Start Game"
    toggle_cls   = "btn-danger" if game_active else "btn-success"
    game_badge   = ('<span class="badge badge-up">🟢 Live</span>' if game_active
                    else '<span class="badge badge-neu">⏸ Paused</span>')

    # ── Stat cards
    total_trades = sum(p["trades"] for p in state["players"].values())

    # ── Leaderboard
    sorted_players = sorted(state["players"].values(), key=portfolio_value, reverse=True)
    lb_rows = ""
    for i, p in enumerate(sorted_players):
        pv   = portfolio_value(p)
        gain = pv - 100000
        gc   = "up" if gain >= 0 else "dn"
        medal = ["🥇","🥈","🥉"][i] if i < 3 else f"#{i+1}"
        lb_rows += f"""
<tr>
  <td>{medal}</td>
  <td><strong>{esc(p['name'])}</strong></td>
  <td style="color:var(--text2)">{esc(p['team'])}</td>
  <td>₹{p['balance']:,.0f}</td>
  <td>₹{pv:,.0f}</td>
  <td class="{gc}">{'+'if gain>=0 else ''}₹{abs(gain):,.0f}</td>
  <td style="color:var(--text2)">{p['trades']}</td>
  <td style="font-size:12px;color:var(--text3)">{p['joined_at']}</td>
</tr>"""
    if not lb_rows:
        lb_rows = '<tr><td colspan="8" style="text-align:center;color:var(--text3);padding:24px">No players yet.</td></tr>'

    # ── News cards
    released_ids = {n["id"] for n in state["news_feed"]}
    news_cards = ""
    for n in state["news_pool"]:
        done = n["id"] in released_ids
        impacts = " · ".join(f"{t} {'+'if v>0 else ''}{v}%" for t,v in n["impacts"].items())
        badge   = '<span class="badge badge-up" style="font-size:11px">✓ Released</span>' if done else '<span class="badge badge-neu" style="font-size:11px">Pending</span>'
        btn     = ('<button class="btn btn-ghost btn-sm" disabled>Released</button>'
                   if done else
                   f'<form method="POST" action="/admin/release" style="display:inline"><input type="hidden" name="news_id" value="{n["id"]}"><button type="submit" class="btn btn-primary btn-sm">📢 Release</button></form>')
        news_cards += f"""
<div class="news-card {'released' if done else ''}">
  <div style="display:flex;justify-content:space-between;align-items:start;gap:10px;margin-bottom:8px">
    <div style="font-weight:600;font-size:14px">{n['title']}</div>{badge}
  </div>
  <div style="font-size:12px;color:var(--text3);margin-bottom:4px">{n['category']}</div>
  <div style="font-size:13px;color:var(--text2);margin-bottom:10px">{n['description']}</div>
  <div style="font-size:12px;color:var(--text3);margin-bottom:12px">↕ {impacts}</div>
  {btn}
</div>"""

    # ── Price rows
    price_rows = ""
    for ticker, p in state["prices"].items():
        chg = round((p["current"] - p["base"]) / p["base"] * 100, 2)
        gc  = "up" if chg >= 0 else "dn"
        hist = state["price_history"].get(ticker, [])
        spark_data = json.dumps([v for _, v in hist])
        price_rows += f"""
<tr>
  <td><strong style="color:{p['color']}">{ticker}</strong></td>
  <td>{esc(p['name'])}</td>
  <td>₹{p['base']}</td>
  <td class="{gc}" style="font-weight:600">₹{p['current']:,.2f}</td>
  <td class="{gc}">{'+'if chg>=0 else ''}{chg}%</td>
  <td><canvas id="as-{ticker}" width="120" height="28" data-vals='{spark_data}' data-color="{p['color']}" style="display:block"></canvas></td>
</tr>"""

    return page("Admin Panel", f"""
<style>
.topbar{{background:var(--bg2);border-bottom:1px solid var(--border);padding:14px 24px;display:flex;align-items:center;justify-content:space-between;gap:12px;position:sticky;top:0;z-index:50}}
.brand{{font-size:16px;font-weight:700}}.brand em{{font-style:normal;color:var(--blue)}}
.brand .ex{{font-size:12px}}
.main{{max-width:1340px;margin:0 auto;padding:24px}}
.sec-title{{font-size:17px;font-weight:600;margin-bottom:16px;display:flex;align-items:center;gap:8px}}
.stats-row{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}}
.stat-box{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:16px 22px;min-width:130px}}
.stat-box .n{{font-size:26px;font-weight:700;color:var(--blue)}}.stat-box .l{{font-size:13px;color:var(--text2);margin-top:2px}}
.ctrl-row{{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:28px;padding:18px;background:var(--card);border:1px solid var(--border);border-radius:var(--radius-lg)}}
.ctrl-row .spacer{{flex:1}}
.news-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-bottom:32px}}
.news-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:16px;transition:border-color .15s}}
.news-card:hover{{border-color:var(--border2)}}.news-card.released{{opacity:.5}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:9px 14px;background:var(--bg3);color:var(--text3);font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
td{{padding:10px 14px;border-bottom:1px solid var(--border)}}
.danger-zone{{margin-top:32px;padding:20px;border:1px solid var(--red-dim);border-radius:var(--radius-lg);background:#1a0a0a}}
.danger-zone h3{{color:var(--red);font-size:15px;margin-bottom:8px}}
.danger-zone p{{font-size:13px;color:var(--text2);margin-bottom:14px}}
</style>
<div class="topbar">
  <div class="brand"><em>STOCK</em><span class="ex">EX</span>&nbsp;<span style="font-size:13px;color:var(--gold);font-weight:500">⚡ Admin</span></div>
  <div style="display:flex;gap:10px;align-items:center">
    {game_badge}
    <a href="/" class="btn btn-ghost btn-sm" target="_blank">↗ Player view</a>
    <a href="/admin/logout" class="btn btn-ghost btn-sm">Logout</a>
  </div>
</div>
<div class="main">
  {fh}

  <!-- Stats -->
  <div class="stats-row">
    <div class="stat-box"><div class="n">{len(state['players'])}</div><div class="l">Players joined</div></div>
    <div class="stat-box"><div class="n">{len(state['news_feed'])}/{len(state['news_pool'])}</div><div class="l">News released</div></div>
    <div class="stat-box"><div class="n">{total_trades}</div><div class="l">Total trades</div></div>
    <div class="stat-box"><div class="n" id="adm-tick" style="font-size:20px">—</div><div class="l">Last price tick</div></div>
  </div>

  <!-- Controls -->
  <div class="ctrl-row">
    <span style="font-size:14px;font-weight:500">Game controls</span>
    <div class="spacer"></div>
    <form method="POST" action="/admin/toggle">
      <button type="submit" class="btn {toggle_cls}">{toggle_label}</button>
    </form>
    <form method="POST" action="/admin/reset_prices">
      <button type="submit" class="btn btn-ghost">↺ Reset prices</button>
    </form>
  </div>

  <!-- News -->
  <div class="sec-title">📰 News Clippings — Release Controls</div>
  <div class="news-grid">{news_cards}</div>

  <!-- Leaderboard -->
  <div class="sec-title">🏆 Live Leaderboard</div>
  <div class="card" style="padding:0;overflow:hidden;margin-bottom:28px">
    <table>
      <thead><tr><th>Rank</th><th>Name</th><th>Team</th><th>Cash</th><th>Portfolio</th><th>P&L</th><th>Trades</th><th>Joined</th></tr></thead>
      <tbody id="adm-lb">{lb_rows}</tbody>
    </table>
  </div>

  <!-- Price table -->
  <div class="sec-title">💹 Live Prices</div>
  <div class="card" style="padding:0;overflow:hidden;margin-bottom:28px">
    <table>
      <thead><tr><th>Ticker</th><th>Stock</th><th>Base</th><th>Current</th><th>Change</th><th>Trend</th></tr></thead>
      <tbody id="adm-prices">{price_rows}</tbody>
    </table>
  </div>

  <!-- Danger zone -->
  <div class="danger-zone">
    <h3>⚠ Danger Zone</h3>
    <p>Full reset clears all players, portfolios, trade history, and news — resets prices to base values. This cannot be undone.</p>
    <form method="POST" action="/admin/full_reset" onsubmit="return confirm('Full reset — are you absolutely sure? This deletes all players and resets everything.')">
      <button type="submit" class="btn btn-danger">🔄 Full Game Reset</button>
    </form>
  </div>
</div>

<script>
// Draw admin sparklines
function drawAdminSpark(canvas) {{
  const vals = JSON.parse(canvas.dataset.vals || '[]');
  const color = canvas.dataset.color;
  if (vals.length < 2) return;
  const w = canvas.width, h = canvas.height;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, w, h);
  const min = Math.min(...vals), max = Math.max(...vals);
  const range = max - min || 1;
  const pts = vals.map((v, i) => [i / (vals.length-1) * w, h - ((v-min)/range)*(h-3)-2]);
  ctx.beginPath();
  pts.forEach(([x,y],i) => i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y));
  ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
  // last dot
  ctx.beginPath();
  ctx.arc(pts[pts.length-1][0], pts[pts.length-1][1], 2.5, 0, Math.PI*2);
  ctx.fillStyle = color; ctx.fill();
}}
document.querySelectorAll('[id^="as-"]').forEach(drawAdminSpark);

// Live refresh
async function admRefresh() {{
  const r = await fetch('/api/admin_state');
  const d = await r.json();
  if (!d.ok) return;
  document.getElementById('adm-tick').textContent = d.last_tick || '—';
  // Rebuild price table rows inline
  const tbody = document.getElementById('adm-prices');
  if (tbody) {{
    tbody.querySelectorAll('canvas').forEach(c => {{
      const ticker = c.id.replace('as-','');
      const hist = d.price_history[ticker] || [];
      const vals = hist.map(h => h[1]);
      c.dataset.vals = JSON.stringify(vals);
      const p = d.prices[ticker];
      if (!p) return;
      const base = parseFloat(c.closest('tr').children[2].textContent.replace('₹','').replace(',',''));
      const chg = ((p.current - p.base) / p.base * 100).toFixed(2);
      const up = chg >= 0;
      const tr = c.closest('tr');
      tr.children[3].textContent = '₹' + p.current.toLocaleString('en-IN',{{minimumFractionDigits:2}});
      tr.children[3].className = up ? 'up' : 'dn';
      tr.children[4].textContent = (up?'+':'') + chg + '%';
      tr.children[4].className = up ? 'up' : 'dn';
      drawAdminSpark(c);
    }});
  }}
  // Leaderboard
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({{
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }}[ch]));
  const lb = document.getElementById('adm-lb');
  if (lb && d.leaderboard) {{
    const medals = ['🥇','🥈','🥉'];
    lb.innerHTML = d.leaderboard.map((p,i) => {{
      const gc = p.gain >= 0 ? 'up' : 'dn';
      return `<tr>
        <td>${{medals[i] || '#'+(i+1)}}</td>
        <td><strong>${{escapeHtml(p.name)}}</strong></td>
        <td style="color:var(--text2)">${{escapeHtml(p.team)}}</td>
        <td>₹${{p.balance.toLocaleString('en-IN',{{maximumFractionDigits:0}})}}</td>
        <td>₹${{p.pv.toLocaleString('en-IN',{{maximumFractionDigits:0}})}}</td>
        <td class="${{gc}}">${{p.gain>=0?'+':''}}₹${{Math.abs(p.gain).toLocaleString('en-IN',{{maximumFractionDigits:0}})}}</td>
        <td style="color:var(--text2)">${{p.trades}}</td>
        <td style="font-size:12px;color:var(--text3)">${{escapeHtml(p.joined_at)}}</td>
      </tr>`;
    }}).join('') || '<tr><td colspan="8" style="text-align:center;color:var(--text3);padding:24px">No players yet.</td></tr>';
  }}
}}
setInterval(admRefresh, 3000);
</script>""")

def render_admin_login(flash=""):
    fh = f'<div class="flash flash-err">{flash}</div>' if flash else ""
    return page("Admin Login", f"""
<style>
body{{display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px}}
.wrap{{width:100%;max-width:380px}}
.logo{{font-size:24px;font-weight:700;text-align:center;margin-bottom:6px}}.logo em{{font-style:normal;color:var(--gold)}}
.sub{{text-align:center;color:var(--text2);font-size:14px;margin-bottom:28px}}
.field{{margin-bottom:16px}}.field label{{display:block;font-size:13px;color:var(--text2);margin-bottom:6px;font-weight:500}}
.field input{{width:100%;background:var(--bg3);border:1px solid var(--border2);border-radius:var(--radius);padding:10px 14px;color:var(--text);font-size:15px;outline:none}}
.field input:focus{{border-color:var(--gold)}}
</style>
<div class="wrap">
  <div class="logo"><em>⚡ Admin</em> Login</div>
  <div class="sub">STOCK<span style="font-size:10px">EX</span> — Control Panel</div>
  {fh}
  <div class="card">
    <form method="POST" action="/admin/login">
      <div class="field"><label>Admin password</label><input type="password" name="password" placeholder="Enter password" required autofocus/></div>
      <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:12px">Enter →</button>
    </form>
  </div>
</div>""")

# ── HTTP Handler ──────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):

    def send_html(self, html, code=200):
        b = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(b))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
        self.send_header("ngrok-skip-browser-warning", "true")
        self.end_headers()
        self.wfile.write(b)

    def send_json(self, data, code=200):
        b = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(b))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(b)

    def redirect(self, path):
        self.send_response(302)
        self.send_header("Location", path)
        self.end_headers()

    def get_cookie(self, name):
        for part in self.headers.get("Cookie","").split(";"):
            k, _, v = part.strip().partition("=")
            if k.strip() == name: return v.strip()
        return None

    def set_cookie(self, name, value):
        self.send_header("Set-Cookie", f"{name}={value}; Path=/; HttpOnly; SameSite=Strict")

    def read_body(self):
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            raise ValueError("Invalid Content-Length.")
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("Request body is too large.")
        return self.rfile.read(length).decode("utf-8")

    def parse_form(self):
        return dict(urllib.parse.parse_qsl(self.read_body()))

    def player_token(self):
        return self.get_cookie("player_token")

    def is_admin(self):
        token = self.get_cookie("admin_token")
        with state["lock"]:
            return bool(token and token in state["admin_sessions"])

    # ── GET ───────────────────────────────────────────────────────────────────

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/register"):
            self.send_html(render_register())

        elif path == "/directory":
            # Public page. If the participant is already logged in, the same
            # player_token cookie is retained and /trade will use that session.
            tok = self.player_token()
            player = get_player(tok) if tok else None
            self.send_html(render_directory(player))
        elif path == "/trade":
            tok = self.player_token()
            player = get_player(tok) if tok else None
            if not player: self.redirect("/")
            else: self.send_html(render_trade(player))

        elif path == "/health":
            self.send_json({
                "ok": True,
                "service": "stockex",
                "game_active": state["game_active"],
                "players": len(state["players"]),
            })

        elif path == "/api/state":
            tok = self.player_token()
            with state["lock"]:
                player = state["players"].get(tok) if tok else None
                if not player:
                    self.send_json({"ok": False}); return
                # Build a compact response snapshot while holding the lock; no disk I/O.
                prices = copy.deepcopy(state["prices"])
                history = copy.deepcopy(state["price_history"])
                news = copy.deepcopy(state["news_feed"])
                player_copy = copy.deepcopy(player)
                pv = portfolio_value(player_copy)
            self.send_json({
                "ok": True,
                "prices": prices,
                "price_history": history,
                "player": {
                    "balance": player_copy["balance"],
                    "portfolio_value": pv,
                    "portfolio": player_copy["portfolio"],
                    "avg_cost": player_copy.get("avg_cost", {}),
                },
                "news_feed": news,
            })

        elif path == "/api/admin_state":
            if not self.is_admin():
                self.send_json({"ok": False}); return
            with state["lock"]:
                hist = copy.deepcopy(state["price_history"])
                prices = copy.deepcopy(state["prices"])
                players = copy.deepcopy(list(state["players"].values()))
                last_tick = next((values[-1][0] for values in hist.values() if values), None)
                sorted_players = sorted(
                    players,
                    key=lambda p: p["balance"] + sum(
                        prices.get(t, {}).get("current", 0) * q
                        for t, q in p.get("portfolio", {}).items()
                    ),
                    reverse=True,
                )
                lb = []
                for player in sorted_players:
                    pv = player["balance"] + sum(
                        prices.get(t, {}).get("current", 0) * q
                        for t, q in player.get("portfolio", {}).items()
                    )
                    lb.append({
                        "name": player["name"], "team": player["team"],
                        "balance": player["balance"], "pv": round(pv, 2),
                        "gain": round(pv - STARTING_CASH, 2),
                        "trades": player.get("trades", 0),
                        "joined_at": player.get("joined_at", ""),
                    })
            self.send_json({
                "ok": True, "prices": prices, "price_history": hist,
                "last_tick": last_tick, "leaderboard": lb,
            })

        elif path == "/admin":
            if self.is_admin(): self.send_html(render_admin())
            else: self.redirect("/admin/login")

        elif path == "/admin/login":
            self.send_html(render_admin_login())

        elif path == "/admin/logout":
            tok = self.get_cookie("admin_token")
            with state["lock"]:
                state["admin_sessions"].discard(tok)
            self.send_response(302)
            self.send_header("Location", "/admin/login")
            self.send_header("Set-Cookie", "admin_token=; Path=/; Max-Age=0")
            self.end_headers()

        else:
            self.send_html("<h1 style='font-family:sans-serif;padding:40px'>404</h1>", 404)

    def log_message(self, fmt, *args): pass

    # ── POST ──────────────────────────────────────────────────────────────────

    def do_POST(self):
        path = self.path.split("?", 1)[0]

        # Player registration
        if path == "/register":
            form = self.parse_form()
            name = form.get("name","").strip()
            team = form.get("team","").strip()
            if not name or not team:
                self.send_html(render_register("Please fill in both fields.", "err")); return
            if len(name) > 40 or len(team) > 40:
                self.send_html(render_register("Name and team must be 40 characters or fewer.", "err")); return
            if any(ord(ch) < 32 for ch in name + team):
                self.send_html(render_register("Please remove control characters from the fields.", "err")); return
            tok = generate_token()
            with state["lock"]:
                state["players"][tok] = {
                    "name": name, "team": team,
                    "balance": STARTING_CASH,
                    "portfolio": {},
                    "avg_cost": {},   # ticker → weighted-average price paid per share
                    "trades": 0,
                    "joined_at": datetime.now().strftime("%H:%M:%S"),
                }
            request_checkpoint()
            self.send_response(302)
            self.send_header("Location", "/trade")
            self.set_cookie("player_token", tok)
            self.end_headers()

        # Trade
        elif path == "/api/trade":
            tok = self.player_token()
            if not tok:
                self.send_json({"ok":False,"msg":"Not logged in."}); return
            try:
                body   = json.loads(self.read_body())
                ticker = body["ticker"]
                action = body["action"]
                qty    = int(body.get("qty",1))
            except Exception:
                self.send_json({"ok":False,"msg":"Invalid request."}); return
            if (not isinstance(ticker, str) or ticker not in state["prices"]
                    or not isinstance(action, str) or action not in ("buy", "sell")
                    or qty < 1 or qty > 1000000):
                self.send_json({"ok":False,"msg":"Invalid ticker, action or quantity."}, 400); return

            # The complete financial mutation is atomic. SQLite is deliberately
            # NOT touched here, keeping the critical section very short.
            with state["lock"]:
                player = state["players"].get(tok)
                if not player:
                    result = {"ok":False,"msg":"Not logged in."}
                elif not state["game_active"]:
                    result = {"ok":False,"msg":"Game is paused. Wait for admin to start."}
                else:
                    price = state["prices"][ticker]["current"]
                    if action == "buy":
                        cost = price * qty
                        if player["balance"] < cost:
                            result = {"ok":False,"msg":f"Need ₹{cost:,.2f} but only ₹{player['balance']:,.2f} available."}
                        else:
                            player["balance"] -= cost
                            old_qty = player["portfolio"].get(ticker,0)
                            old_avg = player["avg_cost"].get(ticker,0)
                            new_qty = old_qty + qty
                            player["avg_cost"][ticker] = round((old_avg*old_qty + price*qty) / new_qty, 2)
                            player["portfolio"][ticker] = new_qty
                            player["trades"] += 1
                            result = {"ok":True,"msg":f"✓ Bought {qty}× {ticker} @ ₹{price:,.2f}"}
                    elif action == "sell":
                        held = player["portfolio"].get(ticker,0)
                        if held < qty:
                            result = {"ok":False,"msg":f"You only hold {held} units of {ticker}."}
                        else:
                            player["balance"] += price * qty
                            remaining = held - qty
                            player["portfolio"][ticker] = remaining
                            if remaining == 0:
                                player["avg_cost"].pop(ticker, None)
                            player["trades"] += 1
                            result = {"ok":True,"msg":f"✓ Sold {qty}× {ticker} @ ₹{price:,.2f}"}
                    else:
                        result = {"ok":False,"msg":"Unknown action."}

            if result["ok"]:
                request_checkpoint()
            self.send_json(result)

        # Admin login
        elif path == "/admin/login":
            form = self.parse_form()
            if form.get("password") == ADMIN_PASSWORD:
                tok = generate_token()
                with state["lock"]:
                    state["admin_sessions"].add(tok)
                self.send_response(302)
                self.send_header("Location", "/admin")
                self.set_cookie("admin_token", tok)
                self.end_headers()
            else:
                self.send_html(render_admin_login("Wrong password."))

        # Toggle game
        elif path == "/admin/toggle":
            if not self.is_admin(): self.redirect("/admin/login"); return
            with state["lock"]:
                state["game_active"] = not state["game_active"]
            request_checkpoint()
            msg = "▶ Game started! Players can now trade." if state["game_active"] else "⏸ Game paused."
            self.send_html(render_admin(msg, "ok"))

        # Release news
        elif path == "/admin/release":
            if not self.is_admin(): self.redirect("/admin/login"); return
            form = self.parse_form()
            nid  = form.get("news_id")
            released_ids = {n["id"] for n in state["news_feed"]}
            item = next((n for n in state["news_pool"] if n["id"] == nid), None)
            if not item:
                self.send_html(render_admin("News item not found.","err")); return
            if nid in released_ids:
                self.send_html(render_admin("Already released.","err")); return
            with state["lock"]:
                entry = dict(item)
                entry["released_at"] = datetime.now().strftime("%H:%M:%S")
                state["news_feed"].append(entry)
                apply_news_impact(entry)
            request_checkpoint()
            self.send_html(render_admin(f"📢 Released: \"{item['title']}\" — prices updated!", "ok"))

        # Reset prices only
        elif path == "/admin/reset_prices":
            if not self.is_admin(): self.redirect("/admin/login"); return
            with state["lock"]:
                for ticker, p in state["prices"].items():
                    p["current"] = p["base"]
                    state["price_history"].setdefault(ticker, []).clear()
            request_checkpoint()
            self.send_html(render_admin("↺ Prices reset to base values.", "ok"))

        # ── Full game reset ───────────────────────────────────────────────────
        elif path == "/admin/full_reset":
            if not self.is_admin(): self.redirect("/admin/login"); return
            do_full_reset()
            self.send_html(render_admin("🔄 Full reset complete — all players cleared, prices back to base.", "ok"))

        else:
            self.send_html("<h1>404</h1>", 404)


# ── Entry point ───────────────────────────────────────────────────────────────

class StockExServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    request_queue_size = 256
    daemon_threads = True

def main():
    with StockExServer((HOST, PORT), Handler) as httpd:
        base = f"http://localhost:{PORT}"
        print(f"""
╔══════════════════════════════════════════════════╗
║  STOCKex - THE ULTIMATE TRADING CHALLENGE        ║
╠══════════════════════════════════════════════════╣
║  Player URL :  {base:<33} ║
║  Admin URL  :  {(base+'/admin'):<33} ║
║  Admin password: {("configured in environment" if ADMIN_PASSWORD_FROM_ENV else ADMIN_PASSWORD):<32} ║
╚══════════════════════════════════════════════════╝
  Prices fluctuate every {TICK_INTERVAL}s when game is live.
  Press Ctrl+C to stop.
""")
        threading.Timer(0.8, lambda: webbrowser.open(base)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Saving game state...")
            try:
                save_state()
                backup_database()
            except Exception as exc:
                print(f"  Final save failed: {exc}")
            print("  Server stopped.")

if __name__ == "__main__":
    main()
