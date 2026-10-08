def generate_ui_demo():
    enemy = {"name": "Lesser Demon", "hp": 450, "max_hp": 500}
    player = {"name": "Tanjiro", "hp": 1000, "max_hp": 1000, "sta": 100, "max_sta": 100}

    def bar(current, max_val, color_emoji, bg_emoji="⬛", length=10):
        if max_val <= 0: return bg_emoji * length
        filled = int(length * max(0.0, min(1.0, current / max_val)))
        return f"[{color_emoji * filled}{bg_emoji * (length - filled)}]"

    enemy_bar = bar(enemy['hp'], enemy['max_hp'], "🟥")
    player_hp_bar = bar(player['hp'], player['max_hp'], "🟩")
    player_sta_bar = bar(player['sta'], player['max_sta'], "🟦")

    ui = f"""
╭──────────────────────╮
│     ⚔️ BATTLE ⚔️      │
╰──────────────────────╯

👹 *{enemy['name']}*
❤️ HP: {enemy['hp']} / {enemy['max_hp']}
{enemy_bar}

          🆚

🗡️ *『{player['name']}』*
❤️ HP: {player['hp']} / {player['max_hp']}
{player_hp_bar}
🌀 STA: {player['sta']} / {player['max_sta']}
{player_sta_bar}

────────────────────────
📜 *Combat Log:*
› 🌊 *Water Surface Slash* dealt 50 damage!
────────────────────────
"""
    print(ui)

generate_ui_demo()
