const { CHAPTERS, CAMPAIGN_ID } = require("../../data/story");
const { handleOptions, applyCors, methodNotAllowed } = require("../../lib/http");

module.exports = async function handler(req, res) {
  if (handleOptions(req, res)) return;
  applyCors(req, res);
  if (req.method !== "GET") return methodNotAllowed(res, ["GET", "OPTIONS"]);

  return res.status(200).json({
    campaignId: CAMPAIGN_ID,
    chapters: CHAPTERS
  });
};