"""
/setimage [name] — Admin uploads image for breathing style, demon art, technique, enemy, or Hashira
Bot saves the file_id and uses it when the asset is rendered
"""
from telegram import Update
from telegram.ext import ContextTypes
from utils.database import col
from config import BREATHING_STYLES, DEMON_ARTS, TECHNIQUES, SLAYER_ENEMIES, DEMON_ENEMIES, REGION_ENEMIES


async def setimage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.admin import has_admin_access
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    # Must have a photo AND a caption or args
    reply = update.message.reply_to_message
    file_id = None
    if reply:
        if reply.photo:
            file_id = reply.photo[-1].file_id
        elif reply.animation:
            file_id = reply.animation.file_id
        elif reply.document and (reply.document.mime_type or "").startswith("image/"):
            file_id = reply.document.file_id

    if not file_id and update.message.photo:
        file_id = update.message.photo[-1].file_id

    if not file_id and not context.args:
        await update.message.reply_text(
            "📸 *SET ASSET IMAGE*\n\n"
            "*Method 1 — Send/Reply to Photo or GIF:*\n"
            "Reply to any photo/GIF with:\n"
            "`/setimage Water Breathing`\n\n"
            "*Method 2 — Direct Telegram file\\_id:*\n"
            "Forward any image, tap it → `Copy file_id`, then:\n"
            "`/setimage Water Breathing AgACAgI...`\n\n"
            "*Method 3 — Web URL:*\n"
            "`/setimage Giyu Tomioka https://example.com/giyu.jpg`\n\n"
            "💡 _Supported targets: breathing styles, demon arts, forms, enemies, Hashiras._",
            parse_mode='Markdown'
        )
        return

    args = context.args or []
    url     = None
    file_id_from_arg = None

    # Detect: last arg is a URL
    if args and args[-1].startswith('http'):
        url        = args[-1]
        style_name = ' '.join(args[:-1])
    # Detect: last arg is a Telegram file_id (long base64-like string, no spaces, len > 30)
    elif args and len(args[-1]) > 30 and args[-1].replace('-', '').replace('_', '').isalnum():
        file_id_from_arg = args[-1]
        style_name       = ' '.join(args[:-1])
    else:
        style_name = ' '.join(args)

    # Prefer explicit file_id over photo in message
    if file_id_from_arg:
        file_id = file_id_from_arg

    if not style_name:
        await update.message.reply_text("❌ Provide a target name. Example: `/setimage Water Breathing`", parse_mode='Markdown')
        return

    # Build match pools
    all_styles = BREATHING_STYLES + DEMON_ARTS
    style_names = {s["name"]: s for s in all_styles}

    tech_names = {}
    for t_list in TECHNIQUES.values():
        for t in t_list:
            tech_names[t["name"]] = t

    enemy_names = {}
    for e in SLAYER_ENEMIES + DEMON_ENEMIES:
        enemy_names[e["name"]] = e
    for reg in REGION_ENEMIES.values():
        for e in reg.get("enemies", []):
            enemy_names[e["name"]] = e

    hashiras = ["giyu tomioka", "shinobu kocho", "kyojuro rengoku", "tengen uzui", "muichiro tokito", "mitsuri kanroji", "gyomei himejima", "obanai iguro", "sanemi shinazugawa"]
    hashira_names = {h.title(): h for h in hashiras}

    # Merge everything for autocomplete
    search_pool = {}
    search_pool.update({k.lower(): k for k in style_names.keys()})
    search_pool.update({k.lower(): k for k in tech_names.keys()})
    search_pool.update({k.lower(): k for k in enemy_names.keys()})
    search_pool.update({k.lower(): k for k in hashira_names.keys()})

    normalized_name = style_name.strip()
    query_lower = normalized_name.lower()
    if query_lower in search_pool:
        normalized_name = search_pool[query_lower]
    else:
        # Try partial match
        partial = next((orig for low, orig in search_pool.items() if query_lower in low), None)
        if partial:
            normalized_name = partial

    if not file_id and not url:
        await update.message.reply_text("❌ Send a photo, reply to one, or provide an image URL.")
        return

    # Save to DB
    update_data = {
        "style_name": normalized_name,
        "set_by": user_id
    }
    if file_id:
        update_data["file_id"] = file_id
    if url:
        update_data["url"] = url

    col("style_images").update_one(
        {"style_name": normalized_name},
        {"$set": update_data},
        upsert=True
    )

    await update.message.reply_text(
        f"✅ *Image set successfully!*\n\n"
        f"👤 *Target:* `{normalized_name}`\n"
        f"🖼️ *Source:* {'📸 Photo (file_id stored)' if file_id else f'🔗 URL: {url}'}\n\n"
        f"_The bot will now use this image when displaying this asset._",
        parse_mode='Markdown'
    )


async def listimages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: see which assets have custom images set."""
    from handlers.admin import has_admin_access
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return

    images = list(col("style_images").find())
    if not images:
        await update.message.reply_text("📭 No custom asset images set yet.")
        return

    lines = ["📸 *CUSTOM ASSET IMAGES*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    for img in images:
        name = img.get("style_name", "?")
        source = "📸 Photo" if img.get("file_id") else "🔗 URL"
        lines.append(f"• `{name}` — {source}")

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


def get_style_image(style_name):
    """Returns (file_id_or_url, type) or (None, None)"""
    doc = col("style_images").find_one({"style_name": style_name})
    if not doc:
        return None, None
    if doc.get('file_id'):
        return doc['file_id'], 'file_id'
    if doc.get('url'):
        return doc['url'], 'url'
    return None, None
