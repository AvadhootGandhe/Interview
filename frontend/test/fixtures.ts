import type { Report, SessionReply } from "@/lib/api";

export const profiles = ["AI Engineer", "Backend", "DevOps"];
export const levels = ["Fresher", "SDE-1", "SDE-1/2", "SDE-2/3", "Architect/Principal"];
export const topics = ["Caching", "Databases", "System Design"];

/** Real backend shape (backend/app/api/sessions.py SessionReply). */
export const sessionStart: SessionReply = {
  session_id: "s1",
  text: "Hi, I'm your interviewer today. How would you design a cache for a read-heavy API?",
  kind: "ask",
  state: "asking",
  done: false,
  question_index: 0,
  total_questions: 5,
  messages: [
    { kind: "greeting", text: "Hi, I'm your interviewer today." },
    { kind: "ask", text: "How would you design a cache for a read-heavy API?" },
  ],
  audio_url: null,
  evaluation: null,
};

export const answerReply: SessionReply = {
  session_id: "s1",
  text: "How would you handle cache invalidation?",
  kind: "follow_up",
  state: "asking",
  done: false,
  question_index: 1,
  total_questions: 5,
  messages: [{ kind: "follow_up", text: "How would you handle cache invalidation?" }],
  audio_url: null,
  evaluation: { satisfaction: 40, missing_points: ["invalidation"], mentioned_terms: ["redis"] },
};

export const closingReply: SessionReply = {
  ...answerReply,
  text: "Thanks for your time. Your report is ready.",
  kind: "closing",
  state: "done",
  done: true,
  question_index: 4,
  messages: [{ kind: "closing", text: "Thanks for your time. Your report is ready." }],
};

export const report: Report = {
  overall_score: 78,
  verdict: "Solid fundamentals; go deeper on trade-offs.",
  strengths: ["Clear structure", "Good use of examples"],
  gaps: ["Cache invalidation strategies"],
  questions: [
    {
      question_id: "q1",
      topic: "Caching",
      text: "How would you design a cache for a read-heavy API?",
      final_score: 85,
      follow_ups: 0,
      thread: [
        { role: "interviewer", text: "How would you design a cache for a read-heavy API?" },
        { role: "candidate", text: "I would put Redis in front of the database." },
      ],
      missing_points: [],
    },
    {
      question_id: "q2",
      topic: "Caching",
      text: "How do you keep a cache consistent with the database?",
      final_score: 62,
      follow_ups: 2,
      thread: [
        { role: "interviewer", text: "How do you keep a cache consistent with the database?" },
        { role: "candidate", text: "Expire keys." },
      ],
      missing_points: ["write-through versus write-behind trade-offs"],
    },
  ],
};
