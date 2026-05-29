import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler

# Predefined mission pools per tier
MISSION_POOLS = {
    "high": [
        "Defeat the Ultra Demon Lord",
        "Conquer the Dragon's Lair",
        "Complete the Slayer Tournament",
        "Rescue the Emperor",
        "Retrieve the Sacred Relic",
    ],
    "medium": [
        "Clear the Haunted Forest",
        "Collect 50 Demon Hearts",
        "Win 3 arena battles",
        "Discover the Hidden Shrine",
        "Help a village against bandits",
    ],
    "low": [
        "Gather 10 herbs",
        "Explore a new region",
        "Trade with a merchant",
        "Complete a daily quest",
        "Visit the training grounds",
    ],
}

# Current missions displayed to users – refreshed daily
CURRENT_MISSIONS = {
    "high": [],
    "medium": [],
    "low": [],
}

def _refresh_missions() -> None:
    """Populate CURRENT_MISSIONS with a random selection from each pool.
    This function is intended to be called by a scheduled job once per day.
    """
    for tier, pool in MISSION_POOLS.items():
        # Choose up to 3 unique missions per tier (or fewer if pool is small)
        count = min(3, len(pool))
        CURRENT_MISSIONS[tier] = random.sample(pool, k=count)

# Initialise missions at module load so the bot has something to show immediately
_refresh_missions()

async def missions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the `/missions` command.
    Shows the current daily missions grouped by tier.
    """
    lines = []
    for tier in ["high", "medium", "low"]:
        lines.append(f"*{tier.title()} Tier Missions:*")
        for mission in CURRENT_MISSIONS.get(tier, []):
            lines.append(f"- {mission}")
        lines.append("")  # blank line between tiers
    message = "\n".join(lines)
    await update.effective_chat.send_message(message, parse_mode="Markdown")

def register_missions(app) -> None:
    """Register the `/missions` command with the Application instance."""
    app.add_handler(CommandHandler('missions', missions_command))

def refresh_missions_job() -> None:
    """Job function for APScheduler – refreshes the daily missions.
    The scheduler runs this at a fixed time (e.g., midnight UTC).
    """
    _refresh_missions()
    # Optionally, you could log the refresh for debugging.
    print("[Missions] Daily missions refreshed.")
