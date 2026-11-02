const bcrypt = require("bcryptjs");
const { getDb } = require("../../lib/db");
const { createToken } = require("../../lib/auth");
const { handleOptions, applyCors, methodNotAllowed } = require("../../lib/http");

module.exports = async function handler(req, res) {
  if (handleOptions(req, res)) return;
  applyCors(req, res);
  if (req.method !== "POST") return methodNotAllowed(res, ["POST", "OPTIONS"]);

  try {
    const email = String(req.body?.email || "").trim().toLowerCase();
    const password = String(req.body?.password || "");

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return res.status(400).json({ error: "Enter a valid email address" });
    }
    if (password.length < 8 || password.length > 72) {
      return res.status(400).json({ error: "Password must be 8–72 characters" });
    }

    const db = await getDb();
    const users = db.collection("web_users");
    if (await users.findOne({ email }, { projection: { _id: 1 } })) {
      return res.status(409).json({ error: "An account with this email already exists" });
    }

    const passwordHash = await bcrypt.hash(password, 12);
    const now = new Date();
    const result = await users.insertOne({
      email,
      passwordHash,
      accountType: "web",
      createdAt: now,
      updatedAt: now
    });

    const user = { _id: result.insertedId, email };
    return res.status(201).json({
      token: createToken(user),
      user: { id: result.insertedId.toString(), email }
    });
  } catch (error) {
    if (error.code === 11000) {
      return res.status(409).json({ error: "An account with this email already exists" });
    }
    console.error("Registration failed:", error.message);
    return res.status(500).json({ error: "Could not create account" });
  }
};