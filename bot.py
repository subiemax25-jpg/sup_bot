"""
🏄 САП-бот: анонсы + отзывы + новости + погода + расписание + рейтинг
=====================================================================
Погода:
  - Open-Meteo (hourly)    — ветер, температура, осадки; 3 локации
  - Open-Meteo Marine      — волны по часам; 3 локации
  - WorldWeatherOnline     — свелл, температура воды для о. Русский

Установка:  pip install "python-telegram-bot[job-queue]" aiohttp
Запуск:     python3 bot.py
"""

import logging
import asyncio
import aiohttp
import math
import random
import os
from datetime import date, datetime, time as dtime, timedelta, timezone
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto, InputMediaVideo,
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler,
    filters, ContextTypes, PicklePersistence
)

# ─────────────────────────────────────────────
#  НАСТРОЙКИ — все значения берутся из Railway Variables
# ─────────────────────────────────────────────
BOT_TOKEN  = os.environ.get("BOT_TOKEN",  "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
ADMIN_ID   = int(os.environ.get("ADMIN_ID", "0"))
WWO_KEY    = os.environ.get("WWO_KEY",    "")
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  ГЛАВНОЕ МЕНЮ (постоянная клавиатура)
# ──────────────────────────────────────────────
def _main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📝 Анонс",       "📸 Отзыв"],
            ["🌤 Погода",      "📰 Новость"],
            ["📅 Расписание",  "🏆 Рейтинг"],
            ["🎰 Колесо фортуны"],
        ],
        resize_keyboard=True,
    )

# ──────────────────────────────────────────────
#  СОСТОЯНИЯ ДИАЛОГОВ
# ──────────────────────────────────────────────
DATE, LOCATION, TIME, ROUTE, DURATION, LEVEL, CONTACT, PHOTO, CONFIRM = range(9)
# REVIEW: добавлен шаг REVIEW_PARTICIPANTS между REVIEW_AUTHOR и REVIEW_MEDIA
REVIEW_COMMENT, REVIEW_AUTHOR, REVIEW_PARTICIPANTS, REVIEW_MEDIA, REVIEW_CONFIRM = range(9, 14)
NEWS_TEXT, NEWS_PHOTO, NEWS_CONFIRM = range(14, 17)

# ──────────────────────────────────────────────
#  РЕЙТИНГ
# ──────────────────────────────────────────────
RANKS = [
    (21, "🔱 Посейдон"),
    (11, "🦈 Кракен"),
    (6,  "🐙 Ларга"),
    (3,  "🦀 Баклан"),
    (1,  "🪸 Планктон"),
]

def _get_rank(points: int) -> str:
    for min_pts, title in RANKS:
        if points >= min_pts:
            return title
    return "🪸 Планктон"

def _pts_word(n: int) -> str:
    if 11 <= n % 100 <= 14: return "очков"
    r = n % 10
    if r == 1:      return "очко"
    if 2 <= r <= 4: return "очка"
    return "очков"

def _escape_md(text: str) -> str:
    if not text: return ""
    for ch in ["_", "*", "`", "["]:
        text = text.replace(ch, f"\\{ch}")
    return text

def _ratings(bot_data: dict) -> dict:
    return bot_data.setdefault("ratings", {})


# ──────────────────────────────────────────────
#  ПОГОДА — константы и вспомогательные функции
# ──────────────────────────────────────────────

# Три локации: Русский + оба залива
WEATHER_LOCATIONS = [
    {"name": "Остров Русский",    "lat": 42.948, "lon": 131.941, "emoji": "🏝"},
    {"name": "Амурский залив",    "lat": 43.20,  "lon": 131.72,  "emoji": "🌊"},
    {"name": "Уссурийский залив", "lat": 43.05,  "lon": 132.45,  "emoji": "🌊"},
]

# Для WWO (только Русский)
SUP_LAT = WEATHER_LOCATIONS[0]["lat"]
SUP_LON = WEATHER_LOCATIONS[0]["lon"]
VLAD_TZ = timezone(timedelta(hours=10))

MONTHS_RU = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
]

def _deg_to_compass(deg: float) -> str:
    dirs = ["С", "ССВ", "СВ", "ВСВ", "В", "ВЮВ", "ЮВ", "ЮЮВ",
            "Ю", "ЮЮЗ", "ЮЗ", "ЗЮЗ", "З", "ЗСЗ", "СЗ", "ССЗ"]
    return dirs[round(deg / 22.5) % 16]

def _wmo_icon(code: int) -> str:
    if code == 0:  return "☀️"
    if code <= 3:  return "⛅"
    if code <= 48: return "🌫"
    if code <= 67: return "🌧"
    if code <= 77: return "❄️"
    if code <= 82: return "🌦"
    if code <= 86: return "🌨"
    return "⛈"

def _wind_dot(s): return "🟢" if s < 4 else "🟡" if s < 7 else "🟠" if s < 11 else "🔴"
def _wave_dot(h): return "🟢" if h < 0.3 else "🟡" if h < 0.6 else "🟠" if h < 1.0 else "🔴"

def _verdict(wind, wave):
    if wind >= 12 or wave >= 1.0: return "🔴 Выход не рекомендуется"
    if wind >= 8  or wave >= 0.6: return "🟠 Сложные условия — только опытным"
    if wind >= 5  or wave >= 0.3: return "🟡 Приемлемо — выбирай укрытое место"
    return "🟢 Отлично — можно идти везде"

def _location_advice(wind_dir_deg, wind, wave):
    if wind < 4 and wave < 0.3:
        return "Штиль 🌊 Любая точка острова — иди куда хочешь!"
    if wind >= 12:
        return "Слишком сильный ветер. Только закрытые бухты: Новик или Аякс."
    d = wind_dir_deg
    if   d < 22.5 or d >= 337.5: spot = "бухта Новик (южная сторона)"
    elif d < 67.5:                spot = "западная сторона — Амурский залив"
    elif d < 112.5:               spot = "западная сторона — Амурский залив"
    elif d < 157.5:               spot = "бухта Аякс (северная сторона)"
    elif d < 202.5:               spot = "северный берег, ближе к Владивостоку"
    elif d < 247.5:               spot = "восточная сторона — Уссурийский залив"
    elif d < 292.5:               spot = "восточная сторона — Уссурийский залив"
    else:                         spot = "юго-восточная сторона острова"
    return f"Лучшее место: {spot} — там будет укрытие от ветра."

def _date_label(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except Exception:
        return iso
    today = date.today()
    if d == today:
        prefix = "Сегодня"
    elif d == today + timedelta(days=1):
        prefix = "Завтра"
    else:
        prefix = ""
    return f"{prefix}, {d.day} {MONTHS_RU[d.month]}" if prefix else f"{d.day} {MONTHS_RU[d.month]}"

def _circular_mean(angles: list) -> int:
    """Корректное среднее для направлений ветра (учитывает переход 359°→0°)."""
    if not angles:
        return 0
    sin_s = sum(math.sin(math.radians(a)) for a in angles)
    cos_s = sum(math.cos(math.radians(a)) for a in angles)
    return round(math.degrees(math.atan2(sin_s, cos_s)) % 360)

def _sup_recommendations(d: dict) -> str:
    wind    = d.get("wind_speed", 0)
    wave    = d.get("wave_height", 0)
    gusts   = d.get("wind_gusts", 0)
    swell_h = d.get("swell_height") or 0
    swell_p = d.get("swell_period") or 0

    if wind < 4 and wave < 0.3:
        who = "👶 Подходит для всех, включая новичков."
    elif wind < 7 and wave < 0.5:
        who = "🏄 Подходит для уверенных пользователей. Новичкам — только с опытным напарником."
    elif wind < 11 and wave < 0.8:
        who = "💪 Только для опытных. Новичкам выходить не рекомендуется."
    else:
        who = "🚫 Не рекомендуется никому."

    warnings = []
    if gusts > 0 and gusts - wind >= 4:
        warnings.append(f"⚡ Порывы {gusts} м/с — значительно сильнее среднего ветра.")
    if swell_h >= 0.5 and swell_p >= 7:
        warnings.append(f"〰️ Свелл {swell_h} м, период {int(swell_p)} с — на открытой воде качает.")
    if d.get("prec_prob", 0) >= 50:
        warnings.append("🌧 Высокая вероятность дождя — возьми гермочехол.")
    if d.get("water_temp") and d["water_temp"] < 15:
        warnings.append(f"🥶 Вода {d['water_temp']}°C — надевай гидрокостюм.")

    warnings_str = "\n".join(warnings) + "\n" if warnings else ""
    return (
        f"*{_verdict(wind, wave)}*\n"
        f"📍 {_location_advice(d.get('wind_dir', 0), wind, wave)}\n"
        f"{who}\n{warnings_str}"
    )


# ──────────────────────────────────────────────
#  ПОГОДА — получение данных
# ──────────────────────────────────────────────

def _process_daylight_hourly(wh: dict, mh: dict) -> list:
    """
    Принимает почасовые данные Open-Meteo (timezone=Asia/Vladivostok).
    Фильтрует часы 07:00–20:59 (световой день).
    Возвращает список из 2 дней со средними значениями.
    """
    days: dict = {}
    times = wh.get("time", [])

    for i, t in enumerate(times):
        try:
            hour = int(t[11:13])   # "2026-05-18T09:00" → 9
        except Exception:
            continue
        if not (7 <= hour <= 20):
            continue
        date_str = t[:10]
        d = days.setdefault(date_str, {
            "wind": [], "gusts": [], "wind_dir": [],
            "temp": [], "precip": [], "wmo": [], "prec_prob": [],
            "wave": [], "wave_period": [],
        })

        def _v(key):
            arr = wh.get(key, [])
            return arr[i] if arr and i < len(arr) and arr[i] is not None else None

        v = _v("windspeed_10m");              
        if v is not None: d["wind"].append(float(v))
        v = _v("windgusts_10m");              
        if v is not None: d["gusts"].append(float(v))
        v = _v("winddirection_10m");          
        if v is not None: d["wind_dir"].append(float(v))
        v = _v("temperature_2m");             
        if v is not None: d["temp"].append(float(v))
        v = _v("precipitation");              
        if v is not None: d["precip"].append(float(v))
        v = _v("weathercode");                
        if v is not None: d["wmo"].append(int(v))
        v = _v("precipitation_probability"); 
        if v is not None: d["prec_prob"].append(float(v))

    # Marine (могут быть те же временны́е метки)
    m_times = mh.get("time", []) if mh else []
    for i, t in enumerate(m_times):
        try:
            hour = int(t[11:13])
        except Exception:
            continue
        if not (7 <= hour <= 20):
            continue
        date_str = t[:10]
        if date_str not in days:
            continue
        d = days[date_str]

        def _mv(key):
            arr = mh.get(key, [])
            return arr[i] if arr and i < len(arr) and arr[i] is not None else None

        v = _mv("wave_height"); 
        if v is not None: d["wave"].append(float(v))
        v = _mv("wave_period"); 
        if v is not None: d["wave_period"].append(float(v))

    def avg(lst):    return round(sum(lst) / len(lst), 1) if lst else 0.0
    def avg_i(lst):  return round(sum(lst) / len(lst))    if lst else 0
    def mx_prob(lst):return round(max(lst))                if lst else 0

    result = []
    for date_str in sorted(days)[:2]:
        d = days[date_str]
        result.append({
            "date":        date_str,
            "icon":        _wmo_icon(max(set(d["wmo"]), key=d["wmo"].count) if d["wmo"] else 0),
            "t_min":       round(min(d["temp"])) if d["temp"] else "—",
            "t_max":       round(max(d["temp"])) if d["temp"] else "—",
            "wind_speed":  avg(d["wind"]),
            "wind_gusts":  avg(d["gusts"]),
            "wind_dir":    _circular_mean(d["wind_dir"]),
            "wind_dir_str":_deg_to_compass(_circular_mean(d["wind_dir"])),
            "precip":      round(sum(d["precip"]), 1),
            "prec_prob":   mx_prob(d["prec_prob"]),
            "wave_height": avg(d["wave"]),
            "wave_period": avg_i(d["wave_period"]),
        })
    return result


async def _fetch_location_weather(session: aiohttp.ClientSession, lat: float, lon: float) -> list:
    """Почасовой прогноз Open-Meteo + Marine для одной локации, средние за 07–21."""
    t = aiohttp.ClientTimeout(total=12)
    try:
        w = await (await session.get(
            "https://api.open-meteo.com/v1/forecast", timeout=t,
            params={
                "latitude": lat, "longitude": lon,
                "wind_speed_unit": "ms",
                "timezone": "Asia/Vladivostok",
                "forecast_days": 2,
                "hourly": ",".join([
                    "temperature_2m", "windspeed_10m", "windgusts_10m",
                    "winddirection_10m", "precipitation",
                    "precipitation_probability", "weathercode",
                ]),
            }
        )).json()
        m = await (await session.get(
            "https://marine-api.open-meteo.com/v1/marine", timeout=t,
            params={
                "latitude": lat, "longitude": lon,
                "timezone": "Asia/Vladivostok",
                "forecast_days": 2,
                "hourly": "wave_height,wave_period",
            }
        )).json()
        return _process_daylight_hourly(w.get("hourly", {}), m.get("hourly", {}))
    except Exception as ex:
        logger.warning(f"Open-Meteo {lat},{lon}: {ex}")
        return []


async def _fetch_wwo_marine(session: aiohttp.ClientSession, key: str) -> list | None:
    """WWO Marine — свелл и температура воды для о. Русский (только световой день)."""
    if not key:
        return None
    try:
        resp = await session.get(
            "https://api.worldweatheronline.com/premium/v1/marine.ashx",
            timeout=aiohttp.ClientTimeout(total=15),
            params={
                "key": key, "q": f"{SUP_LAT},{SUP_LON}",
                "format": "json", "num_of_days": 2, "tp": 3,
            }
        )
        data     = await resp.json()
        err      = data.get("data", {}).get("error")
        if err:
            logger.warning(f"WWO Marine error: {err}")
            return None
        days_raw = data.get("data", {}).get("weather", [])
        result   = []
        for day in days_raw[:2]:
            hourly = day.get("hourly", [])
            # Фильтрация светового дня: поле "time" = "0","300","600",...,"2100"
            day_hourly = [
                h for h in hourly
                if 700 <= int(h.get("time", "0")) <= 2000
            ]
            if not day_hourly:
                day_hourly = hourly   # fallback — берём все если пусто

            def _f(h, k, default=0.0):
                try: return float(h.get(k, default) or default)
                except: return default

            wave_h  = [_f(h, "sigHeight_m")      for h in day_hourly]
            swell_h = [_f(h, "swellHeight_m")    for h in day_hourly]
            swell_p = [_f(h, "swellPeriod_secs") for h in day_hourly]
            water_t = [_f(h, "waterTemp_C")       for h in day_hourly]

            result.append({
                "wave_height":  round(sum(wave_h)  / len(wave_h),  1) if wave_h  else 0,
                "swell_height": round(max(swell_h), 1)                if swell_h else None,
                "swell_period": round(sum(swell_p) / len(swell_p))    if swell_p else None,
                "water_temp":   round(sum(water_t) / len(water_t), 1) if water_t else None,
            })
        return result if result else None
    except Exception as ex:
        logger.warning(f"WWO Marine: {ex}")
        return None


async def _fetch_all_weather() -> list:
    """
    Параллельно загружает почасовой прогноз для 3 локаций + WWO для Русского.
    Возвращает список словарей: [{"location": {...}, "days": [day1, day2]}, ...].
    """
    async with aiohttp.ClientSession() as session:
        loc_tasks = [
            _fetch_location_weather(session, loc["lat"], loc["lon"])
            for loc in WEATHER_LOCATIONS
        ]
        wwo_task = _fetch_wwo_marine(session, WWO_KEY)
        all_res  = await asyncio.gather(*loc_tasks, wwo_task, return_exceptions=True)

    n   = len(WEATHER_LOCATIONS)
    wwo = all_res[n] if isinstance(all_res[n], list) else []

    location_data = []
    for i, loc in enumerate(WEATHER_LOCATIONS):
        days = all_res[i] if isinstance(all_res[i], list) else []
        # Для Русского острова (i==0) обогащаем данными WWO
        if i == 0:
            for j, day in enumerate(days):
                w = wwo[j] if j < len(wwo) else {}
                # Приоритет у WWO по волне если есть
                if w.get("wave_height"):
                    day["wave_height"] = w["wave_height"]
                day["swell_height"] = w.get("swell_height")
                day["swell_period"] = w.get("swell_period")
                day["water_temp"]   = w.get("water_temp")
                day["sources"] = (["Open-Meteo"]
                                  + (["WorldWeatherOnline"] if wwo else []))
        location_data.append({"location": loc, "days": days})

    return location_data


# ══════════════════════════════════════════════════════
#  МЕНЮ
# ══════════════════════════════════════════════════════

async def menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Выбери действие:",
        reply_markup=_main_keyboard())


# ══════════════════════════════════════════════════════
#  АНОНС
# ══════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "🏄‍♂️ *Привет! Я помогу составить анонс САП-прогулки.*\n\n"
        "Отвечай на вопросы — я сформирую пост и отправлю его на проверку.\n\n"
        "📅 *Дата прогулки?*\n_Пример: суббота, 14 июня_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove())
    return DATE

async def get_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["date"] = update.message.text.strip()
    await update.message.reply_text(
        "📍 *Место сбора?*\n_Пример: Набережная Горького, у моста (ссылка 2Gis)_",
        parse_mode="Markdown")
    return LOCATION

async def get_location(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["location"] = update.message.text.strip()
    await update.message.reply_text("⏰ *Время сбора?*\n_Пример: 10:00_", parse_mode="Markdown")
    return TIME

async def get_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["time"] = update.message.text.strip()
    await update.message.reply_text(
        "🗺 *Маршрут прогулки?*\n_Пример: вдоль набережной до острова и обратно_",
        parse_mode="Markdown")
    return ROUTE

async def get_route(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["route"] = update.message.text.strip()
    await update.message.reply_text(
        "🕐 *Продолжительность прогулки?*\n_Пример: 2 часа_",
        parse_mode="Markdown")
    return DURATION

async def get_duration(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["duration"] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("🐣 Для новичков", callback_data="level_beginner")],
        [InlineKeyboardButton("🏄 Все уровни",   callback_data="level_all")],
        [InlineKeyboardButton("💪 Опытные",       callback_data="level_advanced")],
    ]
    await update.message.reply_text(
        "🎯 *Уровень подготовки?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard))
    return LEVEL

async def get_level(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    levels = {
        "level_beginner": "🐣 Для новичков",
        "level_all":      "🏄 Все уровни",
        "level_advanced": "💪 Опытные",
    }
    ctx.user_data["level"] = levels[q.data]
    await q.edit_message_text(
        f"Уровень: *{ctx.user_data['level']}* ✓\n\n"
        f"👤 *Кто предложил прогулку?*\n_Пример: @username (телефон +7)_",
        parse_mode="Markdown")
    return CONTACT

async def get_contact(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["contact"] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("📷 Прикрепить фото", callback_data="add_photo")],
        [InlineKeyboardButton("⏭ Пропустить",        callback_data="skip_photo")],
    ]
    await update.message.reply_text(
        "🖼 *Хочешь добавить фото к анонсу?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard))
    return PHOTO

async def photo_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "add_photo":
        await q.edit_message_text("📷 Отправь фото для анонса:")
        return PHOTO
    ctx.user_data["photo_id"] = None
    await show_announce_preview(q.message, ctx)
    return CONFIRM

async def get_announce_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["photo_id"] = update.message.photo[-1].file_id
    await show_announce_preview(update.message, ctx)
    return CONFIRM

def build_post(d: dict) -> str:
    return (
        f"🏄‍♂️ *САП-ПРОГУЛКА*\n{'━'*16}\n\n"
        f"📅  *Дата:* {_escape_md(d['date'])}\n"
        f"⏰  *Сбор:* {_escape_md(d['time'])}\n"
        f"🕐  *Длительность:* {_escape_md(d['duration'])}\n"
        f"📍  *Место сбора:* {_escape_md(d['location'])}\n"
        f"🗺  *Маршрут:* {_escape_md(d['route'])}\n"
        f"🎯  *Уровень:* {_escape_md(d['level'])}\n\n"
        f"👤  *Предложил:* {_escape_md(d['contact'])}\n\n"
        f"#сап #сапсёрфинг #прогулка #paddle #sup"
    )

async def show_announce_preview(message, ctx):
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Отправить на проверку", callback_data="announce_submit"),
        InlineKeyboardButton("✏️ Начать заново",         callback_data="announce_restart"),
    ]])
    await message.reply_text(
        f"*Вот твой анонс:*\n\n{build_post(ctx.user_data)}",
        parse_mode="Markdown",
        reply_markup=keyboard)

async def confirm_announce(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "announce_restart":
        await q.edit_message_text("↩️ Начинаем заново. Нажми 📝 Анонс")
        return ConversationHandler.END

    d, author  = ctx.user_data, q.from_user
    post_text  = build_post(d)
    photo_id   = d.get("photo_id")
    author_info = f"@{author.username}" if author.username else f"id:{author.id}"

    pending = ctx.bot_data.setdefault("pending", {})
    pending[f"announce_{author.id}"] = {
        "text": post_text, "photo_id": photo_id, "type": "announce",
        "author_display": author_info,
        "schedule_entry": {k: d.get(k, "") for k in ["date", "time", "location", "route", "duration", "level", "contact"]},
    }

    mod_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:announce_{author.id}"),
        InlineKeyboardButton("❌ Отклонить",    callback_data=f"reject:announce_{author.id}"),
    ]])
    if photo_id:
        await ctx.bot.send_photo(ADMIN_ID, photo=photo_id)
    await ctx.bot.send_message(
        ADMIN_ID,
        f"📬 *Новый анонс от* {_escape_md(author_info)}\n{'─'*28}\n\n{post_text}\n\n{'─'*28}\nОпубликовать в канал?",
        parse_mode="Markdown",
        reply_markup=mod_keyboard)
    await q.edit_message_text(
        "⏳ *Анонс отправлен на проверку.*\nКак только одобрят — пост появится в канале. Спасибо! 🙌",
        parse_mode="Markdown")
    await ctx.bot.send_message(author.id, "Выбери действие:", reply_markup=_main_keyboard())
    return ConversationHandler.END


# ══════════════════════════════════════════════════════
#  ОТЗЫВ
# ══════════════════════════════════════════════════════

async def review_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["review_media"] = []
    await update.message.reply_text(
        "🌊 *Поделись впечатлениями о прогулке!*\n\n✍️ *Напиши комментарий или отзыв:*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove())
    return REVIEW_COMMENT

async def get_review_comment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["review_comment"] = update.message.text.strip()
    await update.message.reply_text(
        "👤 *Как тебя подписать?*\n"
        "_Укажи только одного автора — своё имя или @username_\n"
        "_Пример: Максим или @maximvk_",
        parse_mode="Markdown")
    return REVIEW_AUTHOR

async def get_review_author(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["review_author"] = update.message.text.strip()
    await update.message.reply_text(
        "👥 *Кто ещё был на прогулке?*\n\n"
        "_Перечисли участников через пробел или с новой строки._\n"
        "_Формат: @username — если есть нижнее подчёркивание, пишем его точно._\n"
        "_Можно и просто имена: Максим, Аня._\n"
        "_Количество не ограничено._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ Пропустить", callback_data="skip_participants")
        ]]))
    return REVIEW_PARTICIPANTS

async def get_review_participants(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Пользователь ввёл список участников текстом."""
    ctx.user_data["review_participants"] = update.message.text.strip()
    await _prompt_review_media(update.message)
    return REVIEW_MEDIA

async def skip_participants_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Нажата кнопка «Пропустить» на шаге участников."""
    q = update.callback_query
    await q.answer()
    ctx.user_data["review_participants"] = ""
    await _prompt_review_media(q.message)
    return REVIEW_MEDIA

async def _prompt_review_media(message):
    """Вспомогательная: показывает приглашение загрузить медиа."""
    await message.reply_text(
        "📸 *Отправь фото или видео с прогулки.*\n\n"
        "До 10 файлов — по одному.\n"
        "Когда закончишь — нажми *«Готово»*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Готово", callback_data="review_done")
        ]]))

async def get_review_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    media = ctx.user_data.setdefault("review_media", [])
    if len(media) >= 10:
        await update.message.reply_text(
            "⚠️ Максимум 10 файлов. Нажми *«Готово»*.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Готово", callback_data="review_done")]]))
        return REVIEW_MEDIA
    if update.message.photo:
        media.append({"type": "photo", "file_id": update.message.photo[-1].file_id})
    elif update.message.video:
        media.append({"type": "video", "file_id": update.message.video.file_id})
    count = len(media)
    await update.message.reply_text(
        f"{'📷' if update.message.photo else '🎥'} Файл {count} принят! "
        f"{'Осталось: ' + str(10 - count) if count < 10 else 'Максимум достигнут.'}\n"
        f"Нажми *«Готово»* когда закончишь.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Готово", callback_data="review_done")]]))
    return REVIEW_MEDIA

async def review_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    media        = ctx.user_data.get("review_media", [])
    comment      = ctx.user_data.get("review_comment", "")
    author       = ctx.user_data.get("review_author", "")
    participants = ctx.user_data.get("review_participants", "")

    if not media:
        await q.edit_message_text("⚠️ Пришли хотя бы один файл, а потом нажми «Готово».")
        return REVIEW_MEDIA

    caption    = _build_review_caption(comment, author, participants)
    will_split = len(caption) > CAPTION_LIMIT
    if will_split:
        format_note = (
            f"\n\n📝 _Текст длинный ({len(comment)} симв.) — выйдет двумя постами:_\n"
            "_1️⃣ Текст отзыва   2️⃣ Фото/видео_"
        )
    else:
        format_note = f"\n\n📝 _{len(comment)} симв. — выйдет одним постом_"

    parts_line = f"\n👥 Участники: {_escape_md(participants)}" if participants else ""
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Отправить на проверку", callback_data="review_submit"),
        InlineKeyboardButton("✏️ Начать заново",         callback_data="review_restart"),
    ]])
    await q.edit_message_text(
        f"*Твой отзыв:*\n\n"
        f"💬 {_escape_md(comment)}\n\n"
        f"Отзыв оставил: {_escape_md(author)}{parts_line}\n"
        f"📎 Файлов: {len(media)}"
        f"{format_note}",
        parse_mode="Markdown",
        reply_markup=keyboard)
    return REVIEW_CONFIRM

async def confirm_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "review_restart":
        await q.edit_message_text("↩️ Начинаем заново. Нажми 📸 Отзыв")
        return ConversationHandler.END

    author       = q.from_user
    author_info  = ctx.user_data.get("review_author", f"@{author.username}" if author.username else f"id:{author.id}")
    comment      = ctx.user_data.get("review_comment", "")
    participants = ctx.user_data.get("review_participants", "")
    media        = ctx.user_data.get("review_media", [])

    ctx.bot_data.setdefault("pending", {})[f"review_{author.id}"] = {
        "type":         "review",
        "comment":      comment,
        "media":        media,
        "author":       author_info,
        "author_display": author_info,
        "participants": participants,
    }

    try:
        # Подпись к медиа у администратора — всегда короткая (лимит 1024 символа)
        await _send_media_group(ctx, ADMIN_ID, media, caption="📸 Медиа из отзыва")

        # Текстовое сообщение с кнопками модерации
        parts_hint = f"\n👥 Участники: {participants}" if participants else ""
        caption_preview = _build_review_caption(comment, author_info, participants)
        split_note = "\n\n⚠️ _Длинный отзыв — выйдет двумя постами в канале_" if len(caption_preview) > CAPTION_LIMIT else ""

        # Если комментарий очень длинный — показываем обрезанную версию администратору
        # (полный текст уйдёт в канал при публикации)
        ADMIN_COMMENT_LIMIT = 800
        if len(comment) > ADMIN_COMMENT_LIMIT:
            comment_display = _escape_md(comment[:ADMIN_COMMENT_LIMIT]) + f"…\n_(показано {ADMIN_COMMENT_LIMIT} из {len(comment)} символов)_"
        else:
            comment_display = _escape_md(comment)

        mod_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:review_{author.id}"),
            InlineKeyboardButton("❌ Отклонить",    callback_data=f"reject:review_{author.id}"),
        ]])
        await ctx.bot.send_message(
            ADMIN_ID,
            f"📸 *Новый отзыв от* {_escape_md(author_info)}\n{'─'*28}\n\n"
            f"💬 {comment_display}{_escape_md(parts_hint)}\n📎 Файлов: {len(media)}"
            f"{split_note}\n\n{'─'*28}\nОпубликовать в канал?",
            parse_mode="Markdown",
            reply_markup=mod_keyboard)
    except Exception as e:
        logger.error(f"confirm_review send to admin failed: {e}")
        # Убираем из pending чтобы пользователь мог попробовать ещё раз
        ctx.bot_data.get("pending", {}).pop(f"review_{author.id}", None)
        await q.edit_message_text(
            "⚠️ *Не удалось отправить отзыв на проверку.*\n\n"
            "Попробуй ещё раз — нажми 📸 Отзыв",
            parse_mode="Markdown")
        return ConversationHandler.END

    await q.edit_message_text(
        "⏳ *Отзыв отправлен на проверку.*\nКак только одобрят — пост появится в канале. Спасибо! 🙌",
        parse_mode="Markdown")
    await ctx.bot.send_message(author.id, "Выбери действие:", reply_markup=_main_keyboard())
    return ConversationHandler.END

async def _send_media_group(ctx, chat_id, media, caption=""):
    if not media: return
    items = []
    for i, item in enumerate(media):
        cap = caption if i == 0 else None
        if item["type"] == "photo":
            items.append(InputMediaPhoto(media=item["file_id"], caption=cap, parse_mode="Markdown"))
        else:
            items.append(InputMediaVideo(media=item["file_id"], caption=cap, parse_mode="Markdown"))
    await ctx.bot.send_media_group(chat_id=chat_id, media=items)

def _build_review_caption(comment: str, author: str, participants: str) -> str:
    """Собирает финальный текст отзыва для публикации в канале."""
    parts_line = f"\n👥 Участники: {_escape_md(participants)}" if participants else ""
    return (
        f"🌊 *Впечатления от прогулки*\n\n"
        f"💬 {_escape_md(comment)}\n\n"
        f"Отзыв оставил: {_escape_md(author)}{parts_line}\n\n"
        f"#сап #отзыв #впечатления"
    )

# Лимит Telegram на подпись к медиа-группе
CAPTION_LIMIT = 1024


# ══════════════════════════════════════════════════════
#  НОВОСТЬ
# ══════════════════════════════════════════════════════

async def news_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "📰 *Новость для сообщества*\n\n✍️ Напиши текст новости:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove())
    return NEWS_TEXT

async def news_get_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["news_text"] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("📷 Добавить фото", callback_data="news_add_photo")],
        [InlineKeyboardButton("⏭ Без фото",       callback_data="news_skip_photo")],
    ]
    await update.message.reply_text(
        "🖼 Хочешь добавить фото к новости?",
        reply_markup=InlineKeyboardMarkup(keyboard))
    return NEWS_PHOTO

async def news_photo_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "news_add_photo":
        await q.edit_message_text("📷 Отправь фото:")
        return NEWS_PHOTO
    ctx.user_data["news_photo_id"] = None
    await _show_news_preview(q.message, ctx)
    return NEWS_CONFIRM

async def news_get_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["news_photo_id"] = update.message.photo[-1].file_id
    await _show_news_preview(update.message, ctx)
    return NEWS_CONFIRM

async def _show_news_preview(message, ctx):
    text     = ctx.user_data.get("news_text", "")
    photo_id = ctx.user_data.get("news_photo_id")
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Отправить на проверку", callback_data="news_submit"),
        InlineKeyboardButton("✏️ Начать заново",         callback_data="news_restart"),
    ]])
    preview = (
        f"*Твоя новость:*\n\n"
        f"📰 {_escape_md(text)}\n\n"
        f"{'📎 Фото прикреплено' if photo_id else '📎 Без фото'}"
    )
    await message.reply_text(preview, parse_mode="Markdown", reply_markup=keyboard)

async def confirm_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "news_restart":
        await q.edit_message_text("↩️ Начинаем заново. Нажми 📰 Новость")
        return ConversationHandler.END

    author      = q.from_user
    author_info = f"@{author.username}" if author.username else f"id:{author.id}"
    text        = ctx.user_data.get("news_text", "")
    photo_id    = ctx.user_data.get("news_photo_id")

    post_text = (
        f"📰 *НОВОСТЬ*\n{'━'*16}\n\n"
        f"{_escape_md(text)}\n\n"
        f"#сап #новость"
    )

    ctx.bot_data.setdefault("pending", {})[f"news_{author.id}"] = {
        "type":           "news",
        "text":           post_text,
        "photo_id":       photo_id,
        "author_display": author_info,
    }

    mod_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:news_{author.id}"),
        InlineKeyboardButton("❌ Отклонить",    callback_data=f"reject:news_{author.id}"),
    ]])
    if photo_id:
        await ctx.bot.send_photo(ADMIN_ID, photo=photo_id)
    await ctx.bot.send_message(
        ADMIN_ID,
        f"📰 *Новость от* {_escape_md(author_info)}\n{'─'*28}\n\n{post_text}\n\n{'─'*28}\nОпубликовать в канал?",
        parse_mode="Markdown",
        reply_markup=mod_keyboard)
    await q.edit_message_text(
        "⏳ *Новость отправлена на проверку.*\nКак только одобрят — появится в канале. Спасибо! 🙌",
        parse_mode="Markdown")
    await ctx.bot.send_message(author.id, "Выбери действие:", reply_markup=_main_keyboard())
    return ConversationHandler.END


# ══════════════════════════════════════════════════════
#  МОДЕРАЦИЯ
# ══════════════════════════════════════════════════════

async def moderate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        await q.answer("⛔ Только администратор.", show_alert=True)
        return

    action, key = q.data.split(":", 1)
    pending     = ctx.bot_data.get("pending", {})
    post_data   = pending.pop(key, None)
    if not post_data:
        await q.edit_message_text("⚠️ Данные не найдены. Попроси автора отправить повторно.")
        return

    user_id = int(key.split("_", 1)[1])

    if action == "approve":
        try:
            ptype = post_data["type"]
            if ptype == "announce":
                if post_data["photo_id"]:
                    await ctx.bot.send_photo(CHANNEL_ID, photo=post_data["photo_id"],
                                             caption=post_data["text"], parse_mode="Markdown")
                else:
                    await ctx.bot.send_message(CHANNEL_ID, text=post_data["text"], parse_mode="Markdown")
                schedule = ctx.bot_data.setdefault("schedule", [])
                schedule.append(post_data["schedule_entry"])
                ctx.bot_data["schedule"] = schedule[-20:]
            elif ptype == "review":
                caption = _build_review_caption(
                    post_data["comment"],
                    post_data["author"],
                    post_data.get("participants", ""),
                )
                if len(caption) <= CAPTION_LIMIT:
                    # Короткий отзыв — один пост: альбом с подписью
                    await _send_media_group(ctx, CHANNEL_ID, post_data["media"], caption=caption)
                else:
                    # Длинный отзыв — два поста: сначала текст, потом альбом
                    await ctx.bot.send_message(CHANNEL_ID, text=caption, parse_mode="Markdown")
                    await _send_media_group(ctx, CHANNEL_ID, post_data["media"])
            elif ptype == "news":
                if post_data["photo_id"]:
                    await ctx.bot.send_photo(CHANNEL_ID, photo=post_data["photo_id"],
                                             caption=post_data["text"], parse_mode="Markdown")
                else:
                    await ctx.bot.send_message(CHANNEL_ID, text=post_data["text"], parse_mode="Markdown")
        except Exception as e:
            await q.edit_message_text(f"⚠️ Ошибка при публикации:\n{e}")
            return

        label          = {"announce": "Анонс", "review": "Отзыв", "news": "Новость"}.get(post_data["type"], "Пост")
        author_display = post_data.get("author_display", f"id:{user_id}")
        pts            = "2" if post_data["type"] == "review" else "1"
        hint           = f"\n💡 Не забудь начислить очки: /addpoints {author_display.lstrip('@')} {pts}" if post_data["type"] != "news" else ""
        await q.edit_message_text(f"✅ {label} опубликован!\n\n👤 Автор: {author_display}{hint}")
        try:
            await ctx.bot.send_message(user_id, "🎉 *Твой пост одобрен и опубликован в канале!*",
                                       parse_mode="Markdown")
        except Exception:
            pass

    elif action == "reject":
        label = {"announce": "Анонс", "review": "Отзыв", "news": "Новость"}.get(post_data["type"], "Пост")
        await q.edit_message_text(f"❌ {label} отклонён.")
        try:
            await ctx.bot.send_message(
                user_id,
                "😔 *К сожалению, твой пост отклонён.*",
                parse_mode="Markdown")
        except Exception:
            pass


# ══════════════════════════════════════════════════════
#  РАСПИСАНИЕ
# ══════════════════════════════════════════════════════

async def schedule_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    entries = ctx.bot_data.get("schedule", [])
    if not entries:
        await update.message.reply_text(
            "📭 *Ближайших прогулок пока нет.*\n\nСоздай анонс через 📝 Анонс 🏄‍♂️",
            parse_mode="Markdown")
        return
    lines = ["🗓 *Ближайшие САП-прогулки:*\n"]
    for i, e in enumerate(entries, 1):
        lines.append(
            f"*{i}. {_escape_md(e['date'])}*\n"
            f"⏰ {_escape_md(e['time'])}  🎯 {_escape_md(e['level'])}\n"
            f"📍 {_escape_md(e['location'])}\n"
            f"👤 {_escape_md(e['contact'])}\n"
        )
    lines.append("_Подробности — в канале._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════════════
#  БЭКАП И ВОССТАНОВЛЕНИЕ РАСПИСАНИЯ
# ══════════════════════════════════════════════════════

async def schedulebackup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Только для администратора.
    Выводит текущее расписание в виде команд /addschedule для восстановления после деплоя.

    Сценарий:
      1. Перед деплоем: /schedulebackup → скопировать список команд
      2. После деплоя: отправить сохранённые команды по одной боту
    """
    if update.effective_user.id != ADMIN_ID:
        return
    schedule = ctx.bot_data.get("schedule", [])
    if not schedule:
        await update.message.reply_text("📭 Расписание пусто — нечего сохранять.")
        return
    fields = ["date", "time", "location", "route", "duration", "level", "contact"]
    lines  = [
        "📋 *Резервная копия расписания*\n"
        "_(скопируй и сохрани, отправь после деплоя по одной команде)_\n"
    ]
    for e in schedule:
        parts   = [str(e.get(k, "")).replace("|", "/") for k in fields]  # | — разделитель
        encoded = "|".join(parts)
        lines.append(f"/addschedule {encoded}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def addschedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Только для администратора.
    Добавляет запись в расписание из строки-бэкапа.
    Формат: /addschedule дата|время|место|маршрут|длительность|уровень|контакт
    """
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text.strip()
    if " " not in text:
        await update.message.reply_text(
            "Использование:\n"
            "`/addschedule дата|время|место|маршрут|длительность|уровень|контакт`\n\n"
            "Разделитель полей — вертикальная черта `|`",
            parse_mode="Markdown")
        return
    raw   = text.split(" ", 1)[1]
    parts = raw.split("|")
    if len(parts) < 7:
        await update.message.reply_text(
            f"⚠️ Нужно 7 полей через `|`, получено {len(parts)}.\n"
            "Формат: дата|время|место|маршрут|длительность|уровень|контакт",
            parse_mode="Markdown")
        return
    keys  = ["date", "time", "location", "route", "duration", "level", "contact"]
    entry = {k: parts[i].strip() for i, k in enumerate(keys)}
    schedule = ctx.bot_data.setdefault("schedule", [])
    schedule.append(entry)
    ctx.bot_data["schedule"] = schedule[-20:]
    await update.message.reply_text(
        f"✅ Добавлено в расписание:\n"
        f"📅 {entry['date']} | ⏰ {entry['time']}\n"
        f"📍 {entry['location']}"
    )


# ══════════════════════════════════════════════════════
#  ПОГОДА
# ══════════════════════════════════════════════════════

async def weather(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "⏳ Загружаю прогноз для острова Русский и заливов...")
    try:
        location_data = await _fetch_all_weather()
    except Exception as e:
        logger.error(f"Weather fetch error: {e}")
        await msg.edit_text("⚠️ Не удалось получить данные. Попробуй позже.")
        return

    lines = [
        "🌊 *Прогноз погоды*",
        "_Средние показатели за световой день 07:00–21:00_",
        "━" * 16,
    ]

    for loc_idx, loc_entry in enumerate(location_data):
        loc      = loc_entry["location"]
        days     = loc_entry["days"]
        is_main  = (loc_idx == 0)   # Остров Русский — полный блок

        lines.append(f"\n{loc['emoji']} *{loc['name']}*")

        if not days:
            lines.append("_Данные временно недоступны_")
            continue

        for i, d in enumerate(days):
            wind  = d.get("wind_speed", 0)
            wave  = d.get("wave_height", 0)
            gusts = d.get("wind_gusts", 0)

            if is_main:
                # ── Полный блок для Острова Русский ──
                water_line = f"🌡 Вода: +{d['water_temp']}°C\n" if d.get("water_temp") else ""
                swell_line = ""
                if d.get("swell_height") and d.get("swell_period"):
                    swell_line = f"〰️ Свелл: {d['swell_height']} м, период {int(d['swell_period'])} с\n"
                prob   = d.get("prec_prob", 0)
                precip = d.get("precip", 0)
                if precip > 0.1:
                    rain_line = f"☔ Осадки: {precip} мм (вероятность {prob}%)\n"
                elif prob > 0:
                    rain_line = f"☔ Вероятность дождя: {prob}%\n"
                else:
                    rain_line = "☔ Без осадков\n"

                lines.append(
                    f"\n📅 *{_date_label(d['date'])}* {d['icon']}\n"
                    f"🌡 Воздух: +{d['t_min']}°...+{d['t_max']}°C\n"
                    f"{water_line}"
                    f"💨 Ветер: {d['wind_dir_str']}, {wind} м/с (порывы {gusts} м/с) {_wind_dot(wind)}\n"
                    f"🌊 Волна: {wave} м {_wave_dot(wave)}\n"
                    f"{swell_line}"
                    f"{rain_line}\n"
                    f"{_sup_recommendations(d)}"
                )
                if i == 0 and len(days) > 1:
                    lines.append("")  # разрыв между днями

            else:
                # ── Компактная строка для заливов ──
                lines.append(
                    f"  📅 *{_date_label(d['date'])}*:  "
                    f"💨 {d['wind_dir_str']} {wind} м/с {_wind_dot(wind)}  |  "
                    f"🌊 {wave} м {_wave_dot(wave)}"
                )

        if is_main:
            lines.append("\n" + "━" * 16)

    # Источники данных
    sources = location_data[0]["days"][0].get("sources", ["Open-Meteo"]) if location_data[0]["days"] else ["Open-Meteo"]
    lines.append(f"\n_Данные: {' + '.join(sources)}_")
    lines.append("_⚠️ Прогноз приблизительный. Перед выходом проверяйте актуальную погоду._")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════════════
#  РЕЙТИНГ
# ══════════════════════════════════════════════════════

async def top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ratings = _ratings(ctx.bot_data)
    year    = datetime.now(VLAD_TZ).year
    if not ratings:
        await update.message.reply_text(
            "📊 *Рейтинг пока пуст*\n\nОчки начисляет организатор после каждой прогулки.\n\n"
            "🪸 За отзыв о прогулке — 2 очка\n🦀 За опубликованный анонс — 1 очко",
            parse_mode="Markdown")
        return
    sorted_r = sorted(ratings.items(), key=lambda x: x[1]["points"], reverse=True)
    medals   = ["🥇", "🥈", "🥉"]
    lines    = [f"🏆 *Рейтинг сезона {year}*\n"]
    for i, (username, data) in enumerate(sorted_r, 1):
        pts   = data["points"]
        medal = medals[i - 1] if i <= 3 else f"{i}."
        lines.append(f"{medal} {_get_rank(pts)} @{_escape_md(username)} — {pts} {_pts_word(pts)}")
    lines.append(
        "\n_🪸 За отзыв о прогулке — 2 очка_\n_🦀 За опубликованный анонс — 1 очко_\n\n"
        "*Звания:*\n_🪸 1\\-2 прогулки — Планктон_\n_🦀 3\\-5 прогулок — Баклан_\n"
        "_🐙 6\\-10 прогулок — Ларга_\n_🦈 11\\-20 прогулок — Кракен_\n_🔱 21\\+ прогулок — Посейдон_"
    )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def rank(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user     = update.effective_user
    username = user.username or ""
    ratings  = _ratings(ctx.bot_data)
    data     = ratings.get(username)
    if not data:
        await update.message.reply_text(
            "📊 *Ты пока не в рейтинге*\n\nОрганизатор начисляет очки после прогулок!\n\n"
            "🪸 За отзыв — 2 очка  |  🦀 За анонс — 1 очко",
            parse_mode="Markdown")
        return
    pts          = data["points"]
    current_rank = _get_rank(pts)
    next_info    = "🏆 Ты достиг высшего звания — Посейдон!\n"
    for min_pts, title in reversed(RANKS):
        if pts < min_pts:
            needed    = min_pts - pts
            next_info = f"🎯 До звания *{title}* — ещё {needed} {_pts_word(needed)}\n"
            break
    await update.message.reply_text(
        f"*Твой рейтинг*\n\nЗвание: {current_rank}\nОчки: {pts} {_pts_word(pts)}\n\n"
        f"{next_info}\n_🪸 За отзыв — 2 очка  |  🦀 За анонс — 1 очко_",
        parse_mode="Markdown")

async def addpoints(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args    = ctx.args
    ratings = _ratings(ctx.bot_data)
    if not args or len(args) < 2:
        if ratings:
            lines = ["👥 *Текущий рейтинг:*\n"]
            for username, data in sorted(ratings.items(), key=lambda x: x[1]["points"], reverse=True):
                pts = data["points"]
                lines.append(f"• @{username} — {pts} {_pts_word(pts)} ({_get_rank(pts)})")
            lines.append("\n_Использование: /addpoints username 5_")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        else:
            await update.message.reply_text(
                "📊 Рейтинг пуст.\n\n_Использование: /addpoints username 5_",
                parse_mode="Markdown")
        return
    username = args[0].lstrip("@")
    try:
        points = int(args[1])
    except ValueError:
        await update.message.reply_text("⚠️ Укажи целое число. Пример: /addpoints maximvk 5")
        return
    if username not in ratings:
        ratings[username] = {"points": 0}
    ratings[username]["points"] += points
    new_pts = ratings[username]["points"]
    action  = "начислено" if points > 0 else "снято"
    await update.message.reply_text(
        f"✅ @{_escape_md(username)}: {action} {abs(points)} {_pts_word(abs(points))}.\n"
        f"Итого: {new_pts} {_pts_word(new_pts)} — {_get_rank(new_pts)}",
        parse_mode="Markdown")

async def backup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    ratings = _ratings(ctx.bot_data)
    if not ratings:
        await update.message.reply_text("📊 Рейтинг пуст — нечего сохранять.")
        return
    lines = ["📋 *Резервная копия рейтинга*\n_(скопируй и сохрани)_\n"]
    for username, data in sorted(ratings.items(), key=lambda x: x[1]["points"], reverse=True):
        lines.append(f"/addpoints {username} {data['points']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def year_end_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(VLAD_TZ)
    if now.month != 12 or now.day != 31:
        return
    ratings = _ratings(context.bot_data)
    year    = now.year
    if ratings:
        sorted_r = sorted(ratings.items(), key=lambda x: x[1]["points"], reverse=True)
        medals   = ["🥇", "🥈", "🥉"]
        lines    = [f"🎉 *Итоги сезона {year}!*\n\nНаши лучшие сёрферы года:\n"]
        for i, (username, data) in enumerate(sorted_r[:10], 1):
            pts   = data["points"]
            medal = medals[i - 1] if i <= 3 else f"{i}."
            lines.append(f"{medal} {_get_rank(pts)} @{username} — {pts} {_pts_word(pts)}")
        lines.append(f"\nВсего участников: {len(ratings)}")
        lines.append("Поздравляем всех! До встречи на воде в следующем году 🏄‍♂️")
        try:
            await context.bot.send_message(CHANNEL_ID, "\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Year-end: {e}")
    context.bot_data["ratings"] = {}


# ══════════════════════════════════════════════════════
#  КОЛЕСО ФОРТУНЫ
# ══════════════════════════════════════════════════════

SPIN_PHRASES = [
    "Сегодня ларга уже заняла твоё место на воде\nи уходить не планирует 🦭",
    "Сегодня бакланы летят именно туда,\nкуда ты собрался идти 🦅",
    "Краб на дне видел твою технику гребли\nи решил стать инструктором 🦀",
    "Осьминог в бухте Новик уже знает\nтвой маршрут лучше тебя 🐙",
    "Косатки сегодня тренируются в проливе.\nТы им не помешаешь. Наверное 🐋",
    "Медузы сегодня собрались именно там,\nкуда ты хотел опустить руку 🪼",
    "Ларга смотрит на тебя с камня\nи думает то же самое что и ты 🦭",
    "Бакланы уже провели голосование —\nты звезда сезона 🦅",
    "Краб видел как ты гребёшь\nи предложил мастер-класс 🦀",
    "Ветер сегодня специально с той стороны,\nоткуда тебе плыть обратно 💨",
    "Волны сегодня тренировались,\nчтобы встретить именно тебя 🌊",
    "Прогноз говорит штиль.\nПрогноз врёт 😅",
    "Ветер сегодня изменит направление\nровно когда ты развернёшься 💨",
    "Волны обещали вести себя хорошо.\nИм не верь 🌊",
    "Японское море сегодня в настроении.\nВ каком именно — узнаешь на воде 🌊",
    "Штиль будет. Но только пока ты\nсобираешь снаряжение на берегу 😂",
    "Ветер сегодня дует со всех сторон\nодновременно. Физики в панике 💨",
    "Сегодня ты точно перевернёшься.\nНо красиво 😂",
    "Весло сегодня будет грести само.\nТы просто держись 🏄",
    "Доска сегодня решила что она каяк.\nПереубедить не получится 😄",
    "Твой лиш сегодня запутается\nв самый неподходящий момент 🤣",
    "Гидрокостюм надевать долго.\nЗато снимать ещё дольше 😅",
    "Сегодня ты найдёшь идеальную технику гребли.\nЗавтра забудешь 🏄",
    "Доска говорит что готова.\nКолени не согласны 😂",
    "Весло сегодня будет задевать воду\nименно с той стороны где брызги 💦",
    "Бухта Новик сегодня ждёт именно тебя.\nОстальные пусть сами разбираются 🏖",
    "Пролив Старка сегодня в хорошем настроении.\nПролив Старка всегда врёт 😅",
    "Маршрут который ты выберешь\nокажется длиннее чем казался 🗺",
    "Самое красивое место сегодня\nровно за следующим мысом 📍",
    "Обратный путь всегда длиннее.\nЭто закон острова Русский ⚓",
    "До острова Попова рукой подать.\nЧужой рукой 😂",
    "Собираться ты будешь час.\nНа воде пробудешь на пять минут больше 😄",
    "Солнце выйдет ровно когда\nты соберёшься домой ☀️",
    "Идеальная погода для САПа —\nта которая уже прошла 😅",
    "Прогноз обещает солнце после обеда.\nТы уже дома после обеда 😂",
    "Сегодня лучший день для САПа.\nВчера тоже был лучший день ☀️",
    "Облака сегодня специально\nв форме доски для САПа ⛅",
    "Сегодня ты встретишь на воде\nчеловека с лучшим веслом чем у тебя 😄",
    "Кто-то уже занял твоё любимое место.\nКак они узнали 😤",
    "Фото получится отличным.\nНа третьей попытке 📸",
    "Ты вернёшься с прогулки\nи сразу захочешь обратно 🌊",
    "Сегодня ты объяснишь трём незнакомым людям\nчто такое САП 😅",
    "Телефон в гермочехле.\nКлючи от машины — нет 🔑",
    "Сегодня ты точно встанешь пораньше.\nСказал ты вчера вечером 😂",
    "Вода сегодня прозрачная.\nДно ближе чем кажется 💦",
    "После прогулки ты скажешь\n«надо было выйти раньше» 🕐",
    "Все завидуют.\nПросто молча 😎",
    "Сегодня ты выйдешь в море на сапе.\nЧайка оценит твою технику гребли и\nгромко прокомментирует 🐦",
    "День обещает встречу. Ларга всплывёт в трёх\nметрах, фыркнет и заставит тебя вздрогнуть 🦭",
    "Ты планировал маршрут до Токаревского маяка.\nВетер планировал иначе 🌬️",
    "Звёзды говорят: сегодня ты научишься\nгрести стоя на одной ноге. Потому что вторая\nбудет спасать телефон 📱",
    "На горизонте появится медуза-крестовик.\nТы вспомнишь, что ты не просто гребец,\nа спринтер 🏃",
    "Тебя ждёт романтический закат на воде.\nИ сотня мошек, которые тоже пришли посмотреть 🌅",
    "Сегодня ты встретишь рыбака на лодке.\nОн спросит: «Клюёт?» Ты ответишь:\n«Я на сапе». Он не поймёт 🎣",
    "День сулит встречу с местными: ты трижды\nобъяснишь прохожим, что это сап, а не доска\nдля сёрфинга и не катамаран 😅",
    "Сегодня ты встанешь на сап и почувствуешь\nсебя капитаном. Пока не пройдёт катер и не\nнапомнит, кто тут главный 🚢",
    "Ты вернёшься на берег, уставший и счастливый.\nВ кроссовках хлюпает, в термосе морская вода.\nЭто был хороший день 🌊",
    "День принесёт испытание: ты захочешь в туалет\nровно посередине бухты. Чайки осудят ☕",
    "Ты встретишь огромного трепанга. Он будет похож\nна огурец-переросток. Ты зависнешь, он зависнет.\nНичья 🥒",
    "Сегодня ты решишь грести спиной вперёд ради сториз.\nСап решит, что ты хочешь искупаться 🤳",
    "Предсказание: ты выйдешь на воду в штиль.\nЧерез десять минут придёт ветер с Амурского залива.\nОн всегда приходит 💨",
    "Ты увидишь гребешок, который плывёт быстрее тебя.\nГордость пошатнётся, но ты это заслужил 🐚",
    "Ты встретишь каякера. Между вами будет\nмолчаливая битва за звание самого медленного судна.\nПроиграют оба 🛶",
    "Предсказание: ты купишь новое весло.\nОно красивое. Ты уронишь его в воду в\nпервые пятнадцать минут. Конец 🏊",
    "Ты решишь поплавать не у берега, а «вон там, где красиво».\nКрасиво было. Обратно ты будешь грести\nсорок минут и материться 🌊",
    "Ты наденешь гидрокостюм. Он будет жать.\nТы будешь похож на упитанного сивуча.\nСивучи оценят 🦭",
]

async def spin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    today   = datetime.now(VLAD_TZ).strftime("%Y-%m-%d")
    spins   = ctx.bot_data.setdefault("spins", {})
    if spins.get(str(user_id)) == today:
        await update.message.reply_text(
            "🎰 Ты уже крутил колесо сегодня!\n\nВозвращайся завтра — колесо ждёт 😄")
        return
    spins[str(user_id)] = today
    await update.message.reply_text(
        f"🎰 *Колесо фортуны говорит...*\n\n{random.choice(SPIN_PHRASES)}",
        parse_mode="Markdown")


# ══════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════

def main():
    persistence = PicklePersistence(filepath="bot_data.pkl")
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

    # Диалог: Анонс
    announce_conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Text(["📝 Анонс"]), start),
        ],
        states={
            DATE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date)],
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_location)],
            TIME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
            ROUTE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_route)],
            DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_duration)],
            LEVEL:    [CallbackQueryHandler(get_level, pattern="^level_")],
            CONTACT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_contact)],
            PHOTO: [
                CallbackQueryHandler(photo_choice, pattern="^(add_photo|skip_photo)$"),
                MessageHandler(filters.PHOTO, get_announce_photo),
            ],
            CONFIRM: [CallbackQueryHandler(confirm_announce, pattern="^announce_(submit|restart)$")],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True, per_message=False,
    )

    # Диалог: Отзыв (добавлен шаг REVIEW_PARTICIPANTS)
    review_conv = ConversationHandler(
        entry_points=[
            CommandHandler("review", review_start),
            MessageHandler(filters.Text(["📸 Отзыв"]), review_start),
        ],
        states={
            REVIEW_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_review_comment)
            ],
            REVIEW_AUTHOR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_review_author)
            ],
            REVIEW_PARTICIPANTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_review_participants),
                CallbackQueryHandler(skip_participants_cb, pattern="^skip_participants$"),
            ],
            REVIEW_MEDIA: [
                MessageHandler(filters.PHOTO | filters.VIDEO, get_review_media),
                CallbackQueryHandler(review_done, pattern="^review_done$"),
            ],
            REVIEW_CONFIRM: [
                CallbackQueryHandler(confirm_review, pattern="^review_(submit|restart)$")
            ],
        },
        fallbacks=[CommandHandler("review", review_start)],
        allow_reentry=True, per_message=False,
    )

    # Диалог: Новость
    news_conv = ConversationHandler(
        entry_points=[
            CommandHandler("news", news_start),
            MessageHandler(filters.Text(["📰 Новость"]), news_start),
        ],
        states={
            NEWS_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, news_get_text)],
            NEWS_PHOTO: [
                CallbackQueryHandler(news_photo_choice, pattern="^news_(add_photo|skip_photo)$"),
                MessageHandler(filters.PHOTO, news_get_photo),
            ],
            NEWS_CONFIRM: [CallbackQueryHandler(confirm_news, pattern="^news_(submit|restart)$")],
        },
        fallbacks=[CommandHandler("news", news_start)],
        allow_reentry=True, per_message=False,
    )

    app.add_handler(announce_conv)
    app.add_handler(review_conv)
    app.add_handler(news_conv)

    # Кнопки меню → команды
    app.add_handler(MessageHandler(filters.Text(["🌤 Погода"]),          weather))
    app.add_handler(MessageHandler(filters.Text(["📅 Расписание"]),      schedule_cmd))
    app.add_handler(MessageHandler(filters.Text(["🏆 Рейтинг"]),         top))
    app.add_handler(MessageHandler(filters.Text(["🎰 Колесо фортуны"]),  spin))

    # Команды пользователей
    app.add_handler(CommandHandler("menu",     menu))
    app.add_handler(CommandHandler("schedule", schedule_cmd))
    app.add_handler(CommandHandler("weather",  weather))
    app.add_handler(CommandHandler("top",      top))
    app.add_handler(CommandHandler("rank",     rank))
    app.add_handler(CommandHandler("spin",     spin))

    # Команды администратора
    app.add_handler(CommandHandler("addpoints",      addpoints))
    app.add_handler(CommandHandler("backup",         backup))
    app.add_handler(CommandHandler("schedulebackup", schedulebackup))
    app.add_handler(CommandHandler("addschedule",    addschedule))

    # Модерация
    app.add_handler(CallbackQueryHandler(moderate, pattern="^(approve|reject):"))

    # Ежегодный итог
    app.job_queue.run_daily(year_end_job, time=dtime(23, 59, tzinfo=VLAD_TZ))

    logger.info("🏄 САП-бот запущен.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
