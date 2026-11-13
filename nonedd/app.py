"""Криминальная империя — Telegram-бот на кнопках. Локальная БД (SQLite), без Mini App и без сервера."""
import os, sqlite3, random, time, html
import httpx

DB_FILE = "game.db"
db = sqlite3.connect(DB_FILE)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS players(id INTEGER PRIMARY KEY, name TEXT, balance INTEGER DEFAULT 5000,
  xp INTEGER DEFAULT 0, jobs_done INTEGER DEFAULT 0, jobs_failed INTEGER DEFAULT 0,
  last_job REAL DEFAULT 0, last_daily REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS assets(id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER, key TEXT,
  level INTEGER DEFAULT 1, last_collect REAL);
""")
def q(sql, *a):
    cur = db.execute(sql, a); db.commit(); return cur

# ---------- НАСТРОЙКИ ИГРЫ (можно менять) ----------
CATALOG = {  # income — ₽/час на 1 уровне; bonus — % к наградам за дела
    "kiosk":  dict(kind="business", name="Ларёк",            price=5_000,     income=300),
    "garage": dict(kind="business", name="Автомастерская",   price=25_000,    income=1_800),
    "club":   dict(kind="business", name="Ночной клуб",      price=120_000,   income=9_000),
    "casino": dict(kind="business", name="Казино",           price=600_000,   income=50_000),
    "flat":   dict(kind="estate",   name="Квартира",         price=200_000,   income=1_500),
    "villa":  dict(kind="estate",   name="Вилла",            price=2_000_000, income=18_000),
    "car1":   dict(kind="car",      name="Старая «девятка»", price=15_000,    bonus=3),
    "car2":   dict(kind="car",      name="BMW",              price=150_000,   bonus=8),
    "car3":   dict(kind="car",      name="Mercedes S-class", price=900_000,   bonus=15),
}
KINDS = {"business": "🏢 Бизнес", "estate": "🏙 Недвижимость", "car": "🚗 Автомобили"}
JOBS = [
    dict(name="Мелкая кража",       lvl=1, reward=(300, 700),       xp=10,  fail=0.15),
    dict(name="Крышевание ларьков", lvl=2, reward=(1_500, 3_500),   xp=25,  fail=0.25),
    dict(name="Угон авто",          lvl=4, reward=(8_000, 16_000),  xp=60,  fail=0.35),
    dict(name="Ограбление склада",  lvl=7, reward=(40_000, 80_000), xp=150, fail=0.45),
]
JOB_COOLDOWN = 20        # секунд между делами
INCOME_CAP_H = 8         # доход копится не дольше 8 часов
DAILY_BASE = 1000        # ежедневная награда = DAILY_BASE * уровень

# ---------- ВСПОМОГАТЕЛЬНОЕ ----------
def money(n): return f"{int(n):,}".replace(",", " ") + " ₽"
def level_of(xp): return int((xp / 40) ** 0.5) + 1
def next_xp(lvl): return 40 * lvl * lvl
def esc(s): return html.escape(str(s))
def upgrade_cost(a): return int(CATALOG[a["key"]]["price"] * a["level"] * 0.8)
def pending(a):
    c = CATALOG[a["key"]]
    if "income" not in c: return 0
    hours = min((time.time() - a["last_collect"]) / 3600, INCOME_CAP_H)
    return int(c["income"] * a["level"] * hours)
def load(pid): return q("SELECT * FROM players WHERE id=?", pid).fetchone()
def assets(pid): return q("SELECT * FROM assets WHERE player_id=? ORDER BY id", pid).fetchall()
def get_player(user):
    name = (user.get("first_name") or user.get("username") or "Игрок")[:40]
    if not load(user["id"]):
        q("INSERT INTO players(id,name) VALUES(?,?)", user["id"], name)
    else:
        q("UPDATE players SET name=? WHERE id=?", name, user["id"])
    return load(user["id"])

# ---------- ДЕЙСТВИЯ (возвращают текст-результат) ----------
def do_job(p, i):
    j = JOBS[i]
    if level_of(p["xp"]) < j["lvl"]: return f"🔒 Нужен уровень {j['lvl']}"
    wait = JOB_COOLDOWN - (time.time() - p["last_job"])
    if wait > 0: return f"⏳ Подожди ещё {int(wait) + 1} сек."
    q("UPDATE players SET last_job=? WHERE id=?", time.time(), p["id"])
    if random.random() < j["fail"]:
        fine = min(p["balance"], j["reward"][0] // 2)
        q("UPDATE players SET balance=balance-?, jobs_failed=jobs_failed+1 WHERE id=?", fine, p["id"])
        return f"🚔 Провал! Штраф {money(fine)}"
    bonus = sum(CATALOG[a["key"]].get("bonus", 0) for a in assets(p["id"]))
    r = int(random.randint(*j["reward"]) * (1 + bonus / 100))
    q("UPDATE players SET balance=balance+?, xp=xp+?, jobs_done=jobs_done+1 WHERE id=?", r, j["xp"], p["id"])
    return f"✅ Успех! +{money(r)}, +{j['xp']} XP" + (f" (бонус машин +{bonus}%)" if bonus else "")

def do_buy(p, key):
    c = CATALOG.get(key)
    if not c: return "Нет такого товара"
    if any(a["key"] == key for a in assets(p["id"])): return "Уже куплено"
    if p["balance"] < c["price"]: return f"❌ Не хватает денег ({money(c['price'])})"
    q("UPDATE players SET balance=balance-? WHERE id=?", c["price"], p["id"])
    q("INSERT INTO assets(player_id,key,last_collect) VALUES(?,?,?)", p["id"], key, time.time())
    return f"✅ Куплено: {c['name']}"

def do_upgrade(p, aid):
    a = q("SELECT * FROM assets WHERE id=? AND player_id=?", aid, p["id"]).fetchone()
    if not a or "income" not in CATALOG[a["key"]]: return "Нельзя улучшить"
    cost = upgrade_cost(a)
    if p["balance"] < cost: return f"❌ Не хватает денег ({money(cost)})"
    q("UPDATE players SET balance=balance-?+? WHERE id=?", cost, pending(a), p["id"])  # накопленное не теряем
    q("UPDATE assets SET level=level+1, last_collect=? WHERE id=?", time.time(), aid)
    return f"⬆ {CATALOG[a['key']]['name']} → уровень {a['level'] + 1}"

def do_collect(p):
    total = sum(pending(a) for a in assets(p["id"]))
    q("UPDATE assets SET last_collect=? WHERE player_id=?", time.time(), p["id"])
    q("UPDATE players SET balance=balance+? WHERE id=?", total, p["id"])
    return f"💰 Собрано {money(total)}" if total else "Пока нечего собирать"

def do_daily(p):
    left = 86400 - (time.time() - p["last_daily"])
    if left > 0: return f"🎁 Уже получено. Следующая через {int(left // 3600)} ч {int(left % 3600 // 60)} мин"
    r = DAILY_BASE * level_of(p["xp"])
    q("UPDATE players SET balance=balance+?, last_daily=? WHERE id=?", r, time.time(), p["id"])
    return f"🎁 Ежедневная награда: +{money(r)}"

# ---------- ЭКРАНЫ (текст + кнопки) ----------
def back(): return [("⬅ В меню", "home")]

def scr_home(p, _=""):
    lvl = level_of(p["xp"]); pend = sum(pending(a) for a in assets(p["id"]))
    text = (f"🔥 <b>Криминальная империя</b>\n\n👤 {esc(p['name'])} · уровень {lvl}\n"
            f"💵 Баланс: <b>{money(p['balance'])}</b>\n⭐ Опыт: {p['xp']}/{next_xp(lvl)}\n"
            f"📊 Дел: {p['jobs_done']} успешных, {p['jobs_failed']} провалено")
    return text, [[("🔫 Дела", "jobs"), ("🏢 Моё имущество", "biz")],
                  [("🛒 Магазин", "shop"), ("👑 Рейтинг", "top")],
                  [(f"💰 Собрать доход ({money(pend)})", "collect")],
                  [("🎁 Ежедневная награда", "daily")]]

def scr_jobs(p, _=""):
    lvl = level_of(p["xp"])
    rows = [[(f"{'🔒' if lvl < j['lvl'] else '🔫'} {j['name']} · {money(j['reward'][0])}–{money(j['reward'][1])} · риск {int(j['fail']*100)}%", f"job:{i}")]
            for i, j in enumerate(JOBS)]
    return (f"🔫 <b>Криминальные дела</b>\nУровень {lvl} · баланс {money(p['balance'])}\n"
            f"Чем выше уровень — тем серьёзнее дела. Пауза между делами {JOB_COOLDOWN} сек."), rows + [back()]

def scr_biz(p, _=""):
    items = assets(p["id"])
    if not items: return "🏢 У тебя пока ничего нет. Загляни в магазин!", [[("🛒 Магазин", "shop")], back()]
    lines, rows = [], []
    for a in items:
        c = CATALOG[a["key"]]
        if "income" in c:
            lines.append(f"• {c['name']} (ур. {a['level']}) — {money(c['income'] * a['level'])}/час, накоплено {money(pending(a))}")
            rows.append([(f"⬆ {c['name']} → ур.{a['level'] + 1} · {money(upgrade_cost(a))}", f"up:{a['id']}")])
        else:
            lines.append(f"• {c['name']} — +{c['bonus']}% к наградам за дела")
    return "🏢 <b>Моё имущество</b>\n\n" + "\n".join(lines), rows + [[("💰 Собрать доход", "collect")], back()]

def scr_shop(p, kind=""):
    if kind not in KINDS:
        return "🛒 <b>Магазин</b>\nВыбери раздел:", [[(t, f"shop:{k}")] for k, t in KINDS.items()] + [back()]
    owned = {a["key"] for a in assets(p["id"])}
    rows = [[(f"{'✅' if k in owned else '🛒'} {c['name']} · {money(c['price'])} · " +
              (f"{money(c['income'])}/ч" if "income" in c else f"+{c['bonus']}%"), f"buy:{k}")]
            for k, c in CATALOG.items() if c["kind"] == kind]
    return f"{KINDS[kind]}\nБаланс: {money(p['balance'])}", rows + [[("⬅ Разделы", "shop")], back()]

def scr_top(p, _=""):
    worth = {r["id"]: [r["name"], r["balance"]] for r in q("SELECT id,name,balance FROM players").fetchall()}
    for a in q("SELECT player_id,key,level FROM assets").fetchall():
        worth[a["player_id"]][1] += CATALOG[a["key"]]["price"] * a["level"]
    top = sorted(worth.items(), key=lambda x: -x[1][1])[:10]
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"{medals[i] if i < 3 else str(i + 1) + '.'} {esc(n)}{' (ты)' if pid == p['id'] else ''} — {money(w)}"
             for i, (pid, (n, w)) in enumerate(top)]
    return "👑 <b>Богатейшие игроки</b>\n\n" + "\n".join(lines), [back()]

SCREENS = dict(home=scr_home, jobs=scr_jobs, biz=scr_biz, shop=scr_shop, top=scr_top)

def handle(p, data):
    """Обрабатывает нажатие кнопки → (текст, кнопки)."""
    cmd, _, arg = data.partition(":")
    note = ""
    if cmd == "job":       note = do_job(p, int(arg));    cmd, arg = "jobs", ""
    elif cmd == "buy":     note = do_buy(p, arg);         cmd, arg = "shop", CATALOG.get(arg, {}).get("kind", "")
    elif cmd == "up":      note = do_upgrade(p, int(arg)); cmd, arg = "biz", ""
    elif cmd == "collect": note = do_collect(p);          cmd = "home"
    elif cmd == "daily":   note = do_daily(p);            cmd = "home"
    text, rows = SCREENS.get(cmd, scr_home)(load(p["id"]), arg)
    return (f"{esc(note)}\n\n" if note else "") + text, rows

# ---------- TELEGRAM (long polling, сервер и домен не нужны) ----------
def main():
    token = os.getenv("BOT_TOKEN")
    if not token and os.path.exists("token.txt"): token = open("token.txt").read().strip()
    if not token:
        token = input("Вставь токен бота от @BotFather: ").strip()
        open("token.txt", "w").write(token)
    http = httpx.Client(timeout=45)
    def api(method, **kw):
        return http.post(f"https://api.telegram.org/bot{token}/{method}", json=kw).json()
    def markup(rows): return dict(inline_keyboard=[[dict(text=t, callback_data=d) for t, d in r] for r in rows])

    me = api("getMe")
    if not me.get("ok"): raise SystemExit(f"Неверный токен: {me}")
    api("deleteWebhook")                                   # на случай прошлых запусков с вебхуком
    api("setChatMenuButton", menu_button=dict(type="default"))
    print(f"Бот @{me['result']['username']} запущен. Остановить: Ctrl+C")

    offset = 0
    while True:
        try:
            for u in api("getUpdates", offset=offset, timeout=30).get("result", []):
                offset = u["update_id"] + 1
                if "message" in u and (u["message"].get("text") or "").startswith("/"):
                    m = u["message"]; p = get_player(m["from"])
                    text, rows = scr_home(p)
                    api("sendMessage", chat_id=m["chat"]["id"], text=text, parse_mode="HTML", reply_markup=markup(rows))
                elif "callback_query" in u:
                    c = u["callback_query"]; p = get_player(c["from"])
                    text, rows = handle(p, c["data"])
                    api("answerCallbackQuery", callback_query_id=c["id"])
                    api("editMessageText", chat_id=c["message"]["chat"]["id"], message_id=c["message"]["message_id"],
                        text=text, parse_mode="HTML", reply_markup=markup(rows))
        except (httpx.HTTPError, KeyError) as e:
            print("Ошибка сети, повтор через 3 сек:", e); time.sleep(3)

if __name__ == "__main__":
    main()