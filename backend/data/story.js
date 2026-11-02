// Original story content for Slayer: Eclipse.
// Keep characters, dialogue, locations and artwork original before public release.
const CAMPAIGN_ID = "eclipse-awakening";

const CHAPTERS = [
  {
    id: "chapter-01",
    campaignId: CAMPAIGN_ID,
    number: 1,
    title: "Ashes of Hinode",
    subtitle: "The night your old life ended",
    recommendedLevel: 1,
    regionId: "hinode-village",
    summary: "A quiet mountain village is attacked after sunset. Find your family, help the villagers and survive your first encounter with a demon.",
    missions: [
      {
        id: "c01-m01",
        title: "A Quiet Morning",
        type: "story",
        objective: "Speak with the villagers and learn the village layout.",
        description: "Explore Hinode and speak to the village elder, the blacksmith and the local healer."
      },
      {
        id: "c01-m02",
        title: "The First Bell",
        type: "story",
        objective: "Investigate the warning bell near the northern gate.",
        description: "Follow the sound through the village and discover why the guards have disappeared."
      },
      {
        id: "c01-m03",
        title: "When the Sun Goes Down",
        type: "combat",
        objective: "Protect the villagers from the lesser demon.",
        description: "Learn movement, light attacks, dodging and blocking in your first real fight."
      },
      {
        id: "c01-m04",
        title: "A Promise at Dawn",
        type: "story",
        objective: "Meet the wandering swordsman at the wisteria boundary.",
        description: "The stranger offers a path to training, but warns that surviving the night was only the beginning."
      }
    ]
  },
  {
    id: "chapter-02",
    campaignId: CAMPAIGN_ID,
    number: 2,
    title: "The Wisteria Path",
    subtitle: "Discipline before strength",
    recommendedLevel: 3,
    regionId: "wisteria-forest",
    summary: "Travel to a secluded training ground, build your fundamentals and learn the discipline required to face demons.",
    missions: [
      { id: "c02-m01", title: "The Long Climb", type: "exploration", objective: "Reach the mountain training grounds.", description: "Navigate the forest trail and find the hidden training camp." },
      { id: "c02-m02", title: "Breath and Balance", type: "training", objective: "Complete the stamina and movement trials.", description: "Practise sprinting, dodging, blocking and controlled breathing." },
      { id: "c02-m03", title: "The Wooden Blade", type: "combat", objective: "Defeat the training opponent.", description: "Learn to recognise attack tells and punish openings." }
    ]
  },
  {
    id: "chapter-03",
    campaignId: CAMPAIGN_ID,
    number: 3,
    title: "Echoes in the Bamboo",
    subtitle: "Something is hunting the hunters",
    recommendedLevel: 6,
    regionId: "bamboo-valley",
    summary: "A patrol has vanished in Bamboo Valley. Track the signs, rescue the survivor and confront the demon responsible.",
    missions: [
      { id: "c03-m01", title: "Missing Patrol", type: "investigation", objective: "Search the abandoned patrol route.", description: "Inspect clues and follow the trail deeper into the valley." },
      { id: "c03-m02", title: "Silence Between Trees", type: "combat", objective: "Defeat the valley stalkers.", description: "Fight enemies that use ambushes and retreating attacks." },
      { id: "c03-m03", title: "The Thread Collector", type: "boss", objective: "Defeat the chapter boss.", description: "Study the boss attack patterns and protect the rescued patrol member." }
    ]
  },
  {
    id: "chapter-04",
    campaignId: CAMPAIGN_ID,
    number: 4,
    title: "The Final Selection",
    subtitle: "Earn the right to wear the uniform",
    recommendedLevel: 10,
    regionId: "selection-mountain",
    summary: "Enter the selection grounds, survive a series of trials and prove that you can protect others when the night turns against you.",
    missions: [
      { id: "c04-m01", title: "The Gate Opens", type: "story", objective: "Enter the selection grounds.", description: "Meet the other candidates and learn the rules of the trial." },
      { id: "c04-m02", title: "Seven Nights", type: "survival", objective: "Survive the selection trials.", description: "Manage health and stamina while navigating increasingly dangerous encounters." },
      { id: "c04-m03", title: "A Blade of Your Own", type: "story", objective: "Complete the selection and receive your first sword.", description: "Return from the mountain and begin your life as a recognised hunter." }
    ]
  }
];

function getChapter(chapterId) {
  return CHAPTERS.find((chapter) => chapter.id === chapterId) || null;
}

module.exports = { CAMPAIGN_ID, CHAPTERS, getChapter };