"use client";
import { useEffect, useRef, useState } from "react";
import {
  saveChunk,
  recoveries,
  recordingBlob,
  clearRecording,
  download,
} from "../lib/recording";
export default function Recorder({
  onReady,
}: {
  onReady: (file: File) => void;
}) {
  const [state, setState] = useState("idle"),
    [elapsed, setElapsed] = useState(0),
    [level, setLevel] = useState(0),
    [error, setError] = useState(""),
    [saved, setSaved] = useState<string[]>([]);
  const rec = useRef<MediaRecorder | null>(null),
    streams = useRef<MediaStream[]>([]),
    audio = useRef<AudioContext | null>(null),
    frame = useRef(0),
    pending = useRef<Promise<void>>(Promise.resolve()),
    video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    recoveries()
      .then(setSaved)
      .catch(() =>
        setError(
          "Browser storage is unavailable. Use recording download to preserve your work.",
        ),
      );
    return () => {
      if (rec.current?.state !== "inactive") rec.current?.stop();
      streams.current.forEach((s) => s.getTracks().forEach((t) => t.stop()));
      cancelAnimationFrame(frame.current);
      void audio.current?.close();
    };
  }, []);
  useEffect(() => {
    if (state !== "recording") return;
    const t = setInterval(() => setElapsed((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, [state]);
  async function start() {
    setError("");
    setElapsed(0);
    if (
      !window.isSecureContext ||
      !navigator.mediaDevices?.getDisplayMedia ||
      !window.MediaRecorder
    ) {
      setError(
        "Screen recording requires current desktop Chrome or Edge on localhost or HTTPS. You can upload a video instead.",
      );
      return;
    }
    let display: MediaStream | undefined, mic: MediaStream | undefined;
    try {
      // Two distinct permission requests. Display capture never supplies our microphone.
      display = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: false,
      });
      mic = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
        video: false,
      });
      if (!mic.getAudioTracks().length)
        throw Error("No microphone audio track was granted.");
      streams.current = [display, mic];
      const combined = new MediaStream([
        ...display.getVideoTracks(),
        ...mic.getAudioTracks(),
      ]);
      const mime = [
        "video/webm;codecs=vp9,opus",
        "video/webm;codecs=vp8,opus",
        "video/webm",
      ].find((x) => MediaRecorder.isTypeSupported(x));
      if (!mime)
        throw Error(
          "No supported WebM recording format. Upload a recording instead.",
        );
      const recorder = new MediaRecorder(combined, { mimeType: mime });
      rec.current = recorder;
      const session = new Date().toISOString().replace(/[:.]/g, "-");
      let index = 0;
      pending.current = Promise.resolve();
      try {
        await navigator.storage?.persist();
      } catch {}
      recorder.ondataavailable = (e) => {
        if (e.data.size) {
          const n = index++;
          pending.current = pending.current
            .then(() => saveChunk(session, n, e.data))
            .catch(() => {
              setError(
                "Recording chunk storage failed (possibly disk quota). Stop now to recover saved chunks.",
              );
              recorder.stop();
            });
        }
      };
      recorder.onerror = () => {
        setError("The browser stopped recording. Recover saved chunks below.");
        if (recorder.state !== "inactive") recorder.stop();
      };
      recorder.onstop = async () => {
        setState("saving");
        streams.current.forEach((s) => s.getTracks().forEach((t) => t.stop()));
        cancelAnimationFrame(frame.current);
        await audio.current?.close();
        audio.current = null;
        await pending.current;
        setSaved(await recoveries());
        setState("stopped");
        setLevel(0);
      };
      display.getVideoTracks()[0].onended = () => {
        if (recorder.state !== "inactive") recorder.stop();
      };
      const context = new AudioContext();
      audio.current = context;
      const analyser = context.createAnalyser();
      context.createMediaStreamSource(mic).connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      const meter = () => {
        analyser.getByteTimeDomainData(samples);
        setLevel(
          Math.min(
            100,
            Math.sqrt(
              samples.reduce((a, x) => a + (x - 128) ** 2, 0) / samples.length,
            ) * 5,
          ),
        );
        frame.current = requestAnimationFrame(meter);
      };
      meter();
      if (video.current) {
        video.current.srcObject = display;
        await video.current.play();
      }
      recorder.start(3000);
      setState("recording");
    } catch (e) {
      display?.getTracks().forEach((t) => t.stop());
      mic?.getTracks().forEach((t) => t.stop());
      setError(
        `${e instanceof Error ? e.message : "Recording permission failed"}. Allow both screen sharing and microphone access, then try again.`,
      );
      setState("idle");
    }
  }
  function pause() {
    if (!rec.current) return;
    if (rec.current.state === "recording") {
      rec.current.pause();
      setState("paused");
    } else {
      rec.current.resume();
      setState("recording");
    }
  }
  return (
    <div className="recorder">
      <video ref={video} muted playsInline className="capture-preview" />
      <div className="record-status">
        <span className={state === "recording" ? "dot live" : "dot"} />
        {state.toUpperCase()}{" "}
        <b>
          {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}
        </b>
        <label>
          Microphone <meter min={0} max={100} value={level} />
        </label>
      </div>
      <p className="muted">
        Choose a screen, window, or tab. Your microphone is captured separately.
        Starting opens browser permission dialogs; system audio is excluded.
      </p>
      <div className="actions">
        <button
          onClick={start}
          disabled={["recording", "paused", "saving"].includes(state)}
        >
          ● Start recording
        </button>
        <button
          className="secondary"
          onClick={pause}
          disabled={
            !["recording", "paused"].includes(state) ||
            typeof rec.current?.pause !== "function"
          }
        >
          {state === "paused" ? "Resume" : "Pause"}
        </button>
        <button
          className="secondary"
          disabled={!["recording", "paused"].includes(state)}
          onClick={() => rec.current?.stop()}
        >
          Stop
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!!saved.length && (
        <div className="recovery">
          <h4>Saved recordings & recovery</h4>
          <p className="muted">
            Chunks stay in this browser until deleted. Interrupted WebM files
            may need FFmpeg repair. Download a backup before deleting.
          </p>
          {saved.map((s) => (
            <div className="recovery-row" key={s}>
              <small>{s}</small>
              <button
                className="secondary"
                onClick={async () =>
                  onReady(
                    new File([await recordingBlob(s)], `${s}.webm`, {
                      type: "video/webm",
                    }),
                  )
                }
              >
                Use lecture
              </button>
              <button
                className="secondary"
                onClick={async () =>
                  download(await recordingBlob(s), `${s}.webm`)
                }
              >
                Download
              </button>
              <button
                className="text-button"
                onClick={async () => {
                  if (confirm("Delete these local recording chunks?")) {
                    await clearRecording(s);
                    setSaved(await recoveries());
                  }
                }}
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
