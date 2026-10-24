import { audioSrc, type SessionReply } from "./api";

/** The clips to speak for a reply: `audio_urls` in order, else the whole-text `audio_url`, else nothing (text only). */
export function clipsOf(r: Pick<SessionReply, "audio_url" | "audio_urls">): string[] {
  const list = (r.audio_urls ?? []).map(audioSrc).filter((s): s is string => !!s);
  if (list.length) return list;
  const one = audioSrc(r.audio_url);
  return one ? [one] : [];
}

interface Hooks {
  /** True while the sequence is running (orb 'speaking'); false when it ends, is blocked or is stopped. */
  onSpeaking: (speaking: boolean) => void;
  /** The browser wants a tap before it lets us speak. Call `resume()` from a user gesture. */
  onBlocked: () => void;
  /** Every clip in the sequence failed. */
  onAllFailed: () => void;
}

/**
 * Plays a list of clips back to back. Clip n+1 is created (and starts buffering) while clip n plays, so there is no gap.
 * A clip that errors is skipped. `stop()` is final for the current sequence: late events are ignored.
 */
export class ClipPlayer {
  private gen = 0;
  private srcs: string[] = [];
  private els: HTMLAudioElement[] = [];
  private errored = new Set<number>();
  private idx = 0;
  private failed = 0;

  constructor(private hooks: Hooks) {}

  start(srcs: string[]) {
    this.stop();
    if (!srcs.length || typeof Audio === "undefined") return;
    this.srcs = srcs;
    this.hooks.onSpeaking(true);
    this.playCurrent();
  }

  /** After a blocked autoplay: try the current clip again (from a tap). */
  resume() {
    if (this.idx >= this.srcs.length) return;
    this.hooks.onSpeaking(true);
    this.playCurrent();
  }

  stop() {
    this.gen++;
    for (const el of this.els) {
      el.onended = null;
      el.onerror = null;
      try {
        el.pause();
      } catch {
        /* jsdom */
      }
    }
    this.els = [];
    this.srcs = [];
    this.errored.clear();
    this.idx = 0;
    this.failed = 0;
    this.hooks.onSpeaking(false);
  }

  private load(i: number): HTMLAudioElement | null {
    if (i >= this.srcs.length) return null;
    if (this.els[i]) return this.els[i];
    const gen = this.gen;
    const el = new Audio(this.srcs[i]);
    el.preload = "auto";
    el.onended = () => {
      if (gen === this.gen && i === this.idx) this.advance();
    };
    el.onerror = () => {
      if (gen !== this.gen) return;
      if (i === this.idx) this.fail();
      else this.errored.add(i); // a preloaded clip broke early: skip it when its turn comes
    };
    this.els[i] = el;
    return el;
  }

  private playCurrent() {
    const gen = this.gen;
    if (this.errored.has(this.idx)) return this.fail();
    const el = this.load(this.idx);
    if (!el) return;
    this.load(this.idx + 1); // preload the next one
    const done = (err?: { name?: string }) => {
      if (gen !== this.gen) return;
      if (err?.name === "NotAllowedError") {
        this.hooks.onSpeaking(false);
        this.hooks.onBlocked();
      } else this.fail();
    };
    try {
      Promise.resolve(el.play()).catch(done);
    } catch (e) {
      done(e as { name?: string });
    }
  }

  private fail() {
    this.failed++;
    this.advance();
  }

  private advance() {
    this.idx++;
    if (this.idx < this.srcs.length) return this.playCurrent();
    const allFailed = this.failed === this.srcs.length;
    this.hooks.onSpeaking(false);
    if (allFailed) this.hooks.onAllFailed();
  }
}
