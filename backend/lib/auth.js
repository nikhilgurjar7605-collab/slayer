const jwt = require("jsonwebtoken");
const { ObjectId } = require("mongodb");
const { getDb } = require("./db");

function createToken(user) {
  if (!process.env.JWT_SECRET) {
    throw new Error("JWT_SECRET environment variable is required");
  }

  return jwt.sign(
    { sub: user._id.toString(), email: user.email },
    process.env.JWT_SECRET,
    { expiresIn: "7d", issuer: "slayer-eclipse" }
  );
}

async function requireUser(req, res) {
  const header = req.headers.authorization || "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";

  if (!token || !process.env.JWT_SECRET) {
    res.status(401).json({ error: "Authentication required" });
    return null;
  }

  try {
    const payload = jwt.verify(token, process.env.JWT_SECRET, {
      issuer: "slayer-eclipse"
    });
    if (!ObjectId.isValid(payload.sub)) {
      res.status(401).json({ error: "Invalid session" });
      return null;
    }

    const db = await getDb();
    const user = await db.collection("web_users").findOne(
      { _id: new ObjectId(payload.sub) },
      { projection: { passwordHash: 0 } }
    );

    if (!user) {
      res.status(401).json({ error: "Account not found" });
      return null;
    }
    return user;
  } catch {
    res.status(401).json({ error: "Session expired or invalid" });
    return null;
  }
}

module.exports = { createToken, requireUser };