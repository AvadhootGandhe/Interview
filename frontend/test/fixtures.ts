import type { AnswerResult, Report, SessionStart } from "@/lib/api";

export const profiles = ["AI Engineer", "Backend", "DevOps"];
export const levels = ["Fresher", "SDE-1", "SDE-1/2", "SDE-2/3", "Architect/Principal"];
export const topics = ["Caching", "Databases", "System Design"];

export const sessionStart: SessionStart = {
  id: "s1",
  text: "Hi, I'm your interviewer today. Let's start with caching.",
  audio_url: null,
};

export const answerResult: AnswerResult = {
  transcript: "I would put Redis in front of the database.",
  text: "Good. How would you handle cache invalidation?",
  audio_url: null,
  state: "follow_up",
  progress: { current: 2, total: 5 },
};

export const report: Report = {
  overall: 78,
  verdict: "Solid fundamentals; go deeper on trade-offs.",
  questions: [
    {
      question: "How would you design a cache for a read-heavy API?",
      score: 85,
      followups: 0,
      feedback: "Clear layering and eviction choice.",
    },
    {
      question: "How do you keep a cache consistent with the database?",
      score: 62,
      followups: 2,
      feedback: "Missed write-through versus write-behind trade-offs.",
    },
  ],
  strengths: ["Clear structure", "Good use of examples"],
  gaps: ["Cache invalidation strategies"],
  thread: [
    { role: "interviewer", text: "How would you design a cache for a read-heavy API?" },
    { role: "candidate", text: "I would put Redis in front of the database." },
  ],
};
