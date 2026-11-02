# 🗡️ Demon Slayer RPG Telegram Bot

A full Demon Slayer RPG experience on Telegram with character creation, combat, missions, parties, rankings, and world events.

---

## ⚙️ SETUP

### 1. Get a Bot Token
- Open Telegram and message `@BotFather`
- Send `/newbot` and follow the steps
- Copy your bot token

### 2. Add Your Token
- Open `config.py`
- Replace `YOUR_BOT_TOKEN_HERE` with your actual token

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Add Images
Place your images in the correct folders:
```
images/
  enemies/
    lesser_demon.jpg
    vampire.jpg
    goblin.jpg
    lower_moon.jpg
    upper_moon.jpg
    slayer.jpg
    rival_demon.jpg
    hashira.jpg
  breathing/
    water.jpg
    flame.jpg
    thunder.jpg
    wind.jpg
    stone.jpg
    serpent.jpg
    mist.jpg
    moon.jpg
    sun.jpg
    insect.jpg
    sound.jpg
    love.jpg
  demon_arts/
    spider.jpg
    explosive.jpg
    spatial.jpg
    corpse.jpg
    water.jpg
    blood.jpg
    bio.jpg
    ink.jpg
```

### 5. Run the Bot
```bash
python bot.py
```

---

## 📋 ALL COMMANDS

| Command | Description |
|---|---|
| `/start` | Create your character |
| `/menu` | Main hub |
| `/open` | Enter the world |
| `/close` | Return to safe house |
| `/profile` | View your stats |
| `/explore` | Hunt enemies (random encounter) |
| `/mission` | Mission board |
| `/travel` | Travel to different zones |
| `/shop` | View shop items |
| `/buy [item]` | Buy an item |
| `/sell [item]` | Sell an item |
| `/inventory` | View your inventory |
| `/party` | Alliance management |
| `/rankings` | Global leaderboard |
| `/help` | View all commands |

---

## 🎮 GAMEPLAY

### Character Creation
1. `/start` → Enter your name
2. Choose **Demon Slayer** or **Demon**
3. **Gacha roll** assigns your Breathing Style or Demon Art
4. Choose your **Origin Story** for a stat bonus

### Combat
- `/explore` → Random enemy encounter
- Click **Fight** to enter battle
- Use **Attack**, **Technique**, **Items**, **Party**, or **Flee**
- Techniques use Stamina (STA)
- Victory earns XP and Yen

### Ranks (Slayer)
Mizunoto → Mizunoe → Kanoto → Kanoe → Tsuchinoto → Tsuchinoe → Hinoto → Hinoe → Kinoto → Kinoe → **Hashira**

### Ranks (Demon)
Stray Demon → Low Demon → Mid Demon → High Demon → Lower Moon 6-1 → Upper Moon 6-1

### Alliance / Party
- `/party` → Manage your alliance
- Invite players with the Invite button
- Both players must accept
- Fight together in `/explore`
- Cross-faction allowed (Slayer + Demon)

### Shop
- `/shop` → View all items
- `/buy [item name]` → Buy instantly if you have enough Yen
- `/sell [item name]` → Sell any item or material

### Travel
- Unlock new zones as you level up
- `/travel` → Button-based zone selection
- Butterfly Estate heals HP and STA fully

---

## 🌍 WORLD EVENTS
World-wide raid events are broadcast to all players.
A minimum number of players must join before the fight begins.
All damage is combined — everyone contributes!

---

## 🖼️ IMAGES
The bot uses images for:
- Enemy encounters (`/explore`)
- Breathing Style gacha reveal
- Demon Art gacha reveal

All other screens use text and emoji only.
More images can be added later to other screens.

---

## 📁 FILE STRUCTURE
```
demon_slayer_bot/
├── bot.py              — Main bot entry point
├── config.py           — All game data & settings
├── requirements.txt    — Python dependencies
├── data/               — SQLite database (auto-created)
├── images/
│   ├── enemies/        — Enemy images
│   ├── breathing/      — Breathing style images
│   └── demon_arts/     — Demon art images
├── handlers/
│   ├── start.py        — Character creation
│   ├── menu.py         — Main menu
│   ├── profile.py      — Profile card
│   ├── explore.py      — Combat & exploration
│   ├── mission.py      — Mission board
│   ├── shop.py         — Shop system
│   ├── inventory.py    — Inventory
│   ├── party.py        — Alliance system
│   ├── travel.py       — Travel zones
│   ├── rankings.py     — Leaderboards
│   └── help_cmd.py     — Help command
└── utils/
    ├── database.py     — SQLite database layer
    └── helpers.py      — Utility functions
```


---

## 🌐 Slayer: Eclipse Webapp Backend

The independent browser RPG backend lives in `backend/`. It uses the same MongoDB connection variable and database as the Telegram bot, but stores webapp accounts and progress in separate `web_*` collections. Webapp characters start fresh and do not inherit Telegram bot progress.

For Vercel deployment, import this repository and set the Vercel project's **Root Directory** to `backend`. Configure `MONGO_URL`, `JWT_SECRET`, and optionally `WEB_ORIGINS` in Vercel Environment Variables.

See [backend/README.md](backend/README.md) for setup instructions, API routes and Story Mode details.
