const { getDb, DB_NAME } = require("../lib/db");
const { handleOptions, applyCors, methodNotAllowed } = require("../lib/http");

module.exports = async function handler(req, res) {
  if (handleOptions(req, res)) return;
  applyCors(req, res);
  if (req.method !== "GET") return methodNotAllowed(res, ["GET", "OPTIONS"]);

  try {
    await getDb();
    return res.status(200).json({
      ok: true,
      service: "slayer-eclipse-backend",
      database: DB_NAME
    });
  } catch (error) {
    console.error("Health check failed:", error.message);
    return res.status(503).json({ ok: false, error: "Database unavailable" });
  }
};