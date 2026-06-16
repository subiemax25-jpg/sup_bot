"""
🏄 САП-бот: анонсы + отзывы + погода + расписание + рейтинг
============================================================
Установка:  pip install "python-telegram-bot[job-queue]" aiohttp
Запуск:     python3 bot.py
"""

import logging
import asyncio
import aiohttp
from datetime import date, datetime, time as dtime, timedelta, timezone
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto, InputMediaVideo
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler,
    filters, ContextTypes, PicklePersistence
)
import os

# ─────────────────────────────────────────────
#  НАСТРОЙКИ
# ─────────────────────────────────────────────
BOT_TOKEN      = os.environ.get("BOT_TOKEN",      "ВАШ_ТОКЕН_ОТ_BOTFATHER")
CHANNEL_ID     = os.environ.get("CHANNEL_ID",     "@ваш_канал")
ADMIN_ID       = int(os.environ.get("ADMIN_ID",   "123456789"))
STORMGLASS_KEY = os.environ.get("STORMGLASS_KEY", "")
OWM_KEY        = os.environ.get("OWM_KEY",        "")
# Ссылка на Windy с координатами острова Русский (слой ветра) — для кнопок
WINDY_URL      = "https://www.windy.com/?wind,42.948,131.941,11"
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  СОСТОЯНИЯ ДИАЛОГОВ
# ──────────────────────────────────────────────
DATE, LOCATION, TIME, ROUTE, DURATION, LEVEL, CONTACT, PHOTO, CONFIRM = range(9)
REVIEW_COMMENT, REVIEW_AUTHOR, REVIEW_MEDIA, REVIEW_CONFIRM = range(9, 13)

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
#  ПОГОДА
# ──────────────────────────────────────────────
SUP_LAT  = 42.948
SUP_LON  = 131.941
VLAD_TZ  = timezone(timedelta(hours=10))

MONTHS_RU = ["","января","февраля","марта","апреля","мая","июня",
              "июля","августа","сентября","октября","ноября","декабря"]

def _deg_to_compass(deg: float) -> str:
    dirs = ["С","ССВ","СВ","ВСВ","В","ВЮВ","ЮВ","ЮЮВ",
            "Ю","ЮЮЗ","ЮЗ","ЗЮЗ","З","ЗСЗ","СЗ","ССЗ"]
    return dirs[round(deg / 22.5) % 16]

def _wind_dot(s): return "🟢" if s < 4 else "🟡" if s < 7 else "🟠" if s < 11 else "🔴"
def _wave_dot(h): return "🟢" if h < 0.3 else "🟡" if h < 0.6 else "🟠" if h < 1.0 else "🔴"

def _verdict(wind, wave):
    if wind >= 12 or wave >= 1.0: return "🔴 Выход не рекомендуется"
    if wind >= 8  or wave >= 0.6: return "🟠 Сложные условия — только опытным"
    if wind >= 5  or wave >= 0.3: return "🟡 Приемлемо — выбирай укрытое место"
    return "🟢 Отлично — можно идти везде"

def _location_advice(wind_dir, wind, wave):
    if wind < 4 and wave < 0.3: return "Штиль 🌊 Любая точка острова — иди куда хочешь!"
    if wind >= 12: return "Слишком сильный ветер. Только закрытые бухты: Новик или Аякс."
    if   wind_dir < 22.5 or wind_dir >= 337.5: spot = "бухта Новик (южная сторона)"
    elif wind_dir < 67.5:                       spot = "западная сторона — Амурский залив"
    elif wind_dir < 112.5:                      spot = "западная сторона — Амурский залив"
    elif wind_dir < 157.5:                      spot = "бухта Аякс (северная сторона)"
    elif wind_dir < 202.5:                      spot = "северный берег, ближе к Владивостоку"
    elif wind_dir < 247.5:                      spot = "восточная сторона — Уссурийский залив"
    elif wind_dir < 292.5:                      spot = "восточная сторона — Уссурийский залив"
    else:                                        spot = "юго-восточная сторона острова"
    return f"Лучшее место: {spot} — там будет укрытие от ветра."

def _wmo_icon(code):
    if code == 0:  return "☀️"
    if code <= 3:  return "⛅"
    if code <= 48: return "🌫"
    if code <= 67: return "🌧"
    if code <= 77: return "❄️"
    if code <= 82: return "🌦"
    if code <= 86: return "🌨"
    return "⛈"

def _date_label(iso):
    d = date.fromisoformat(iso)
    today = date.today()
    if d == today:                       prefix = "Сегодня"
    elif d == today + timedelta(days=1): prefix = "Завтра"
    else:                                prefix = ""
    return f"{prefix}, {d.day} {MONTHS_RU[d.month]}" if prefix else f"{d.day} {MONTHS_RU[d.month]}"

def _sg_val(sources):
    if not sources: return None
    if "sg" in sources and sources["sg"] is not None: return sources["sg"]
    vals = [v for v in sources.values() if v is not None]
    return round(sum(vals)/len(vals), 2) if vals else None

def _sup_recommendations(d):
    wind, wave, gusts = d["wind_speed"], d["wave_height"], d["wind_gusts"]
    swell_h = d.get("swell_height") or 0
    swell_p = d.get("swell_period") or 0
    if wind < 4 and wave < 0.3:   who = "👶 Подходит для всех, включая новичков."
    elif wind < 7 and wave < 0.5: who = "🏄 Подходит для уверенных пользователей. Новичкам — только с опытным напарником."
    elif wind < 11 and wave < 0.8:who = "💪 Только для опытных. Новичкам выходить не рекомендуется."
    else:                          who = "🚫 Не рекомендуется никому."
    warnings = []
    if gusts - wind >= 4: warnings.append(f"⚡ Порывы {gusts} м/с — значительно сильнее среднего ветра.")
    if swell_h >= 0.5 and swell_p >= 7: warnings.append(f"〰️ Свелл {swell_h} м, период {int(swell_p)} с — на открытой воде качает.")
    if d.get("rain_prob", 0) >= 50: warnings.append("🌧 Высокая вероятность дождя — возьми гермочехол.")
    if d.get("water_temp") and d["water_temp"] < 15: warnings.append(f"🥶 Вода {d['water_temp']}°C — надевай гидрокостюм.")
    warnings_str = "\n".join(warnings) + "\n" if warnings else ""
    return f"*{_verdict(wind, wave)}*\n📍 {_location_advice(d['wind_dir'], wind, wave)}\n{who}\n{warnings_str}"

async def _fetch_open_meteo(session):
    t = aiohttp.ClientTimeout(total=10)
    w = await (await session.get("https://api.open-meteo.com/v1/forecast", timeout=t, params={
        "latitude": SUP_LAT, "longitude": SUP_LON, "wind_speed_unit": "ms",
        "timezone": "Asia/Vladivostok", "forecast_days": 2,
        "daily": "weathercode,temperature_2m_max,temperature_2m_min,windspeed_10m_max,windgusts_10m_max,winddirection_10m_dominant,precipitation_sum",
    })).json()
    m = await (await session.get("https://marine-api.open-meteo.com/v1/marine", timeout=t, params={
        "latitude": SUP_LAT, "longitude": SUP_LON,
        "timezone": "Asia/Vladivostok", "forecast_days": 2,
        "daily": "wave_height_max,wave_direction_dominant,wave_period_max",
    })).json()
    return {"weather": w["daily"], "marine": m["daily"]}

async def _fetch_stormglass(session, key):
    if not key: return None
    try:
        now = datetime.now(VLAD_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        resp = await (await session.get(
            "https://api.stormglass.io/v2/weather/point",
            headers={"Authorization": key},
            timeout=aiohttp.ClientTimeout(total=15),
            params={"lat": SUP_LAT, "lng": SUP_LON,
                    "start": int(now.timestamp()), "end": int((now+timedelta(days=2)).timestamp()),
                    "params": "waveHeight,wavePeriod,swellHeight,swellPeriod,windSpeed,waterTemperature"},
        )).json()
        days = {}
        for h in resp.get("hours", []):
            dt = datetime.fromisoformat(h["time"].replace("Z","+00:00")).astimezone(VLAD_TZ)
            e  = days.setdefault(dt.strftime("%Y-%m-%d"), {k:[] for k in ["wh","wp","sh","sp","wt"]})
            for f,k in [("waveHeight","wh"),("wavePeriod","wp"),("swellHeight","sh"),("swellPeriod","sp"),("waterTemperature","wt")]:
                v = _sg_val(h.get(f,{}))
                if v is not None: e[k].append(v)
        result = []
        for d in sorted(days)[:2]:
            e = days[d]
            mx  = lambda l: round(max(l),1) if l else None
            avg = lambda l: round(sum(l)/len(l),1) if l else None
            result.append({"wave_height": mx(e["wh"]), "wave_period": avg(e["wp"]),
                           "swell_height": mx(e["sh"]), "swell_period": avg(e["sp"]),
                           "water_temp": avg(e["wt"])})
        return result
    except Exception as ex:
        logger.warning(f"Stormglass: {ex}"); return None

async def _fetch_owm(session, key):
    if not key: return None
    try:
        resp = await (await session.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            timeout=aiohttp.ClientTimeout(total=10),
            params={"lat": SUP_LAT, "lon": SUP_LON, "appid": key, "units": "metric", "cnt": 16},
        )).json()
        days = {}
        for item in resp.get("list", []):
            dt = datetime.fromtimestamp(item["dt"], tz=VLAD_TZ)
            e  = days.setdefault(dt.strftime("%Y-%m-%d"), {"h":[],"p":[],"pop":[]})
            e["h"].append(item["main"]["humidity"])
            e["p"].append(item["main"]["pressure"])
            e["pop"].append(item.get("pop",0))
        result = []
        for d in sorted(days)[:2]:
            e = days[d]
            result.append({"humidity": round(sum(e["h"])/len(e["h"])),
                           "pressure": round(sum(e["p"])/len(e["p"])),
                           "rain_prob": round(max(e["pop"])*100)})
        return result
    except Exception as ex:
        logger.warning(f"OWM: {ex}"); return None

async def _fetch_all_weather():
    async with aiohttp.ClientSession() as session:
        om, sg, ow = await asyncio.gather(
            _fetch_open_meteo(session),
            _fetch_stormglass(session, STORMGLASS_KEY),
            _fetch_owm(session, OWM_KEY),
            return_exceptions=True,
        )
    wd = om["weather"] if isinstance(om,dict) else {}
    md = om["marine"]  if isinstance(om,dict) else {}
    sg = sg if isinstance(sg,list) else []
    ow = ow if isinstance(ow,list) else []
    days = []
    for i in range(2):
        s = sg[i] if i < len(sg) else {}
        o = ow[i] if i < len(ow) else {}
        wave_h = s.get("wave_height") or (round(md["wave_height_max"][i],1) if md and md.get("wave_height_max") else 0)
        wave_p = s.get("wave_period") or (round(md["wave_period_max"][i],0) if md and md.get("wave_period_max") else 0)
        src = ["Open-Meteo"] + (["Stormglass"] if s else []) + (["OpenWeatherMap"] if o else [])
        days.append({
            "date":        wd["time"][i] if wd.get("time") else "",
            "wmo":         wd.get("weathercode",[0])[i],
            "t_min":       round(wd["temperature_2m_min"][i]) if wd.get("temperature_2m_min") else "—",
            "t_max":       round(wd["temperature_2m_max"][i]) if wd.get("temperature_2m_max") else "—",
            "wind_speed":  round(wd["windspeed_10m_max"][i],1) if wd.get("windspeed_10m_max") else 0,
            "wind_gusts":  round(wd["windgusts_10m_max"][i],1) if wd.get("windgusts_10m_max") else 0,
            "wind_dir":    wd.get("winddirection_10m_dominant",[0])[i],
            "precip":      (wd["precipitation_sum"][i] or 0) if wd.get("precipitation_sum") else 0,
            "wave_height": wave_h, "wave_period": int(wave_p),
            "swell_height": s.get("swell_height"), "swell_period": s.get("swell_period"),
            "water_temp":  s.get("water_temp"),
            "humidity":    o.get("humidity"), "pressure": o.get("pressure"), "rain_prob": o.get("rain_prob"),
            "sources":     src,
        })
    return days


# ══════════════════════════════════════════════════════
#  АНОНС
# ══════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "🏄‍♂️ *Привет! Я помогу составить анонс САП-прогулки.*\n\n"
        "Отвечай на вопросы — я сформирую пост и отправлю его на проверку.\n\n"
        "📅 *Дата прогулки?*\n_Пример: суббота, 14 июня_", parse_mode="Markdown")
    return DATE

async def get_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["date"] = update.message.text.strip()
    await update.message.reply_text("📍 *Место сбора?*\n_Пример: Набережная Горького, у моста (ссылка 2Gis)_", parse_mode="Markdown")
    return LOCATION

async def get_location(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["location"] = update.message.text.strip()
    await update.message.reply_text("⏰ *Время сбора?*\n_Пример: 10:00_", parse_mode="Markdown")
    return TIME

async def get_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["time"] = update.message.text.strip()
    await update.message.reply_text("🗺 *Маршрут прогулки?*\n_Пример: вдоль набережной до острова и обратно (Без картинок)_", parse_mode="Markdown")
    return ROUTE

async def get_route(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["route"] = update.message.text.strip()
    await update.message.reply_text("🕐 *Продолжительность прогулки?*\n_Пример: 2 часа_", parse_mode="Markdown")
    return DURATION

async def get_duration(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["duration"] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("🐣 Для новичков", callback_data="level_beginner")],
        [InlineKeyboardButton("🏄 Все уровни",   callback_data="level_all")],
        [InlineKeyboardButton("💪 Опытные",       callback_data="level_advanced")],
    ]
    await update.message.reply_text("🎯 *Уровень подготовки?*", parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    return LEVEL

async def get_level(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    levels = {"level_beginner":"🐣 Для новичков","level_all":"🏄 Все уровни","level_advanced":"💪 Опытные"}
    ctx.user_data["level"] = levels[q.data]
    await q.edit_message_text(
        f"Уровень: *{ctx.user_data['level']}* ✓\n\n👤 *Кто предложил прогулку?*\n_Пример: @username (телефон +7)_",
        parse_mode="Markdown")
    return CONTACT

async def get_contact(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["contact"] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("📷 Прикрепить фото", callback_data="add_photo")],
        [InlineKeyboardButton("⏭ Пропустить",        callback_data="skip_photo")],
    ]
    await update.message.reply_text("🖼 *Хочешь добавить фото к анонсу?*", parse_mode="Markdown",
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
    await message.reply_text(f"*Вот твой анонс:*\n\n{build_post(ctx.user_data)}",
                             parse_mode="Markdown", reply_markup=keyboard)

async def confirm_announce(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "announce_restart":
        await q.edit_message_text("↩️ Начинаем заново. Напиши /start")
        return ConversationHandler.END

    d, author = ctx.user_data, q.from_user
    post_text = build_post(d)
    photo_id  = d.get("photo_id")
    author_info = f"@{author.username}" if author.username else f"id:{author.id}"

    pending = ctx.bot_data.setdefault("pending", {})
    pending[f"announce_{author.id}"] = {
        "text": post_text, "photo_id": photo_id, "type": "announce",
        "author_display": author_info,
        "schedule_entry": {k: d.get(k,"") for k in ["date","time","location","route","duration","level","contact"]},
    }

    mod_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:announce_{author.id}"),
        InlineKeyboardButton("❌ Отклонить",    callback_data=f"reject:announce_{author.id}"),
    ]])
    if photo_id: await ctx.bot.send_photo(ADMIN_ID, photo=photo_id)
    await ctx.bot.send_message(ADMIN_ID,
        f"📬 *Новый анонс от* {_escape_md(author_info)}\n{'─'*28}\n\n{post_text}\n\n{'─'*28}\nОпубликовать в канал?",
        parse_mode="Markdown", reply_markup=mod_keyboard)
    await q.edit_message_text(
        "⏳ *Анонс отправлен на проверку.*\nКак только одобрят — пост появится в канале. Спасибо! 🙌",
        parse_mode="Markdown")
    return ConversationHandler.END


# ══════════════════════════════════════════════════════
#  ОТЗЫВ
# ══════════════════════════════════════════════════════

async def review_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["review_media"] = []
    await update.message.reply_text(
        "🌊 *Поделись впечатлениями о прогулке!*\n\n✍️ *Напиши комментарий или отзыв:*",
        parse_mode="Markdown")
    return REVIEW_COMMENT

async def get_review_comment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["review_comment"] = update.message.text.strip()
    await update.message.reply_text(
        "👤 *Как тебя подписать?*\n_Укажи только одного автора — своё имя или @username_\n_Пример: Максим или @maximvk_",
        parse_mode="Markdown")
    return REVIEW_AUTHOR

async def get_review_author(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["review_author"] = update.message.text.strip()
    await update.message.reply_text(
        "📸 *Отправь фото или видео с прогулки.*\n\nДо 10 файлов — по одному.\nКогда закончишь — нажми *«Готово»*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Готово", callback_data="review_done")]]))
    return REVIEW_MEDIA

async def get_review_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    media = ctx.user_data.setdefault("review_media", [])
    if len(media) >= 10:
        await update.message.reply_text("⚠️ Максимум 10 файлов. Нажми *«Готово»*.", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Готово", callback_data="review_done")]]))
        return REVIEW_MEDIA
    if update.message.photo:
        media.append({"type":"photo","file_id":update.message.photo[-1].file_id})
    elif update.message.video:
        media.append({"type":"video","file_id":update.message.video.file_id})
    count = len(media)
    await update.message.reply_text(
        f"{'📷' if update.message.photo else '🎥'} Файл {count} принят! "
        f"{'Осталось: ' + str(10-count) if count < 10 else 'Максимум достигнут.'}\nНажми *«Готово»* когда закончишь.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Готово", callback_data="review_done")]]))
    return REVIEW_MEDIA

async def review_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    media   = ctx.user_data.get("review_media", [])
    comment = ctx.user_data.get("review_comment", "")
    author  = ctx.user_data.get("review_author", "")
    if not media:
        await q.edit_message_text("⚠️ Пришли хотя бы один файл, а потом нажми «Готово».")
        return REVIEW_MEDIA
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Отправить на проверку", callback_data="review_submit"),
        InlineKeyboardButton("✏️ Начать заново",         callback_data="review_restart"),
    ]])
    await q.edit_message_text(
        f"*Твой отзыв:*\n\n💬 {_escape_md(comment)}\n\nОтзыв оставил: {_escape_md(author)}\n📎 Файлов: {len(media)}",
        parse_mode="Markdown", reply_markup=keyboard)
    return REVIEW_CONFIRM

async def confirm_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "review_restart":
        await q.edit_message_text("↩️ Начинаем заново. Напиши /review")
        return ConversationHandler.END

    author      = q.from_user
    author_info = ctx.user_data.get("review_author", f"@{author.username}" if author.username else f"id:{author.id}")
    comment     = ctx.user_data.get("review_comment", "")
    media       = ctx.user_data.get("review_media", [])

    ctx.bot_data.setdefault("pending", {})[f"review_{author.id}"] = {
        "type": "review", "comment": comment, "media": media,
        "author": author_info, "author_display": author_info,
    }

    await _send_media_group(ctx, ADMIN_ID, media, caption=f"💬 {comment}")
    mod_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:review_{author.id}"),
        InlineKeyboardButton("❌ Отклонить",    callback_data=f"reject:review_{author.id}"),
    ]])
    await ctx.bot.send_message(ADMIN_ID,
        f"📸 *Новый отзыв от* {_escape_md(author_info)}\n{'─'*28}\n\n"
        f"💬 {_escape_md(comment)}\n📎 Файлов: {len(media)}\n\n{'─'*28}\nОпубликовать в канал?",
        parse_mode="Markdown", reply_markup=mod_keyboard)
    await q.edit_message_text(
        "⏳ *Отзыв отправлен на проверку.*\nКак только одобрят — пост появится в канале. Спасибо! 🙌",
        parse_mode="Markdown")
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


# ══════════════════════════════════════════════════════
#  МОДЕРАЦИЯ
# ══════════════════════════════════════════════════════

async def moderate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        await q.answer("⛔ Только администратор.", show_alert=True)
        return

    action, key  = q.data.split(":", 1)
    pending      = ctx.bot_data.get("pending", {})
    post_data    = pending.pop(key, None)
    if not post_data:
        await q.edit_message_text("⚠️ Данные не найдены. Попроси автора отправить повторно.")
        return

    user_id = int(key.split("_", 1)[1])

    if action == "approve":
        try:
            if post_data["type"] == "announce":
                if post_data["photo_id"]:
                    await ctx.bot.send_photo(CHANNEL_ID, photo=post_data["photo_id"],
                                             caption=post_data["text"], parse_mode="Markdown")
                else:
                    await ctx.bot.send_message(CHANNEL_ID, text=post_data["text"], parse_mode="Markdown")
                schedule = ctx.bot_data.setdefault("schedule", [])
                schedule.append(post_data["schedule_entry"])
                ctx.bot_data["schedule"] = schedule[-20:]
            elif post_data["type"] == "review":
                caption = (f"🌊 *Впечатления от прогулки*\n\n"
                           f"💬 {_escape_md(post_data['comment'])}\n\n"
                           f"Отзыв оставил: {_escape_md(post_data['author'])}\n\n"
                           f"#сап #отзыв #впечатления")
                await _send_media_group(ctx, CHANNEL_ID, post_data["media"], caption=caption)
        except Exception as e:
            await q.edit_message_text(f"⚠️ Ошибка при публикации:\n{e}")
            return

        label = "Анонс" if post_data["type"] == "announce" else "Отзыв"
        author_display = post_data.get("author_display", f"id:{user_id}")
        pts = 2 if post_data["type"] == "review" else 1

        # ── Автоначисление очков (правится вручную через /addpoints и /fixname) ──
        rating_key = author_display.lstrip("@").strip()
        if rating_key and not rating_key.startswith("id:"):
            ratings = _ratings(ctx.bot_data)
            ratings.setdefault(rating_key, {"points": 0})
            ratings[rating_key]["points"] += pts
            total = ratings[rating_key]["points"]
            points_line = (f"⭐ Начислено +{pts} {_pts_word(pts)} → "
                           f"@{rating_key}: {total} {_pts_word(total)} ({_get_rank(total)})")
            user_bonus = (f"\n\n⭐ +{pts} {_pts_word(pts)} в рейтинг — "
                          f"теперь у тебя {total} ({_get_rank(total)})")
        else:
            points_line = (f"⚠️ Очки не начислены автоматически: у автора нет @username.\n"
                           f"Вручную — /addpoints НИК {pts}")
            user_bonus = ""

        await q.edit_message_text(
            f"✅ {label} опубликован!\n\n"
            f"👤 Автор: {author_display}\n"
            f"{points_line}"
        )
        try:
            await ctx.bot.send_message(
                user_id,
                f"🎉 *Твой пост одобрен и опубликован в канале!*{user_bonus}",
                parse_mode="Markdown")
        except Exception: pass

    elif action == "reject":
        label = "Анонс" if post_data["type"] == "announce" else "Отзыв"
        await q.edit_message_text(f"❌ {label} отклонён.")
        try:
            await ctx.bot.send_message(user_id,
                "😔 *К сожалению, твой пост отклонён.*\nПопробуй снова: /start или /review",
                parse_mode="Markdown")
        except Exception: pass


# ══════════════════════════════════════════════════════
#  РАСПИСАНИЕ
# ══════════════════════════════════════════════════════

async def schedule_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    entries = ctx.bot_data.get("schedule", [])
    if not entries:
        await update.message.reply_text(
            "📭 *Ближайших прогулок пока нет.*\n\nСоздай анонс через /start 🏄‍♂️",
            parse_mode="Markdown")
        return
    lines = ["🗓 *Ближайшие САП-прогулки:*\n"]
    for i, e in enumerate(entries, 1):
        lines.append(f"*{i}. {_escape_md(e['date'])}*\n"
                     f"⏰ {_escape_md(e['time'])}  🎯 {_escape_md(e['level'])}\n"
                     f"📍 {_escape_md(e['location'])}\n"
                     f"👤 {_escape_md(e['contact'])}\n")
    lines.append("_Подробности — в канале._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════════════
#  ПОГОДА
# ══════════════════════════════════════════════════════

async def weather(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Загружаю прогноз для острова Русский...")
    try:
        days = await _fetch_all_weather()
    except Exception as e:
        logger.error(f"Weather: {e}")
        await msg.edit_text("⚠️ Не удалось получить данные. Попробуй позже.")
        return
    lines = ["🌊 *Прогноз для острова Русский*\n" + "━"*16]
    for i, d in enumerate(days):
        wind, wave = d["wind_speed"], d["wave_height"]
        water = f"🌡 Вода: +{d['water_temp']}°C\n" if d.get("water_temp") else ""
        swell = (f"〰️ Свелл: {d['swell_height']} м, период {int(d['swell_period'])} с\n"
                 if d.get("swell_height") and d.get("swell_period") else "")
        hum  = f" | 💧 {d['humidity']}%" if d.get("humidity") else ""
        pres = f" | 🌬 {d['pressure']} гПа" if d.get("pressure") else ""
        prob = f" (вероятность {d['rain_prob']}%)" if d.get("rain_prob") else ""
        rain = f"☔ Осадки: {d['precip']} мм{prob}\n" if d["precip"] > 0.1 else f"☔ Без осадков{prob}\n"
        lines.append(
            f"\n📅 *{_date_label(d['date'])}* {_wmo_icon(d['wmo'])}\n"
            f"🌡 Воздух: +{d['t_min']}°...+{d['t_max']}°C{hum}{pres}\n"
            f"{water}💨 Ветер: {_deg_to_compass(d['wind_dir'])}, {wind} м/с "
            f"(порывы {d['wind_gusts']} м/с) {_wind_dot(wind)}\n"
            f"🌊 Волна: {wave} м, период {d['wave_period']} с {_wave_dot(wave)}\n"
            f"{swell}{rain}\n{_sup_recommendations(d)}"
        )
        if i == 0: lines.append("\n\n" + "━"*16)
    lines.append(f"\n\n_Данные: {' + '.join(days[0]['sources']) if days else 'Open-Meteo'}_")
    lines.append("_⚠️ Прогноз приблизительный. Перед выходом проверяйте актуальную погоду._")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌬 Открыть на Windy", url=WINDY_URL)]])
    await msg.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)


# ══════════════════════════════════════════════════════
#  РЕЙТИНГ — команды
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
    medals   = ["🥇","🥈","🥉"]
    lines    = [f"🏆 *Рейтинг сезона {year}*\n"]
    for i, (username, data) in enumerate(sorted_r, 1):
        pts   = data["points"]
        medal = medals[i-1] if i <= 3 else f"{i}."
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
    """Только для администратора. /addpoints username 5 или /addpoints username -2"""
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

async def fixname(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Только админ. Перенести очки с одной подписи на другую (слияние/переименование).
    /fixname Максим maximvk — очки с 'Максим' уйдут к 'maximvk', старый ключ удалится."""
    if update.effective_user.id != ADMIN_ID:
        return
    args = ctx.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "✏️ *Исправить подпись в рейтинге*\n\n"
            "`/fixname СтароеИмя НовоеИмя`\n\n"
            "_Пример: /fixname Максим maximvk_\n"
            "_Старый ключ удалится, очки сложатся с новым._\n\n"
            "_Весь список подписей — /addpoints без аргументов._",
            parse_mode="Markdown")
        return
    old = args[0].lstrip("@")
    new = args[1].lstrip("@")
    ratings = _ratings(ctx.bot_data)
    if old == new:
        await update.message.reply_text("⚠️ Старое и новое имя совпадают.")
        return
    if old not in ratings:
        await update.message.reply_text(
            f"⚠️ Подписи @{_escape_md(old)} нет в рейтинге.\n"
            f"Весь список — /addpoints без аргументов.", parse_mode="Markdown")
        return
    moved = ratings.pop(old)["points"]
    ratings.setdefault(new, {"points": 0})
    ratings[new]["points"] += moved
    total = ratings[new]["points"]
    await update.message.reply_text(
        f"✅ Перенёс {moved} {_pts_word(moved)} с @{_escape_md(old)} на @{_escape_md(new)}.\n"
        f"Теперь у @{_escape_md(new)}: {total} {_pts_word(total)} — {_get_rank(total)}",
        parse_mode="Markdown")

async def backup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показывает текущий рейтинг для резервного копирования."""
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
    if now.month != 12 or now.day != 31: return
    ratings = _ratings(context.bot_data)
    year    = now.year
    if ratings:
        sorted_r = sorted(ratings.items(), key=lambda x: x[1]["points"], reverse=True)
        medals   = ["🥇","🥈","🥉"]
        lines    = [f"🎉 *Итоги сезона {year}!*\n\nНаши лучшие сёрферы года:\n"]
        for i, (username, data) in enumerate(sorted_r[:10], 1):
            pts   = data["points"]
            medal = medals[i-1] if i <= 3 else f"{i}."
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

import random

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
    user_id  = update.effective_user.id
    today    = datetime.now(VLAD_TZ).strftime("%Y-%m-%d")
    spins    = ctx.bot_data.setdefault("spins", {})
    last     = spins.get(str(user_id))

    if last == today:
        await update.message.reply_text(
            "🎰 Ты уже крутил колесо сегодня!\n\n"
            "Возвращайся завтра — колесо ждёт 😄",
        )
        return

    phrase = random.choice(SPIN_PHRASES)
    spins[str(user_id)] = today

    await update.message.reply_text(
        f"🎰 *Колесо фортуны говорит...*\n\n{phrase}",
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════════════════
#  ОКНО НА ВОДУ (/window) — призыв в канал
# ══════════════════════════════════════════════════════

WINDOW_CALLS = [
    "🟢 *Сегодня будет окошко!*\n\nПо ветру и волне намечается просвет с {start} до {end}{place}. Вода зовёт — выходим! 🏄",
    "🌊 *Окно на воду*\n\nВетер и волна обещают присмиреть с {start} до {end}{place}. Кто свободен — хватаем доску и погнали.",
    "🏄 *Ловим погоду!*\n\nСегодня по прогнозу окошко с {start} до {end}{place}. Самое время на воду — встречаемся на старте.",
]

def _norm_time(s: str) -> str:
    s = s.strip()
    return f"{int(s):02d}:00" if s.isdigit() else s

async def window(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Только админ. Зовёт на воду: /window 14 18 [место]
    Постит в канал общий призыв с окном по времени + кнопку на Windy."""
    import random
    if update.effective_user.id != ADMIN_ID:
        return
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "🌊 *Позвать на воду*\n\n"
            "`/window НАЧАЛО КОНЕЦ [место]`\n\n"
            "_Примеры:_\n"
            "`/window 14 18` — окно с 14:00 до 18:00\n"
            "`/window 9:30 12 Новик` — с указанием места\n\n"
            "_Глянь Windy, прикинь окошко — и зови._",
            parse_mode="Markdown")
        return
    start = _norm_time(args[0])
    end   = _norm_time(args[1])
    place = " ".join(args[2:]).strip()
    place_str = f" на {place}" if place else ""

    text = random.choice(WINDOW_CALLS).format(start=start, end=end, place=place_str)
    text += "\n\n#сап #русский"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌬 Проверить на Windy", url=WINDY_URL)]])
    try:
        await ctx.bot.send_message(CHANNEL_ID, text=text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Не ушло в канал:\n{e}")
        return
    await update.message.reply_text(
        f"✅ Призыв опубликован!\nОкно: {start}–{end}{place_str}")


# ══════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════

def main():
    persistence = PicklePersistence(filepath="bot_data.pkl")
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

    announce_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
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

    review_conv = ConversationHandler(
        entry_points=[CommandHandler("review", review_start)],
        states={
            REVIEW_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_review_comment)],
            REVIEW_AUTHOR:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_review_author)],
            REVIEW_MEDIA: [
                MessageHandler(filters.PHOTO | filters.VIDEO, get_review_media),
                CallbackQueryHandler(review_done, pattern="^review_done$"),
            ],
            REVIEW_CONFIRM: [CallbackQueryHandler(confirm_review, pattern="^review_(submit|restart)$")],
        },
        fallbacks=[CommandHandler("review", review_start)],
        allow_reentry=True, per_message=False,
    )

    app.add_handler(announce_conv)
    app.add_handler(review_conv)
    app.add_handler(CommandHandler("schedule", schedule_cmd))
    app.add_handler(CommandHandler("weather",  weather))
    app.add_handler(CommandHandler("top",      top))
    app.add_handler(CommandHandler("rank",     rank))
    app.add_handler(CommandHandler("addpoints", addpoints))
    app.add_handler(CommandHandler("fixname",   fixname))
    app.add_handler(CommandHandler("backup",    backup))
    app.add_handler(CommandHandler("spin",      spin))
    app.add_handler(CommandHandler("window",    window))
    app.add_handler(CallbackQueryHandler(moderate, pattern="^(approve|reject):"))
    app.job_queue.run_daily(year_end_job, time=dtime(23, 59, tzinfo=VLAD_TZ))

    logger.info("🏄 САП-бот запущен.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
