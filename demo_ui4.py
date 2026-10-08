def generate_ui_demo4():
    def bar(current, max_val, color_emoji, bg_emoji="⬛", length=10):
        if max_val <= 0: return bg_emoji * length
        filled = int(length * max(0.0, min(1.0, current / max_val)))
        return f"[{color_emoji * filled}{bg_emoji * (length - filled)}]"

    hp_bar = bar(200, 240, "🟥")
    p_hp_bar = bar(270, 270, "🟩")

    print(f"""
╭──────────────────────────╮
│ 👹 *HUNGRY DEMON*
│ ❤️ 200/240 {hp_bar}
├──────────────────────────┤
│ 🗡️ *『Lord』*
│ ❤️ 270/270 {p_hp_bar}
│ 🌀 100/100 [🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦]
╰──────────────────────────╯
> 🌊 *Water Surface Slash* dealt 40 damage!
""")

generate_ui_demo4()
