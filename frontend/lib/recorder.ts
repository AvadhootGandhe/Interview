import type { RecorderLike } from "@/components/MicButton";

/** Browser microphone recorder; rejects if access is denied. */
export async function createBrowserRecorder(): Promise<RecorderLike> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const media = new MediaRecorder(stream);
  const chunks: BlobPart[] = [];
  const rec: RecorderLike = {
    onstop: undefined,
    start: () => media.start(),
    stop: () => media.stop(),
  };
  media.ondataavailable = (e) => chunks.push(e.data);
  media.onstop = () => {
    stream.getTracks().forEach((t) => t.stop());
    rec.onstop?.(new Blob(chunks, { type: media.mimeType || "audio/webm" }));
  };
  return rec;
}
