const { getDb } = require("../../lib/db");
const { requireUser } = require("../../lib/auth");
const { CAMPAIGN_ID, CHAPTERS } = require("../../data/story");
const { handleOptions, applyCors, methodNotAllowed } = require("../../lib/http");

module.exports = async function handler(req, res) {
  if (handleOptions(req, res)) return;
  applyCors(req, res);
  if (req.method !== "GET") return methodNotAllowed(res, ["GET", "OPTIONS"]);

  try {
    const user = await requireUser(req, res);
    if (!user) return;

    const db = await getDb();
    const [character, progress] = await Promise.all([
      db.collection("web_characters").findOne({ userId: user._id }, { projection: { _id: 0, userId: 0 } }),
      db.collection("web_story_progress").findOne(
        { userId: user._id, campaignId: CAMPAIGN_ID },
        { projection: { _id: 0, userId: 0 } }
      )
    ]);

    const currentChapter = progress
      ? CHAPTERS.find((chapter) => chapter.id === progress.currentChapterId) || null
      : null;

    return res.status(200).json({
      character,
      campaignId: CAMPAIGN_ID,
      started: Boolean(progress),
      progress: progress || null,
      currentChapter
    });
  } catch (error) {
    console.error("Story progress failed:", error.message);
    return res.status(500).json({ error: "Could not load Story Mode progress" });
  }
};