const { getDb } = require("../../lib/db");
const { requireUser } = require("../../lib/auth");
const { handleOptions, applyCors, methodNotAllowed } = require("../../lib/http");

module.exports = async function handler(req, res) {
  if (handleOptions(req, res)) return;
  applyCors(req, res);
  if (req.method !== "POST") return methodNotAllowed(res, ["POST", "OPTIONS"]);

  try {
    const user = await requireUser(req, res);
    if (!user) return;

    const name = String(req.body?.name || "").trim();
    if (name.length < 3 || name.length > 18) {
      return res.status(400).json({ error: "Character name must be 3–18 characters" });
    }

    const db = await getDb();
    const characters = db.collection("web_characters");
    const existing = await characters.findOne({ userId: user._id });
    if (existing) {
      return res.status(409).json({ error: "This account already has a character" });
    }

    const now = new Date();
    const character = {
      userId: user._id,
      name,
      faction: null,
      level: 1,
      xp: 0,
      stats: {
        health: 100,
        maxHealth: 100,
        stamina: 100,
        maxStamina: 100,
        strength: 10,
        agility: 10,
        vitality: 10,
        technique: 10,
        focus: 10
      },
      regionId: "hinode-village",
      createdAt: now,
      updatedAt: now
    };

    const result = await characters.insertOne(character);
    return res.status(201).json({
      character: {
        id: result.insertedId.toString(),
        name: character.name,
        faction: character.faction,
        level: character.level,
        xp: character.xp,
        stats: character.stats,
        regionId: character.regionId
      }
    });
  } catch (error) {
    if (error.code === 11000) {
      return res.status(409).json({ error: "This account already has a character" });
    }
    console.error("Character creation failed:", error.message);
    return res.status(500).json({ error: "Could not create character" });
  }
};