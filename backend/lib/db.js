const { MongoClient } = require("mongodb");

const DB_NAME = process.env.MONGO_DB_NAME || "demon_slayer_rpg";
const CACHE_KEY = "__slayerEclipseMongo";

async function getDb() {
  if (!process.env.MONGO_URL) {
    throw new Error("MONGO_URL environment variable is required");
  }

  if (!global[CACHE_KEY]) {
    const client = new MongoClient(process.env.MONGO_URL, {
      maxPoolSize: 5,
      minPoolSize: 0,
      serverSelectionTimeoutMS: 10000
    });

    global[CACHE_KEY] = {
      client,
      promise: client.connect().then(async () => {
        const db = client.db(DB_NAME);
        await Promise.all([
          db.collection("web_users").createIndex({ email: 1 }, { unique: true }),
          db.collection("web_characters").createIndex({ userId: 1 }, { unique: true }),
          db.collection("web_story_progress").createIndex(
            { userId: 1, campaignId: 1 },
            { unique: true }
          )
        ]);
        return db;
      })
    };
  }

  return global[CACHE_KEY].promise;
}

module.exports = { getDb, DB_NAME };