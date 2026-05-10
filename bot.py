"""
🏄 САП-бот: анонсы прогулок + отзывы с фото/видео
===================================================
Установка:  pip install python-telegram-bot
Запуск:     python3 bot.py
"""

import logging
import asyncio
import aiohttp
from datetime import date, datetime, timedelta, timezone
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto, InputMediaVideo
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler,
    filters, ContextTypes
)

# ─────────────────────────────────────────────
#  НАСТРОЙКИ  ← заполни эти строки
# ─────────────────────────────────────────────
BOT_TOKEN  = "8727634438:AAGKhXdxQNUqgMv6EBvVZ1DwVZDSQvzTuAM"
CHANNEL_ID = "@super_sup_vl"
ADMIN_ID   = 32275597
STORMGLASS_KEY  = "b19dc4ac-4c46-11f1-81a8-0242ac120004-b19dc54c-4c46-11f1-81a8-0242ac120004"   
OWM_KEY         = "973c9e2cd5ba8533bb501d0ecf2fd070"
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  СОСТОЯНИЯ
# ──────────────────────────────────────────────
# Анонс
DATE, LOCATION, TIME, ROUTE, DURATION, LEVEL, CONTACT, PHOTO, CONFIRM = range(9)
# Отзыв
REVIEW_COMMENT, REVIEW_AUTHOR, REVIEW_MEDIA, REVIEW_CONFIRM = range(9, 13)

# ──────────────────────────────────────────────
#  ПОГОДА — константы и вспомогательные функции
# ──────────────────────────────────────────────
SUP_LAT = 42.948
SUP_LON = 131.941
VLAD_TZ = timezone(timedelta(hours=10))

MONTHS_RU = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]

def _deg_to_compass(deg: float) -> str:
    dirs = ["С","ССВ","СВ","ВСВ","В","ВЮВ","ЮВ","ЮЮВ",
            "Ю","ЮЮЗ","ЮЗ","ЗЮЗ","З","ЗСЗ","СЗ","ССЗ"]
    return dirs[round(deg / 22.5) % 16]

def _wind_dot(s: float) -> str:
    return "🟢" if s < 4 else "🟡" if s < 7 else "🟠" if s < 11 else "🔴"

def _wave_dot(h: float) -> str:
    return "🟢" if h < 0.3 else "🟡" if h < 0.6 else "🟠" if h < 1.0 else "🔴"

def _verdict(wind: float, wave: float) -> str:
    if wind >= 12 or wave >= 1.0: return "🔴 Выход не рекомендуется"
    if wind >= 8  or wave >= 0.6: return "🟠 Сложные условия — только опытным"
    if wind >= 5  or wave >= 0.3: return "🟡 Приемлемо — выбирай укрытое место"
    return "🟢 Отлично — можно идти везде"

def _location_advice(wind_dir: float, wind: float, wave: float) -> str:
    if wind < 4 and wave < 0.3:
        return "Штиль 🌊 Любая точка острова — иди куда хочешь!"
    if wind >= 12:
        return "Слишком сильный ветер. Только закрытые бухты: Новик или Аякс."
    if wind_dir < 22.5 or wind_dir >= 337.5: spot = "бухта Новик (южная сторона)"
    elif wind_dir < 67.5:  spot = "западная сторона — Амурский залив"
    elif wind_dir < 112.5: spot = "западная сторона — Амурский залив"
    elif wind_dir < 157.5: spot = "бухта Аякс (северная сторона)"
    elif wind_dir < 202.5: spot = "северный берег, ближе к Владивостоку"
    elif wind_dir < 247.5: spot = "восточная сторона — Уссурийский залив"
    elif wind_dir < 292.5: spot = "восточная сторона — Уссурийский залив"
    else:                  spot = "юго-восточная сторона острова"
    return f"Лучшее место: {spot} — там будет укрытие от ветра."

def _wmo_icon(code: int) -> str:
    if code == 0:  return "☀️"
    if code <= 3:  return "⛅"
    if code <= 48: return "🌫"
    if code <= 67: return "🌧"
    if code <= 77: return "❄️"
    if code <= 82: return "🌦"
    if code <= 86: return "🌨"
    return "⛈"

def _date_label(iso: str) -> str:
    d = date.fromisoformat(iso)
    today = date.today()
    if d == today:                       prefix = "Сегодня"
    elif d == today + timedelta(days=1): prefix = "Завтра"
    else:                                prefix = ""
    return f"{prefix}, {d.day} {MONTHS_RU[d.month]}" if prefix else f"{d.day} {MONTHS_RU[d.month]}"

def _sg_val(sources: dict) -> float | None:
    """Извлекает значение из словаря источников Stormglass."""
    if not sources:
        return None
    if "sg" in sources and sources["sg"] is not None:
        return sources["sg"]
    vals = [v for v in sources.values() if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None

async def _fetch_open_meteo(session: aiohttp.ClientSession) -> dict:
    """Open-Meteo: ветер, погода, осадки + морские волны."""
    timeout = aiohttp.ClientTimeout(total=10)
    w = await (await session.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": SUP_LAT, "longitude": SUP_LON,
            "daily": "weathercode,temperature_2m_max,temperature_2m_min,"
                     "windspeed_10m_max,windgusts_10m_max,winddirection_10m_dominant,precipitation_sum",
            "wind_speed_unit": "ms", "timezone": "Asia/Vladivostok", "forecast_days": 2,
        }, timeout=timeout
    )).json()
    m = await (await session.get(
        "https://marine-api.open-meteo.com/v1/marine",
        params={
            "latitude": SUP_LAT, "longitude": SUP_LON,
            "daily": "wave_height_max,wave_direction_dominant,wave_period_max",
            "timezone": "Asia/Vladivostok", "forecast_days": 2,
        }, timeout=timeout
    )).json()
    return {"weather": w["daily"], "marine": m["daily"]}

async def _fetch_stormglass(session: aiohttp.ClientSession, key: str) -> list[dict] | None:
    """Stormglass: детальные морские данные — волна, свелл, температура воды."""
    if not key:
        return None
    try:
        now   = datetime.now(VLAD_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        start = int(now.timestamp())
        end   = int((now + timedelta(days=2)).timestamp())
        resp  = await (await session.get(
            "https://api.stormglass.io/v2/weather/point",
            params={
                "lat": SUP_LAT, "lng": SUP_LON, "start": start, "end": end,
                "params": "waveHeight,wavePeriod,waveDirection,"
                          "swellHeight,swellPeriod,swellDirection,"
                          "windSpeed,windDirection,waterTemperature",
            },
            headers={"Authorization": key},
            timeout=aiohttp.ClientTimeout(total=15),
        )).json()

        # Группируем по дате (Владивосток UTC+10)
        days: dict[str, dict] = {}
        for h in resp.get("hours", []):
            dt    = datetime.fromisoformat(h["time"].replace("Z", "+00:00")).astimezone(VLAD_TZ)
            day   = dt.strftime("%Y-%m-%d")
            entry = days.setdefault(day, {
                "wave_heights": [], "wave_periods": [],
                "swell_heights": [], "swell_periods": [],
                "wind_speeds": [], "wind_dirs": [], "water_temps": [],
            })
            for field, key_name in [
                ("waveHeight", "wave_heights"), ("wavePeriod", "wave_periods"),
                ("swellHeight", "swell_heights"), ("swellPeriod", "swell_periods"),
                ("windSpeed", "wind_speeds"), ("windDirection", "wind_dirs"),
                ("waterTemperature", "water_temps"),
            ]:
                val = _sg_val(h.get(field, {}))
                if val is not None:
                    entry[key_name].append(val)

        result = []
        for day_iso in sorted(days)[:2]:
            e = days[day_iso]
            def mx(lst): return round(max(lst), 1) if lst else None
            def avg(lst): return round(sum(lst) / len(lst), 1) if lst else None
            result.append({
                "date":        day_iso,
                "wave_height": mx(e["wave_heights"]),
                "wave_period": avg(e["wave_periods"]),
                "swell_height": mx(e["swell_heights"]),
                "swell_period": avg(e["swell_periods"]),
                "water_temp":  avg(e["water_temps"]),
                "wind_speed":  mx(e["wind_speeds"]),
            })
        return result
    except Exception as ex:
        logger.warning(f"Stormglass error: {ex}")
        return None

async def _fetch_owm(session: aiohttp.ClientSession, key: str) -> list[dict] | None:
    """OpenWeatherMap: температура, влажность, давление, вероятность дождя."""
    if not key:
        return None
    try:
        resp = await (await session.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={"lat": SUP_LAT, "lon": SUP_LON, "appid": key,
                    "units": "metric", "cnt": 16},
            timeout=aiohttp.ClientTimeout(total=10),
        )).json()

        days: dict[str, dict] = {}
        for item in resp.get("list", []):
            dt  = datetime.fromtimestamp(item["dt"], tz=VLAD_TZ)
            day = dt.strftime("%Y-%m-%d")
            e   = days.setdefault(day, {
                "temps": [], "humidity": [], "pressure": [], "pop": [], "icons": [],
            })
            e["temps"].append(item["main"]["temp"])
            e["humidity"].append(item["main"]["humidity"])
            e["pressure"].append(item["main"]["pressure"])
            e["pop"].append(item.get("pop", 0))
            e["icons"].append(item["weather"][0]["description"])

        result = []
        for day_iso in sorted(days)[:2]:
            e = days[day_iso]
            result.append({
                "date":     day_iso,
                "humidity": round(sum(e["humidity"]) / len(e["humidity"])),
                "pressure": round(sum(e["pressure"]) / len(e["pressure"])),
                "rain_prob": round(max(e["pop"]) * 100),
            })
        return result
    except Exception as ex:
        logger.warning(f"OWM error: {ex}")
        return None

async def _fetch_all_weather() -> list[dict]:
    """Собирает данные из всех источников и возвращает прогноз на 2 дня."""
    async with aiohttp.ClientSession() as session:
        om_data, sg_data, owm_data = await asyncio.gather(
            _fetch_open_meteo(session),
            _fetch_stormglass(session, STORMGLASS_KEY),
            _fetch_owm(session, OWM_KEY),
            return_exceptions=True,
        )

    wd = om_data["weather"] if isinstance(om_data, dict) else {}
    md = om_data["marine"]  if isinstance(om_data, dict) else {}
    sg = sg_data  if isinstance(sg_data,  list) else []
    ow = owm_data if isinstance(owm_data, list) else []

    days = []
    for i in range(2):
        sg_day  = sg[i]  if i < len(sg)  else {}
        ow_day  = ow[i]  if i < len(ow)  else {}

        wave_h  = (sg_day.get("wave_height") or
                   (round(md["wave_height_max"][i], 1) if md and md.get("wave_height_max") else 0))
        wave_p  = (sg_day.get("wave_period") or
                   (round(md["wave_period_max"][i], 0) if md and md.get("wave_period_max") else 0))

        sources = ["Open-Meteo"]
        if sg_day: sources.append("Stormglass")
        if ow_day: sources.append("OpenWeatherMap")

        days.append({
            "date":         wd["time"][i] if wd.get("time") else "",
            "wmo":          wd["weathercode"][i] if wd.get("weathercode") else 0,
            "t_min":        round(wd["temperature_2m_min"][i]) if wd.get("temperature_2m_min") else "—",
            "t_max":        round(wd["temperature_2m_max"][i]) if wd.get("temperature_2m_max") else "—",
            "wind_speed":   round(wd["windspeed_10m_max"][i], 1) if wd.get("windspeed_10m_max") else 0,
            "wind_gusts":   round(wd["windgusts_10m_max"][i], 1) if wd.get("windgusts_10m_max") else 0,
            "wind_dir":     wd["winddirection_10m_dominant"][i] if wd.get("winddirection_10m_dominant") else 0,
            "precip":       wd["precipitation_sum"][i] or 0 if wd.get("precipitation_sum") else 0,
            "wave_height":  wave_h,
            "wave_period":  int(wave_p),
            "swell_height": sg_day.get("swell_height"),
            "swell_period": sg_day.get("swell_period"),
            "water_temp":   sg_day.get("water_temp"),
            "humidity":     ow_day.get("humidity"),
            "pressure":     ow_day.get("pressure"),
            "rain_prob":    ow_day.get("rain_prob"),
            "sources":      sources,
        })
    return days


# ══════════════════════════════════════════════════════
#  АНОНС — сбор данных
# ══════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "🏄‍♂️ *Привет! Я помогу составить анонс САП-прогулки.*\n\n"
        "Отвечай на вопросы — я сформирую пост и отправлю его на проверку организатору.\n\n"
        "📅 *Дата прогулки?*\n_Пример: суббота, 14 июня_",
        parse_mode="Markdown"
    )
    return DATE


async def get_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["date"] = update.message.text.strip()
    await update.message.reply_text(
        "📍 *Место сбора?*\n_Пример: Набережная Горького, у моста (ссылка 2Gis)_",
        parse_mode="Markdown"
    )
    return LOCATION


async def get_location(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["location"] = update.message.text.strip()
    await update.message.reply_text(
        "⏰ *Время сбора?*\n_Пример: 10:00_",
        parse_mode="Markdown"
    )
    return TIME


async def get_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["time"] = update.message.text.strip()
    await update.message.reply_text(
        "🗺 *Маршрут прогулки?*\n_Пример: вдоль набережной до острова и обратно (Без картинок)_",
        parse_mode="Markdown"
    )
    return ROUTE


async def get_route(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["route"] = update.message.text.strip()
    await update.message.reply_text(
        "🕐 *Продолжительность прогулки?*\n_Пример: 2 часа_",
        parse_mode="Markdown"
    )
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
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
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
        "👤 *Кто предложил прогулку?*\n_Пример: @username (телефон +7)_",
        parse_mode="Markdown"
    )
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
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PHOTO


async def photo_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "add_photo":
        await q.edit_message_text("📷 Отправь фото для анонса:")
        return PHOTO
    else:
        ctx.user_data["photo_id"] = None
        await show_announce_preview(q.message, ctx)
        return CONFIRM


async def get_announce_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["photo_id"] = update.message.photo[-1].file_id
    await show_announce_preview(update.message, ctx)
    return CONFIRM


def build_post(d: dict) -> str:
    return (
        f"🏄‍♂️ *САП-ПРОГУЛКА*\n"
        f"{'━' * 16}\n\n"
        f"📅  *Дата:* {d['date']}\n"
        f"⏰  *Сбор:* {d['time']}\n"
        f"🕐  *Длительность:* {d['duration']}\n"
        f"📍  *Место сбора:* {d['location']}\n"
        f"🗺  *Маршрут:* {d['route']}\n"
        f"🎯  *Уровень:* {d['level']}\n\n"
        f"👤  *Предложил:* {d['contact']}\n\n"
        f"#сап #сапсёрфинг #прогулка #paddle #sup"
    )


async def show_announce_preview(message, ctx: ContextTypes.DEFAULT_TYPE):
    text = build_post(ctx.user_data)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Отправить на проверку", callback_data="announce_submit"),
            InlineKeyboardButton("✏️ Начать заново",         callback_data="announce_restart"),
        ]
    ])
    await message.reply_text(
        f"*Вот твой анонс:*\n\n{text}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def confirm_announce(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "announce_restart":
        await q.edit_message_text("↩️ Начинаем заново. Напиши /start")
        return ConversationHandler.END

    d         = ctx.user_data
    post_text = build_post(d)
    photo_id  = d.get("photo_id")
    author    = q.from_user
    author_info = f"@{author.username}" if author.username else f"id:{author.id}"

    if "pending" not in ctx.bot_data:
        ctx.bot_data["pending"] = {}
    ctx.bot_data["pending"][f"announce_{author.id}"] = {
        "text":     post_text,
        "photo_id": photo_id,
        "type":     "announce",
        "schedule_entry": {
            "date":     d.get("date", ""),
            "time":     d.get("time", ""),
            "location": d.get("location", ""),
            "route":    d.get("route", ""),
            "duration": d.get("duration", ""),
            "level":    d.get("level", ""),
            "contact":  d.get("contact", ""),
        },
    }

    mod_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:announce_{author.id}"),
            InlineKeyboardButton("❌ Отклонить",    callback_data=f"reject:announce_{author.id}"),
        ]
    ])

    if photo_id:
        await ctx.bot.send_photo(ADMIN_ID, photo=photo_id)

    await ctx.bot.send_message(
        ADMIN_ID,
        text=(
            f"📬 *Новый анонс от* {author_info}\n"
            f"{'─' * 28}\n\n{post_text}\n\n"
            f"{'─' * 28}\nОпубликовать в канал?"
        ),
        parse_mode="Markdown",
        reply_markup=mod_keyboard
    )

    await q.edit_message_text(
        "⏳ *Анонс отправлен на проверку организатору.*\n"
        "Как только он одобрит — пост появится в канале. Спасибо! 🙌",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════════════
#  ОТЗЫВ — сбор данных
# ══════════════════════════════════════════════════════

async def review_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["review_media"] = []
    await update.message.reply_text(
        "🌊 *Поделись впечатлениями о прогулке!*\n\n"
        "✍️ *Напиши комментарий или отзыв:*\n"
        "_Пример: Отличная прогулка! Погода была супер, виды потрясающие._",
        parse_mode="Markdown"
    )
    return REVIEW_COMMENT


async def get_review_comment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["review_comment"] = update.message.text.strip()
    await update.message.reply_text(
        "👤 *Как тебя подписать?*\n"
        "_Напиши своё имя или @username_\n"
        "_Пример: Максим или @maximvk_",
        parse_mode="Markdown"
    )
    return REVIEW_AUTHOR


async def get_review_author(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["review_author"] = update.message.text.strip()
    await update.message.reply_text(
        "📸 *Теперь отправь фото или видео с прогулки.*\n\n"
        "Можно загрузить до 10 файлов — отправляй по одному.\n"
        "Когда закончишь — нажми кнопку *«Готово»*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Готово", callback_data="review_done")]
        ])
    )
    return REVIEW_MEDIA


async def get_review_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    media = ctx.user_data.setdefault("review_media", [])

    if len(media) >= 10:
        await update.message.reply_text(
            "⚠️ Максимум 10 файлов. Нажми *«Готово»* для продолжения.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Готово", callback_data="review_done")]
            ])
        )
        return REVIEW_MEDIA

    if update.message.photo:
        media.append({"type": "photo", "file_id": update.message.photo[-1].file_id})
    elif update.message.video:
        media.append({"type": "video", "file_id": update.message.video.file_id})

    count = len(media)
    await update.message.reply_text(
        f"{'📷' if update.message.photo else '🎥'} Файл {count} принят!\n\n"
        f"Отправь ещё {'(осталось ' + str(10 - count) + ')' if count < 10 else '— достигнут максимум'}.\n"
        f"Когда закончишь — нажми *«Готово»*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Готово", callback_data="review_done")]
        ])
    )
    return REVIEW_MEDIA


async def review_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    comment = ctx.user_data.get("review_comment", "")
    author  = ctx.user_data.get("review_author", "")
    media   = ctx.user_data.get("review_media", [])

    if not media:
        await q.edit_message_text(
            "⚠️ Ты ещё не отправил ни одного фото или видео.\n"
            "Пришли хотя бы один файл, а потом нажми «Готово»."
        )
        return REVIEW_MEDIA

    preview_text = (
        f"*Твой отзыв:*\n\n"
        f"💬 {comment}\n\n"
        f"Отзыв оставил: {author}\n\n"
        f"📎 Файлов: {len(media)}"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Отправить на проверку", callback_data="review_submit"),
            InlineKeyboardButton("✏️ Начать заново",         callback_data="review_restart"),
        ]
    ])
    await q.edit_message_text(preview_text, parse_mode="Markdown", reply_markup=keyboard)
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

    if "pending" not in ctx.bot_data:
        ctx.bot_data["pending"] = {}
    ctx.bot_data["pending"][f"review_{author.id}"] = {
        "type":    "review",
        "comment": comment,
        "media":   media,
        "author":  author_info,
    }

    # Отправляем медиа-альбом администратору
    await _send_media_group(ctx, ADMIN_ID, media, caption=f"💬 {comment}")

    # Кнопки модерации отдельным сообщением
    mod_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:review_{author.id}"),
            InlineKeyboardButton("❌ Отклонить",    callback_data=f"reject:review_{author.id}"),
        ]
    ])
    await ctx.bot.send_message(
        ADMIN_ID,
        text=(
            f"📸 *Новый отзыв от* {author_info}\n"
            f"{'─' * 28}\n\n"
            f"💬 {comment}\n"
            f"📎 Файлов: {len(media)}\n\n"
            f"{'─' * 28}\n"
            f"Опубликовать в канал?"
        ),
        parse_mode="Markdown",
        reply_markup=mod_keyboard
    )

    await q.edit_message_text(
        "⏳ *Отзыв отправлен на проверку организатору.*\n"
        "Как только он одобрит — пост появится в канале. Спасибо! 🙌",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ — отправка альбома
# ══════════════════════════════════════════════════════

async def _send_media_group(ctx, chat_id, media: list, caption: str = ""):
    """Отправляет список фото/видео как альбом. Подпись — на первом файле."""
    if not media:
        return

    input_media = []
    for i, item in enumerate(media):
        cap = caption if i == 0 else None
        if item["type"] == "photo":
            input_media.append(InputMediaPhoto(media=item["file_id"], caption=cap, parse_mode="Markdown"))
        else:
            input_media.append(InputMediaVideo(media=item["file_id"], caption=cap, parse_mode="Markdown"))

    await ctx.bot.send_media_group(chat_id=chat_id, media=input_media)


# ══════════════════════════════════════════════════════
#  МОДЕРАЦИЯ — общий обработчик для анонсов и отзывов
# ══════════════════════════════════════════════════════

async def moderate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_ID:
        await q.answer("⛔ Только администратор может это сделать.", show_alert=True)
        return

    action, key = q.data.split(":", 1)
    pending      = ctx.bot_data.get("pending", {})
    post_data    = pending.pop(key, None)

    if not post_data:
        await q.edit_message_text("⚠️ Данные не найдены. Попроси автора отправить повторно.")
        return

    # Определяем user_id из ключа (announce_123 или review_123)
    user_id = int(key.split("_", 1)[1])

    if action == "approve":
        try:
            if post_data["type"] == "announce":
                if post_data["photo_id"]:
                    await ctx.bot.send_photo(
                        CHANNEL_ID,
                        photo=post_data["photo_id"],
                        caption=post_data["text"],
                        parse_mode="Markdown"
                    )
                else:
                    await ctx.bot.send_message(
                        CHANNEL_ID,
                        text=post_data["text"],
                        parse_mode="Markdown"
                    )
                # Сохраняем в расписание
                if "schedule" not in ctx.bot_data:
                    ctx.bot_data["schedule"] = []
                ctx.bot_data["schedule"].append(post_data["schedule_entry"])
                # Храним не более 20 анонсов
                ctx.bot_data["schedule"] = ctx.bot_data["schedule"][-20:]

            elif post_data["type"] == "review":
                review_caption = (
                    f"🌊 *Впечатления от прогулки*\n\n"
                    f"💬 {post_data['comment']}\n\n"
                    f"Отзыв оставил: {post_data['author']}\n\n"
                    f"#сап #отзыв #впечатления"
                )
                await _send_media_group(ctx, CHANNEL_ID, post_data["media"], caption=review_caption)

        except Exception as e:
            await q.edit_message_text(f"⚠️ Ошибка при публикации:\n{e}")
            return

        label = "Анонс" if post_data["type"] == "announce" else "Отзыв"
        await q.edit_message_text(f"✅ {label} опубликован в канале!")
        try:
            await ctx.bot.send_message(
                user_id,
                "🎉 *Твой пост одобрен и опубликован в канале!*",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    elif action == "reject":
        label = "Анонс" if post_data["type"] == "announce" else "Отзыв"
        await q.edit_message_text(f"❌ {label} отклонён.")
        try:
            await ctx.bot.send_message(
                user_id,
                "😔 *К сожалению, твой пост отклонён организатором.*\n"
                "Хочешь попробовать снова? Напиши /start или /review",
                parse_mode="Markdown"
            )
        except Exception:
            pass


# ══════════════════════════════════════════════════════
#  РАСПИСАНИЕ
# ══════════════════════════════════════════════════════

async def schedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    entries = ctx.bot_data.get("schedule", [])

    if not entries:
        await update.message.reply_text(
            "📭 *Ближайших прогулок пока нет.*\n\n"
            "Создай первый анонс через /start 🏄‍♂️",
            parse_mode="Markdown"
        )
        return

    lines = ["🗓 *Ближайшие САП-прогулки:*\n"]
    for i, e in enumerate(entries, 1):
        lines.append(
            f"*{i}. {e['date']}*\n"
            f"⏰ {e['time']}  🎯 {e['level']}\n"
            f"📍 {e['location']}\n"
            f"👤 {e['contact']}\n"
        )

    lines.append("_Подробности каждой прогулки — в канале._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════════════
#  ПОГОДА
# ══════════════════════════════════════════════════════

async def weather(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Загружаю прогноз для острова Русский...")

    try:
        days = await _fetch_all_weather()
    except Exception as e:
        logger.error(f"Weather error: {e}")
        await msg.edit_text("⚠️ Не удалось получить данные. Попробуй чуть позже.")
        return

    lines = ["🌊 *Прогноз для острова Русский*\n" + "━" * 16]

    for i, d in enumerate(days):
        wind  = d["wind_speed"]
        wave  = d["wave_height"]

        # Строки с доп. данными (только если источник их дал)
        water = f"🌡 Вода: +{d['water_temp']}°C\n" if d.get("water_temp") else ""
        swell = (f"〰️ Свелл: {d['swell_height']} м, период {int(d['swell_period'])} с\n"
                 if d.get("swell_height") and d.get("swell_period") else "")
        hum   = f" | 💧 {d['humidity']}%" if d.get("humidity") else ""
        pres  = f" | 🌬 {d['pressure']} гПа" if d.get("pressure") else ""
        prob  = f" (вероятность {d['rain_prob']}%)" if d.get("rain_prob") else ""
        rain  = f"☔ Осадки: {d['precip']} мм{prob}\n" if d["precip"] > 0.1 else f"☔ Без осадков{prob}\n"

        lines.append(
            f"\n📅 *{_date_label(d['date'])}* {_wmo_icon(d['wmo'])}\n"
            f"🌡 Воздух: +{d['t_min']}°...+{d['t_max']}°C{hum}{pres}\n"
            f"{water}"
            f"💨 Ветер: {_deg_to_compass(d['wind_dir'])}, {wind} м/с "
            f"(порывы {d['wind_gusts']} м/с) {_wind_dot(wind)}\n"
            f"🌊 Волна: {wave} м, период {d['wave_period']} с {_wave_dot(wave)}\n"
            f"{swell}"
            f"{rain}\n"
            f"*{_verdict(wind, wave)}*\n"
            f"📍 {_location_advice(d['wind_dir'], wind, wave)}"
        )
        if i == 0:
            lines.append("\n\n" + "━" * 16)

    sources_str = " + ".join(days[0]["sources"]) if days else "Open-Meteo"
    lines.append(f"\n\n_Данные: {sources_str}_")
    lines.append("_⚠️ Прогноз приблизительный и может меняться. Проверяйте погоду в разных источниках перед выходом на воду._")
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

    # Сохраняем user_id запросившего и уведомляем администратора
    requester = update.effective_user
    requester_info = f"@{requester.username}" if requester.username else f"id:{requester.id}"
    ctx.bot_data["windy_request"] = requester.id

    await ctx.bot.send_message(
        ADMIN_ID,
        f"🗺 *{requester_info}* запросил прогноз погоды.\n\n"
        f"Открой Windy для острова Русский и пришли сюда скриншот — "
        f"я перешлю его с пояснением.",
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════════════════
#  WINDY — пересылка скриншота с пояснением
# ══════════════════════════════════════════════════════

WINDY_EXPLANATION = (
    "🗺 *Скриншот с Windy — остров Русский*\n\n"
    "Как читать этот экран:\n\n"
    "*Карта (анимация частиц):*\n"
    "Движущиеся линии — это ветер. Чем гуще и быстрее — тем сильнее ветер.\n"
    "🔵 Синий/зелёный — слабый ветер, спокойно\n"
    "🟡 Жёлтый — умеренный, стоит выбирать укрытое место\n"
    "🟠 Оранжевый — сильный, только для опытных\n"
    "🔴 Красный — очень сильный, выход опасен\n\n"
    "*Стрелки на карте:*\n"
    "🟢 Зелёная стрелка — направление и сила ветра (м/с)\n"
    "🟠 Оранжевая стрелка — направление и высота свелла (м)\n\n"
    "*Таблица внизу (по столбцам — часы):*\n"
    "↗️ Стрелки — направление ветра\n"
    "м/с — скорость ветра / порывы\n"
    "m (первая строка) — высота волны в метрах\n"
    "m (вторая строка) — высота свелла в метрах\n"
    "s — период свелла в секундах (чем больше — тем мощнее)\n\n"
    "*Для САП-сёрфинга:*\n"
    "✅ Комфортно: ветер до 5 м/с, волна до 0.3 м\n"
    "⚠️ Осторожно: ветер 5-8 м/с, волна 0.3-0.6 м\n"
    "🚫 Не рекомендуется: ветер выше 10 м/с, волна выше 0.6 м"
)

async def handle_windy_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Когда администратор присылает фото — пересылаем его пользователю с пояснением."""
    if update.effective_user.id != ADMIN_ID:
        return

    requester_id = ctx.bot_data.get("windy_request")
    if not requester_id:
        await update.message.reply_text(
            "⚠️ Нет активного запроса погоды. "
            "Скриншот будет переслан как только кто-то запросит /weather."
        )
        return

    photo_id = update.message.photo[-1].file_id

    try:
        await ctx.bot.send_photo(
            requester_id,
            photo=photo_id,
            caption=WINDY_EXPLANATION,
            parse_mode="Markdown"
        )
        ctx.bot_data.pop("windy_request", None)
        await update.message.reply_text("✅ Скриншот Windy отправлен пользователю!")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Не удалось отправить: {e}")


# ══════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Диалог — анонс
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
        allow_reentry=True,
        per_message=False,
    )

    # Диалог — отзыв
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
        allow_reentry=True,
        per_message=False,
    )

    app.add_handler(announce_conv)
    app.add_handler(review_conv)
    app.add_handler(CommandHandler("schedule", schedule))
    app.add_handler(CommandHandler("weather", weather))
    app.add_handler(CallbackQueryHandler(moderate, pattern="^(approve|reject):"))
    app.add_handler(MessageHandler(
        filters.PHOTO & filters.User(ADMIN_ID), handle_windy_photo
    ))

    logger.info("🏄 САП-бот запущен. Ctrl+C для остановки.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
