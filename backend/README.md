# Slayer: Eclipse — Vercel Backend

This folder is a standalone Vercel Node.js serverless API. In Vercel, set the project's **Root Directory** to `backend`. Vercel will then deploy each file under `api/` as an API route.

## MongoDB

The Telegram bot currently reads:

- Environment variable: `MONGO_URL`
- Database: `demon_slayer_rpg`

The webapp backend uses the same `MONGO_URL` and defaults to the same database name through `MONGO_DB_NAME`. It does **not** read or write the bot's gameplay collections.

Webapp-owned collections:

- `web_users`
- `web_characters`
- `web_story_progress`

This separation is intentional: Telegram bot players, characters, levels, inventory and currency are not imported. A web account starts from level 1 with a new character.

## Environment variables

Set these in Vercel → Project → Settings → Environment Variables:

- `MONGO_URL`: copy the existing bot's MongoDB connection string from its hosting environment. Never commit the actual secret.
- `MONGO_DB_NAME`: `demon_slayer_rpg` (optional; this is the default).
- `JWT_SECRET`: a new long random secret, not the Telegram bot token.
- `WEB_ORIGINS`: comma-separated allowed frontend origins, for example `https://your-webapp.vercel.app,http://localhost:5173`.

## Deploy

1. Import this GitHub repository into Vercel.
2. In Project Settings → Build and Deployment, set **Root Directory** to `backend`.
3. Set the environment variables above.
4. Deploy.
5. Test `https://YOUR-BACKEND-DOMAIN/api/health`.

## Initial routes

- `GET /api/health`
- `POST /api/auth/register` — JSON: `{ "email": "...", "password": "..." }`
- `POST /api/auth/login` — JSON: `{ "email": "...", "password": "..." }`
- `POST /api/characters/create` — Bearer token; JSON: `{ "name": "..." }`
- `GET /api/story/chapters`
- `POST /api/story/start` — Bearer token; requires a web character.
- `GET /api/story/progress` — Bearer token.

## Story Mode

The initial campaign is **Eclipse Awakening**. It begins in Hinode Village and currently defines four story chapters: Ashes of Hinode, The Wisteria Path, Echoes in the Bamboo and The Final Selection. Chapter and mission definitions are content data; each player's progress is stored separately in `web_story_progress`.

This is the backend foundation, not the finished combat engine. Mission completion rewards must be added only after the server-authoritative battle/mission validation routes exist.

## Local development

From this folder:

```bash
npm install
cp .env.example .env
# Fill in MONGO_URL and JWT_SECRET in .env
npm run dev
```

Do not commit `.env` or expose `MONGO_URL` in frontend code.