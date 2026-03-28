"""
/setimage [style_name] — Admin uploads image for a breathing style/demon art
Bot saves the file_id and uses it when /breathing or /art is called
"""
from telegram import Update
from telegram.ext import ContextTypes
from utils.database import col
from config import BREATHING_STYLES, DEMON_ARTS


async def setimage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.admin import has_admin_access
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    # Must have a photo AND a caption or args
    if not update.message.photo and not context.args:
        await update.message.reply_text(
            "📸 *SET STYLE IMAGE*\n\n"
            "Send a photo with caption:\n"
            "`/setimage Water Breathing`\n\n"
            "Or use a URL:\n"
            "`/setimage Water Breathing https://example.com/water.jpg`\n\n"
            "_Supported: any breathing style or demon art name_",
            parse_mode='Markdown'
        )
        return

    if not context.args:
        await update.message.reply_text("❌ Provide the style name. Example: `/setimage Water Breathing`", parse_mode='Markdown')
        return

    # Check if URL provided
    args = context.args
    url  = None
    if args and args[-1].startswith('http'):
        url        = args[-1]
        style_name = ' '.join(args[:-1])
    else:
        style_name = ' '.join(args)

    # Validate style name
    all_styles = BREATHING_STYLES + DEMON_ARTS
    style = next((s for s in all_styles if s['name'].lower() == style_name.lower()), None)
    if not style:
        # Try partial match
        style = next((s for s in all_styles if style_name.lower() in s['name'].lower()), None)
    if not style:
        await update.message.reply_text(f"❌ Style not found: *{style_name}*", parse_mode='Markdown')
        return

    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id

    if not file_id and not url:
        await update.message.reply_text("❌ Send a photo or provide a URL.")
        return

    # Save to DB
    update_data = {"style_name": style['name']}
    if file_id:
        update_data["file_id"] = file_id
    if url:
        update_data["url"] = url

    col("style_images").update_one(
        {"style_name": style['name']},
        {"$set": update_data},
        upsert=True
    )

    await update.message.reply_text(
        f"✅ *Image set for {style['name']}*\n\n"
        f"{'📸 Photo uploaded (file_id stored)' if file_id else f'🔗 URL: {url}'}\n\n"
        f"_Players will see this image when using /breathing or /art_",
        parse_mode='Markdown'
    )


async def listimages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: see which styles have images set."""
    from handlers.admin import has_admin_access
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return

    images = list(col("style_images").find())
    all_styles = BREATHING_STYLES + DEMON_ARTS

    lines = ["📸 *STYLE IMAGES*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    set_names = {i['style_name'] for i in images}

    for s in all_styles:
        if s['name'] in set_names:
            img   = next(i for i in images if i['style_name'] == s['name'])
            itype = "📸 Photo" if img.get('file_id') else f"🔗 URL"
            lines.append(f"✅ {s['emoji']} *{s['name']}* — {itype}")
        else:
            lines.append(f"❌ {s['emoji']} *{s['name']}* — No image")

    lines.append(f"\n✅ {len(set_names)}/{len(all_styles)} images set")
    lines.append("💡 `/setimage [name]` to add one")
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
