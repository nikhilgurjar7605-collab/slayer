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
    const db = await getDb();
    const user = await db.collection("web_users").findOne({ email });

    if (!user || !(await bcrypt.compare(password, user.passwordHash))) {
      return res.status(401).json({ error: "Invalid email or password" });
    }

    return res.status(200).json({
      token: createToken(user),
      user: { id: user._id.toString(), email: user.email }
    });
  } catch (error) {
    console.error("Login failed:", error.message);
    return res.status(500).json({ error: "Could not sign in" });
  }
};