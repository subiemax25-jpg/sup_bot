"""
🏄 САП-бот: анонсы прогулок + отзывы с фото/видео
===================================================
Установка:  pip install python-telegram-bot
Запуск:     python3 bot.py
"""

import logging
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

# ──────────────────────────────────────────────
#  СОСТОЯНИЯ
# ──────────────────────────────────────────────
# Анонс
DATE, LOCATION, TIME, ROUTE, DURATION, LEVEL, CONTACT, PHOTO, CONFIRM = range(9)
# Отзыв
REVIEW_COMMENT, REVIEW_AUTHOR, REVIEW_MEDIA, REVIEW_CONFIRM = range(9, 13)


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
    app.add_handler(CallbackQueryHandler(moderate, pattern="^(approve|reject):"))

    logger.info("🏄 САП-бот запущен. Ctrl+C для остановки.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
