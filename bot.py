"""
🏄 САП-бот для публикации анонсов прогулок в Telegram-канал
============================================================
Установка:  pip install python-telegram-bot
Запуск:     python3 bot.py
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler,
    filters, ContextTypes
)

# ─────────────────────────────────────────────
#  НАСТРОЙКИ  ← заполни эти три строки
# ─────────────────────────────────────────────
BOT_TOKEN  = "8727634438:AAGKhXdxQNUqgMv6EBvVZ1DwVZDSQvzTuAM"
CHANNEL_ID = "@super_sup_vl"
ADMIN_ID   = 32275597
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния диалога
DATE, LOCATION, TIME, DURATION, LEVEL, SPOTS, CONTACT, PHOTO, CONFIRM = range(9)


# ══════════════════════════════════════════════════════
#  НАЧАЛО ДИАЛОГА
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


# ══════════════════════════════════════════════════════
#  СБОР ДАННЫХ
# ══════════════════════════════════════════════════════

async def get_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["date"] = update.message.text.strip()
    await update.message.reply_text(
        "📍 *Место старта?*\n_Пример: Набережная Горького, у моста_",
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
        "👥 *Сколько мест?*\n_Пример: 8 мест или Без ограничений_",
        parse_mode="Markdown"
    )
    return SPOTS


async def get_spots(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["spots"] = update.message.text.strip()
    await update.message.reply_text(
        "📞 *Контакт для записи?*\n_Пример: @username или +7 900 000-00-00_",
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
        await show_preview(q.message, ctx)
        return CONFIRM


async def get_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["photo_id"] = update.message.photo[-1].file_id
    await show_preview(update.message, ctx)
    return CONFIRM


# ══════════════════════════════════════════════════════
#  ПРЕВЬЮ
# ══════════════════════════════════════════════════════

def build_post(d: dict) -> str:
    return (
        f"🏄‍♂️ *САП-ПРОГУЛКА*\n"
        f"{'━' * 16}\n\n"
        f"📅  *Дата:* {d['date']}\n"
        f"⏰  *Сбор:* {d['time']}\n"
        f"🕐  *Длительность:* {d['duration']}\n"
        f"📍  *Место:* {d['location']}\n"
        f"🎯  *Уровень:* {d['level']}\n"
        f"👥  *Мест:* {d['spots']}\n\n"
        f"📞  *Запись:* {d['contact']}\n\n"
        f"#сап #сапсёрфинг #прогулка #paddle #sup"
    )


async def show_preview(message, ctx: ContextTypes.DEFAULT_TYPE):
    text = build_post(ctx.user_data)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Отправить на проверку", callback_data="submit"),
            InlineKeyboardButton("✏️ Начать заново",         callback_data="restart"),
        ]
    ])
    await message.reply_text(
        f"*Вот твой анонс:*\n\n{text}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "restart":
        await q.edit_message_text("↩️ Начинаем заново. Напиши /start")
        return ConversationHandler.END

    d = ctx.user_data
    post_text = build_post(d)
    photo_id  = d.get("photo_id")
    author    = q.from_user
    author_info = f"@{author.username}" if author.username else f"id:{author.id}"

    # Сохраняем в bot_data — не теряется между хендлерами
    if "pending" not in ctx.bot_data:
        ctx.bot_data["pending"] = {}
    ctx.bot_data["pending"][str(author.id)] = {
        "text":     post_text,
        "photo_id": photo_id,
    }

    mod_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:{author.id}"),
            InlineKeyboardButton("❌ Отклонить",    callback_data=f"reject:{author.id}"),
        ]
    ])

    # Фото отправляем отдельно — без кнопок
    if photo_id:
        await ctx.bot.send_photo(ADMIN_ID, photo=photo_id)

    # Текст и кнопки — всегда отдельным текстовым сообщением
    await ctx.bot.send_message(
        ADMIN_ID,
        text=(
            f"📬 *Новый анонс от* {author_info}\n"
            f"{'─' * 28}\n\n"
            f"{post_text}\n\n"
            f"{'─' * 28}\n"
            f"Опубликовать в канал?"
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
#  МОДЕРАЦИЯ — кнопки у администратора
# ══════════════════════════════════════════════════════

async def moderate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_ID:
        await q.answer("⛔ Только администратор может это сделать.", show_alert=True)
        return

    action, user_id_str = q.data.split(":")
    pending   = ctx.bot_data.get("pending", {})
    post_data = pending.pop(user_id_str, None)

    if not post_data:
        await q.edit_message_text(
            "⚠️ Данные анонса не найдены. Попроси автора отправить анонс повторно."
        )
        return

    post_text = post_data["text"]
    photo_id  = post_data["photo_id"]

    if action == "approve":
        try:
            # Публикуем в канал: с фото или без
            if photo_id:
                await ctx.bot.send_photo(
                    CHANNEL_ID,
                    photo=photo_id,
                    caption=post_text,
                    parse_mode="Markdown"
                )
            else:
                await ctx.bot.send_message(
                    CHANNEL_ID,
                    text=post_text,
                    parse_mode="Markdown"
                )
        except Exception as e:
            await q.edit_message_text(f"⚠️ Ошибка при публикации в канал:\n{e}")
            return

        # Кнопки всегда в текстовом сообщении — edit_message_text всегда работает
        await q.edit_message_text(
            f"✅ Опубликовано в канале!\n\n{post_text}",
            parse_mode="Markdown"
        )
        try:
            await ctx.bot.send_message(
                int(user_id_str),
                "🎉 *Твой анонс одобрен и опубликован в канале!*",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    elif action == "reject":
        await q.edit_message_text(
            f"❌ Анонс отклонён.\n\n{post_text}",
            parse_mode="Markdown"
        )
        try:
            await ctx.bot.send_message(
                int(user_id_str),
                "😔 *К сожалению, твой анонс отклонён организатором.*\n"
                "Хочешь попробовать снова? Напиши /start",
                parse_mode="Markdown"
            )
        except Exception:
            pass


# ══════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            DATE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date)],
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_location)],
            TIME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
            DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_duration)],
            LEVEL:    [CallbackQueryHandler(get_level, pattern="^level_")],
            SPOTS:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_spots)],
            CONTACT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_contact)],
            PHOTO: [
                CallbackQueryHandler(photo_choice, pattern="^(add_photo|skip_photo)$"),
                MessageHandler(filters.PHOTO, get_photo),
            ],
            CONFIRM: [CallbackQueryHandler(confirm, pattern="^(submit|restart)$")],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(moderate, pattern="^(approve|reject):"))

    logger.info("🏄 САП-бот запущен. Ctrl+C для остановки.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
