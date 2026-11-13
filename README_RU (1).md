import os, json, time, hmac, hashlib, urllib.parse, sqlite3, random, threading, asyncio
from contextlib import contextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DB_FILE", "game.db")
BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"

CATALOG = {
    "kiosk":  dict(kind="business", name="Ларёк", price=5000, income=300, image="🏪"),
    "garage": dict(kind="business", name="Автомастерская", price=25000, income=1800, image="🔧"),
    "club":   dict(kind="business", name="Ночной клуб", price=120000, income=9000, image="🌃"),
    "casino": dict(kind="business", name="Казино", price=600000, income=50000, image="🎰"),
    "flat":   dict(kind="estate", name="Квартира", price=200000, income=1500, image="🏙️"),
    "villa":  dict(kind="estate", name="Вилла", price=2000000, income=18000, image="🏰"),
    "car1":   dict(kind="car", name="Старая «девятка»", price=15000, bonus=3, image="🚗"),
    "car2":   dict(kind="car", name="BMW", price=150000, bonus=8, image="🏎️"),
    "car3":   dict(kind="car", name="Mercedes S-class", price=900000, bonus=15, image="🚘"),
}
JOBS = [
    dict(name="Мелкая кража", lvl=1, reward=(300,700), xp=10, fail=.15, icon="🧤"),
    dict(name="Крышевание ларьков", lvl=2, reward=(1500,3500), xp=25, fail=.25, icon="🏪"),
    dict(name="Угон авто", lvl=4, reward=(8000,16000), xp=60, fail=.35, icon="🚘"),
    dict(name="Ограбление склада", lvl=7, reward=(40000,80000), xp=150, fail=.45, icon="📦"),
]
JOB_COOLDOWN = 20
INCOME_CAP_H = 8
DAILY_BASE = 1000

from contextlib import contextmanager

@contextmanager
def db_session():
    c = sqlite3.connect(DB_FILE, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def init_db():
    with db_session() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS players(
          id INTEGER PRIMARY KEY, name TEXT, balance INTEGER DEFAULT 5000,
          xp INTEGER DEFAULT 0, jobs_done INTEGER DEFAULT 0, jobs_failed INTEGER DEFAULT 0,
          last_job REAL DEFAULT 0, last_daily REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS assets(
          id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL,
          key TEXT NOT NULL, level INTEGER DEFAULT 1, last_collect REAL,
          FOREIGN KEY(player_id) REFERENCES players(id), UNIQUE(player_id,key)
        );
        """)

def level_of(xp): return int((max(0, xp) / 40) ** .5) + 1
def next_xp(lvl): return 40 * lvl * lvl
def money(n): return f"{int(n):,}".replace(",", " ") + " ₽"

def pending(a, now=None):
    item = CATALOG[a["key"]]
    if "income" not in item: return 0
    now = now or time.time()
    elapsed = min(max(0, now - (a["last_collect"] or now)) / 3600, INCOME_CAP_H)
    return int(item["income"] * a["level"] * elapsed)

def telegram_user(init_data: str):
    if not BOT_TOKEN:
        raise HTTPException(503, "На сервере не задан BOT_TOKEN")
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash")
        auth_date = int(parsed.get("auth_date", "0"))
        if abs(time.time() - auth_date) > 86400:
            raise ValueError("expired")
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            raise ValueError("bad hash")
        user = json.loads(parsed["user"])
        return {"id": int(user["id"]), "name": (user.get("first_name") or user.get("username") or "Игрок")[:40],
                "username": user.get("username", "")}
    except Exception:
        raise HTTPException(401, "Не удалось проверить Telegram initData. Открой приложение из Telegram.")

def player_for(user):
    with db_session() as c:
        c.execute("INSERT OR IGNORE INTO players(id,name) VALUES(?,?)", (user["id"], user["name"]))
        c.execute("UPDATE players SET name=? WHERE id=?", (user["name"], user["id"]))
        return c.execute("SELECT * FROM players WHERE id=?", (user["id"],)).fetchone()

def snapshot(pid):
    now = time.time()
    with db_session() as c:
        p = c.execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone()
        assets = c.execute("SELECT * FROM assets WHERE player_id=? ORDER BY id", (pid,)).fetchall()
        all_assets = []
        total_pending = 0
        for a in assets:
            item = CATALOG[a["key"]]
            pend = pending(a, now)
            total_pending += pend
            all_assets.append({
                "id": a["id"], "key": a["key"], "name": item["name"], "kind": item["kind"],
                "level": a["level"], "price": item["price"], "income": item.get("income", 0),
                "bonus": item.get("bonus", 0), "pending": pend, "icon": item["image"],
                "upgrade_cost": int(item["price"] * a["level"] * .8) if "income" in item else 0
            })
        lvl = level_of(p["xp"])
        income_hour = sum(x["income"] * x["level"] for x in all_assets)
        return {
            "player": {"id": p["id"], "name": p["name"], "balance": p["balance"], "xp": p["xp"],
                       "level": lvl, "next_xp": next_xp(lvl), "jobs_done": p["jobs_done"],
                       "jobs_failed": p["jobs_failed"], "daily_ready": now-p["last_daily"] >= 86400,
                       "job_wait": max(0, int(JOB_COOLDOWN-(now-p["last_job"])))},
            "assets": all_assets, "pending": total_pending, "income_hour": income_hour,
            "catalog": [{"key": k, **v} for k,v in CATALOG.items()],
            "jobs": [{"index":i, **j} for i,j in enumerate(JOBS)]
        }

def perform_action(pid, action, key=None, asset_id=None, job_index=None):
    now = time.time()
    with db_session() as c:
        c.execute("BEGIN IMMEDIATE")
        p = c.execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone()
        if not p: raise HTTPException(404, "Игрок не найден")
        result = "Готово"
        if action == "collect":
            rows = c.execute("SELECT * FROM assets WHERE player_id=?", (pid,)).fetchall()
            total = sum(pending(a, now) for a in rows)
            c.execute("UPDATE assets SET last_collect=? WHERE player_id=?", (now,pid))
            c.execute("UPDATE players SET balance=balance+? WHERE id=?", (total,pid))
            result = f"Собрано {money(total)}"
        elif action == "daily":
            if now-p["last_daily"] < 86400: raise HTTPException(400, "Ежедневная награда уже получена")
            reward = DAILY_BASE * level_of(p["xp"])
            c.execute("UPDATE players SET balance=balance+?, last_daily=? WHERE id=?", (reward,now,pid))
            result = f"Ежедневная награда: +{money(reward)}"
        elif action == "job":
            if job_index is None or not 0 <= job_index < len(JOBS): raise HTTPException(400, "Неизвестное задание")
            j = JOBS[job_index]
            if level_of(p["xp"]) < j["lvl"]: raise HTTPException(400, f"Нужен уровень {j['lvl']}")
            if now-p["last_job"] < JOB_COOLDOWN: raise HTTPException(400, f"Подожди ещё {int(JOB_COOLDOWN-(now-p['last_job']))+1} сек.")
            c.execute("UPDATE players SET last_job=? WHERE id=?", (now,pid))
            if random.random() < j["fail"]:
                fine = min(p["balance"], j["reward"][0]//2)
                c.execute("UPDATE players SET balance=balance-?, jobs_failed=jobs_failed+1 WHERE id=?", (fine,pid))
                result = f"Провал! Штраф {money(fine)}"
            else:
                cars = c.execute("SELECT key FROM assets WHERE player_id=?", (pid,)).fetchall()
                bonus = sum(CATALOG[a["key"]].get("bonus",0) for a in cars)
                reward = int(random.randint(*j["reward"])*(1+bonus/100))
                c.execute("UPDATE players SET balance=balance+?, xp=xp+?, jobs_done=jobs_done+1 WHERE id=?", (reward,j["xp"],pid))
                result = f"Успех! +{money(reward)}, +{j['xp']} XP"
        elif action == "buy":
            item = CATALOG.get(key)
            if not item: raise HTTPException(400, "Такого товара нет")
            if c.execute("SELECT 1 FROM assets WHERE player_id=? AND key=?", (pid,key)).fetchone():
                raise HTTPException(400, "Уже куплено")
            if p["balance"] < item["price"]: raise HTTPException(400, f"Не хватает денег: {money(item['price'])}")
            c.execute("UPDATE players SET balance=balance-? WHERE id=?", (item["price"],pid))
            c.execute("INSERT INTO assets(player_id,key,last_collect) VALUES(?,?,?)", (pid,key,now))
            result = f"Куплено: {item['name']}"
        elif action == "upgrade":
            a = c.execute("SELECT * FROM assets WHERE id=? AND player_id=?", (asset_id,pid)).fetchone()
            if not a or "income" not in CATALOG[a["key"]]: raise HTTPException(400, "Нельзя улучшить")
            cost = int(CATALOG[a["key"]]["price"]*a["level"]*.8)
            if p["balance"] < cost: raise HTTPException(400, f"Не хватает денег: {money(cost)}")
            accrued = pending(a,now)
            c.execute("UPDATE players SET balance=balance-?+? WHERE id=?", (cost,accrued,pid))
            c.execute("UPDATE assets SET level=level+1,last_collect=? WHERE id=?", (now,asset_id))
            result = f"{CATALOG[a['key']]['name']} улучшен до уровня {a['level']+1}"
        else:
            raise HTTPException(400, "Неизвестное действие")
        c.commit()
    return {"message": result, "state": snapshot(pid)}

app = FastAPI(title="Криминальная империя Mini App")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

class Action(BaseModel):
    action: str
    key: str | None = None
    asset_id: int | None = None
    job_index: int | None = None

@app.on_event("startup")
def startup():
    init_db()
    if BOT_TOKEN and WEBAPP_URL:
        try:
            configure_telegram()
        except Exception as e:
            print("Не удалось настроить Telegram webhook:", e)

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")

@app.get("/api/me")
def me(authorization: str = Header(default="")):
    init_data = authorization.removeprefix("tma ").strip()
    user = telegram_user(init_data)
    player_for(user)
    return snapshot(user["id"])

@app.get("/api/top")
def leaderboard(authorization: str = Header(default="")):
    user = telegram_user(authorization.removeprefix("tma ").strip())
    player_for(user)
    with db_session() as c:
        rows = c.execute("SELECT id,name,balance FROM players ORDER BY balance DESC LIMIT 20").fetchall()
        return [{"id": r["id"], "name": r["name"], "balance": r["balance"],
                 "is_me": r["id"] == user["id"]} for r in rows]

@app.post("/api/action")
def action(body: Action, authorization: str = Header(default="")):
    init_data = authorization.removeprefix("tma ").strip()
    user = telegram_user(init_data)
    player_for(user)
    return perform_action(user["id"], body.action, body.key, body.asset_id, body.job_index)


def telegram_api(method, payload):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not configured")
    with httpx.Client(timeout=20) as client:
        response = client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(str(result))
        return result.get("result")

def configure_telegram():
    if not WEBHOOK_SECRET:
        raise RuntimeError("WEBHOOK_SECRET is required for webhook mode")
    telegram_api("setWebhook", {
        "url": WEBAPP_URL.rstrip("/") + "/telegram/webhook",
        "secret_token": WEBHOOK_SECRET,
        "allowed_updates": ["message"],
        "drop_pending_updates": False
    })
    telegram_api("setChatMenuButton", {
        "menu_button": {
            "type": "web_app",
            "text": "Открыть игру",
            "web_app": {"url": WEBAPP_URL}
        }
    })

@app.post("/telegram/webhook")
async def telegram_webhook(update: dict, x_telegram_bot_api_secret_token: str = Header(default="")):
    if not WEBHOOK_SECRET or not hmac.compare_digest(x_telegram_bot_api_secret_token, WEBHOOK_SECRET):
        raise HTTPException(403, "Invalid Telegram webhook secret")
    message = update.get("message") or {}
    text = message.get("text", "")
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    if chat_id and (text.startswith("/start") or text.startswith("/app")):
        keyboard = {
            "inline_keyboard": [[{
                "text": "🏙 Открыть Криминальную империю",
                "web_app": {"url": WEBAPP_URL}
            }]]
        }
        try:
            telegram_api("sendMessage", {
                "chat_id": chat_id,
                "text": "Добро пожаловать в «Криминальную империю»!\\nНажми кнопку, чтобы открыть игру.",
                "reply_markup": keyboard
            })
        except Exception as e:
            print("Не удалось отправить сообщение Telegram:", e)
    return {"ok": True}
