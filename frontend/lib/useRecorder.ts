"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface Recorder {
  recording: boolean;
  /** Ask for the mic and start recording. Rejects if the mic is unavailable. */
  start: () => Promise<void>;
  /** Stop; `onComplete` fires with the audio once the recorder flushes. */
  stop: () => void;
}

const MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

/** First recording format this browser supports (Chrome/Firefox: webm/ogg, Safari: mp4); undefined = browser default. */
export function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") return undefined;
  return MIME_TYPES.find((t) => MediaRecorder.isTypeSupported(t));
}

/**
 * Hold-to-talk recorder around MediaRecorder. Handles the race where the
 * user lets go before getUserMedia resolves: nothing is recorded or sent.
 */
export function useRecorder(onComplete: (audio: Blob) => void): Recorder {
  const [recording, setRecording] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const holdingRef = useRef(false);
  const startingRef = useRef(false);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const start = useCallback(async () => {
    holdingRef.current = true;
    if (startingRef.current || recorderRef.current) return;
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      holdingRef.current = false;
      throw new Error("Recording is not supported in this browser.");
    }
    startingRef.current = true;
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      holdingRef.current = false;
      throw err;
    } finally {
      startingRef.current = false;
    }
    const release = () => stream.getTracks().forEach((t) => t.stop());
    if (!holdingRef.current) {
      release();
      return;
    }
    const chunks: Blob[] = [];
    let rec: MediaRecorder;
    try {
      const mimeType = pickMimeType();
      rec = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    } catch (err) {
      release();
      holdingRef.current = false;
      throw err;
    }
    rec.ondataavailable = (e: BlobEvent | { data: Blob }) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };
    rec.onerror = () => {
      release();
      recorderRef.current = null;
      setRecording(false);
    };
    rec.onstop = () => {
      release();
      recorderRef.current = null;
      setRecording(false);
      const audio = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
      if (audio.size > 0) onCompleteRef.current(audio);
    };
    recorderRef.current = rec;
    rec.start();
    setRecording(true);
  }, []);

  const stop = useCallback(() => {
    holdingRef.current = false;
    const rec = recorderRef.current;
    if (rec && rec.state === "recording") rec.stop();
  }, []);

  useEffect(
    () => () => {
      holdingRef.current = false;
      const rec = recorderRef.current;
      if (rec && rec.state === "recording") {
        rec.onstop = null;
        rec.stop();
      }
    },
    [],
  );

  return { recording, start, stop };
}
