export type Selection = { profile?: string; level?: string; company?: string; topic?: string };

export type CatalogApi = {
  profiles(): Promise<string[]>;
  levels(): Promise<string[]>;
  companies(q: string): Promise<string[]>;
  topics(profile: string, company?: string): Promise<string[]>;
};

export type Turn = { messages: string[]; kind: string; state: "active" | "done"; audio_urls: string[]; transcript?: string | null };

export type SessionApi = {
  sendText(id: string, text: string): Promise<Turn>;
  sendAudio(id: string, audio: Blob): Promise<Turn>;
  end(id: string): Promise<Turn>;
};

export type ThreadTurn = { role: "interviewer" | "candidate"; kind: string; text: string };
export type QuestionReport = {
  index: number; topic: string; question: string; score: number; followups: number;
  covered_points: string[]; missing_points: string[]; thread: ThreadTurn[];
};
export type Report = {
  session_id: string; profile: string; level: string | null; company: string | null;
  overall_score: number; verdict: string; strengths: string[]; gaps: string[]; questions: QuestionReport[];
};
