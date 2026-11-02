const { getDb } = require("../../lib/db");
const { requireUser } = require("../../lib/auth");
const { CAMPAIGN_ID, CHAPTERS } = require("../../data/story");
const { handleOptions, applyCors, methodNotAllowed } = require("../../lib/http");

module.exports = async function handler(req, res) {
  if (handleOptions(req, res)) return;
  applyCors(req, res);
  if (req.method !== "POST") return methodNotAllowed(res, ["POST", "OPTIONS"]);

  try {
    const user = await requireUser(req, res);
    if (!user) return;

    const db = await getDb();
    const character = await db.collection("web_characters").findOne({ userId: user._id });
    if (!character) {
      return res.status(400).json({ error: "Create your fresh web character before starting Story Mode" });
    }

    const progressCollection = db.collection("web_story_progress");
    const now = new Date();
    await progressCollection.updateOne(
      { userId: user._id, campaignId: CAMPAIGN_ID },
      {
        $setOnInsert: {
          userId: user._id,
          campaignId: CAMPAIGN_ID,
          currentChapterId: CHAPTERS[0].id,
          completedMissionIds: [],
          status: "in_progress",
          startedAt: now,
          updatedAt: now
        }
      },
      { upsert: true }
    );

    const progress = await progressCollection.findOne({
      userId: user._id,
      campaignId: CAMPAIGN_ID
    });

    return res.status(200).json({
      campaignId: CAMPAIGN_ID,
      progress: {
        currentChapterId: progress.currentChapterId,
        completedMissionIds: progress.completedMissionIds,
        status: progress.status
      }
    });
  } catch (error) {
    console.error("Story start failed:", error.message);
    return res.status(500).json({ error: "Could not start Story Mode" });
  }
};