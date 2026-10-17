"use client";
import { useEffect, useRef, useState } from "react";
import Recorder from "../components/Recorder";
import { API, api, csrfToken } from "../lib/api";
type Segment = {
  id: string;
  start: number;
  end: number;
  original: string;
  english: string;
  flags: string[];
  acknowledged: boolean;
  audio: string;
};
type Job = {
  id: string;
  kind: string;
  status: string;
  stage: string;
  progress: number;
  error: string;
  usage: unknown[];
};
type Mapping = {
  id: string | null;
  source_start: number;
  source_end: number;
  final_start: number;
  final_end: number;
  hold: number;
  tempo: number;
  review: boolean;
};
type Lecture = {
  id: string;
  title: string;
  course: string;
  topic: string;
  mode: string;
  status: string;
  source: string;
  revision: number;
  approved: number;
  voice: string;
  pronunciation: string;
  preview: string;
  exports: Record<string, string>;
  segments: Segment[];
  jobs: Job[];
  timeline: Mapping[];
  sample_ok: boolean;
  sample: Segment[] | null;
};
const times = (n: number) =>
  `${Math.floor(n / 60)}:${String(Math.floor(n % 60)).padStart(2, "0")}`;
const asset = (l: Lecture, name: string) =>
  `${API}/lectures/${l.id}/assets/${name}`;
function Editor({
  segment: s,
  onSave,
  seek,
  busy,
  regenerate,
}: {
  segment: Segment;
  onSave: (s: Segment, text: string, ack: boolean) => Promise<void>;
  seek: () => void;
  busy: boolean;
  regenerate: () => void;
}) {
  const [text, setText] = useState(s.english),
    [ack, setAck] = useState(s.acknowledged),
    [saving, setSaving] = useState(false);
  useEffect(() => {
    setText(s.english);
    setAck(s.acknowledged);
  }, [s.english, s.acknowledged]);
  const dirty = text !== s.english || ack !== s.acknowledged;
  return (
    <article
      data-dirty={dirty ? "true" : "false"}
      className={"segment " + (s.flags.length ? "flagged" : "")}
    >
      <div className="segment-head">
        <button className="timestamp" onClick={seek}>
          ▷ {times(s.start)} — {times(s.end)}
        </button>
        <span className="muted">
          {s.flags.length ? "Review required" : "Source linked"}
        </span>
      </div>
      <div className="segment-columns">
        <div>
          <label>ORIGINAL · URDU + ENGLISH</label>
          <p dir="auto">{s.original}</p>
        </div>
        <div>
          <label htmlFor={"segment-" + s.id}>ENGLISH NARRATION</label>
          <textarea
            id={"segment-" + s.id}
            value={text}
            maxLength={4000}
            onChange={(e) => setText(e.target.value)}
            disabled={busy}
          />
        </div>
      </div>
      {s.flags.length > 0 && (
        <div className="flag">
          <p>{s.flags.join(" · ")}</p>
          <label>
            <input
              type="checkbox"
              checked={ack}
              onChange={(e) => setAck(e.target.checked)}
              disabled={busy}
            />{" "}
            I checked this passage against the source
          </label>
        </div>
      )}
      <div className="actions">
        <button
          className="secondary"
          disabled={!dirty || busy || saving}
          onClick={async () => {
            setSaving(true);
            try {
              await onSave(s, text, ack);
            } finally {
              setSaving(false);
            }
          }}
        >
          {saving ? "Saving…" : dirty ? "Save changes" : "Saved"}
        </button>
        {s.audio && (
          <button
            className="text-button"
            disabled={busy || dirty}
            onClick={regenerate}
          >
            Regenerate this segment
          </button>
        )}
        <small className="muted">{text.length}/4000 characters</small>
      </div>
    </article>
  );
}
export default function Home() {
  const [lectures, setLectures] = useState<Lecture[]>([]),
    [selected, setSelected] = useState<Lecture | null>(null),
    [view, setView] = useState("dashboard"),
    [tab, setTab] = useState("source"),
    [capture, setCapture] = useState("upload"),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [uploadProgress, setUploadProgress] = useState(0),
    [health, setHealth] = useState<{ live_available: boolean } | null>(null),
    [file, setFile] = useState<File | null>(null),
    [voice, setVoice] = useState("coral"),
    [pronunciation, setPronunciation] = useState(""),
    [burn, setBurn] = useState(false),
    [acceptHolds, setAcceptHolds] = useState(false);
  const [form, setForm] = useState({
    title: "",
    course: "",
    topic: "",
    context: "",
    glossary: "",
    mode: "demo",
  });
  const video = useRef<HTMLVideoElement>(null),
    selection = useRef<string | null>(null);
  const active = selected?.jobs?.find((j) =>
    ["running", "queued"].includes(j.status),
  );
  async function refresh(id?: string) {
    const list = await api("/lectures");
    setLectures(list);
    const key = id || selection.current;
    if (key) {
      const l = await api("/lectures/" + key);
      setSelected(l);
    }
  }
  useEffect(() => {
    api("/health")
      .then(setHealth)
      .catch((e) => setError(e.message));
    refresh().catch((e) => setError(e.message));
    const t = setInterval(() => refresh().catch(() => {}), 2500);
    return () => clearInterval(t);
  }, []);
  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }
  async function open(l: Lecture) {
    selection.current = l.id;
    const data = await api("/lectures/" + l.id);
    setSelected(data);
    setVoice(data.voice);
    setPronunciation(data.pronunciation);
    setView("lecture");
    setTab("source");
    setAcceptHolds(false);
  }
  async function create() {
    await act(async () => {
      const l = await api("/lectures", "POST", form);
      await open(l);
      await refresh(l.id);
      if (file) await upload(l, file);
    });
  }
  async function upload(l: Lecture, f: File) {
    setUploadProgress(1);
    const data = new FormData();
    data.append("file", f);
    await new Promise<void>((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open("POST", `${API}/lectures/${l.id}/source`);
      x.withCredentials = true;
      if (csrfToken()) x.setRequestHeader("X-CSRF-Token", csrfToken());
      x.upload.onprogress = (e) => {
        if (e.lengthComputable)
          setUploadProgress(Math.round((e.loaded / e.total) * 100));
      };
      x.onload = () =>
        x.status < 300 ? resolve() : reject(Error(x.responseText));
      x.onerror = () =>
        reject(Error("Upload interrupted. Retry the original file."));
      x.send(data);
    });
    setFile(null);
    setUploadProgress(0);
    await refresh(l.id);
  }
  async function job(kind: string) {
    if (!selected) return;
    await act(async () => {
      await api(`/lectures/${selected.id}/jobs`, "POST", {
        kind,
        burn_captions: burn,
        accept_holds: acceptHolds,
      });
      await refresh();
      setNotice(
        kind === "voice_preview"
          ? "Voice preview queued. This short preview may incur a small provider charge in live mode."
          : "Background job queued. You can leave this page open.",
      );
    });
  }
  async function saveSettings() {
    if (!selected) return;
    await act(async () => {
      await api(`/lectures/${selected.id}/settings`, "PUT", {
        voice,
        pronunciation,
      });
      await refresh();
      setNotice("Settings saved. Approve the script again before narration.");
    });
  }
  const disabled = busy || !!active;
  return (
    <div className="shell">
      <aside>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setView("dashboard");
          }}
        >
          <span className="brand-mark">
            L<span>↗</span>
          </span>
          <span>
            Lecture<span className="brand-light">Studio</span>
          </span>
        </a>
        <div className="workspace-label">YOUR WORKSPACE</div>
        <button
          className={"nav " + (view === "dashboard" ? "chosen" : "")}
          onClick={() => setView("dashboard")}
        >
          ▦ <span>All lectures</span>
          <small>{lectures.length}</small>
        </button>
        <button
          className={"nav " + (view === "new" ? "chosen" : "")}
          onClick={() => {
            setFile(null);
            setView("new");
          }}
        >
          ⊕ <span>New lecture</span>
        </button>
        <div className="sidebar-bottom">
          <span className="local-dot" /> Local workspace
          <p>
            Your screen. Your teaching.
            <br />A new audience.
          </p>
          <small>Single user · stored on this computer</small>
        </div>
      </aside>
      <main>
        <header>
          <div className="breadcrumb">
            Workspace <span>/</span>{" "}
            {view === "dashboard"
              ? "All lectures"
              : view === "new"
                ? "New lecture"
                : selected?.title}
          </div>
          <span className="local-badge">● Private workspace</span>
        </header>
        <div className="content">
          {error && (
            <div className="error" role="alert">
              {error}
              <button className="text-button" onClick={() => setError("")}>
                Dismiss
              </button>
            </div>
          )}
          {notice && (
            <div className="notice" role="status">
              {notice}
            </div>
          )}
          {view === "dashboard" && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    FROM YOUR CLASSROOM, TO EVERYONE
                  </div>
                  <h1>Your lectures, in English.</h1>
                  <p className="muted">
                    Keep the explanation. Keep the screen. Reach the next
                    section.
                  </p>
                </div>
                <button
                  onClick={() => {
                    setFile(null);
                    setView("new");
                  }}
                >
                  ＋ New lecture
                </button>
              </div>
              <div className="intro-card">
                <div className="intro-icon">
                  اردو <span>→</span> Aa
                </div>
                <div>
                  <h2>Teach naturally. Share clearly.</h2>
                  <p>
                    Record in Urdu and English, review a faithful English
                    script,
                    <br />
                    then create a synchronized video and student materials.
                  </p>
                </div>
                <div className="intro-steps">
                  <span>
                    01 <b>Capture</b>
                  </span>
                  <span>
                    02 <b>Review</b>
                  </span>
                  <span>
                    03 <b>Share</b>
                  </span>
                </div>
              </div>
              <div className="section-heading">
                <h2>
                  Lecture library <span>{lectures.length}</span>
                </h2>
                <small className="muted">
                  Original recordings are always retained
                </small>
              </div>
              {!lectures.length ? (
                <div className="empty">
                  <div className="empty-icon">▷</div>
                  <h2>Your first English lecture starts here</h2>
                  <p className="muted">
                    Upload a short recording or capture your screen and
                    microphone.
                  </p>
                  <button onClick={() => setView("new")}>
                    Create your first lecture →
                  </button>
                  <p className="tiny">
                    No API key yet? Explore with the clearly labeled offline
                    demo.
                  </p>
                </div>
              ) : (
                <div className="lecture-grid">
                  {lectures.map((l, i) => (
                    <button
                      className="lecture-card"
                      key={l.id}
                      onClick={() => act(() => open(l))}
                    >
                      <div className={"lecture-cover color-" + (i % 3)}>
                        <span>{l.course || "LECTURE"}</span>
                        <div>▷</div>
                        <small>
                          {l.mode === "demo"
                            ? "DEMO PROJECT"
                            : "ENGLISH EDITION"}
                        </small>
                      </div>
                      <div className="lecture-info">
                        <div className="card-meta">
                          <span>{l.topic || "General lecture"}</span>
                          <span className="status">{l.status}</span>
                        </div>
                        <h3>{l.title}</h3>
                        <p>
                          {l.mode === "demo"
                            ? "Offline demonstration"
                            : "Urdu + English → English"}{" "}
                          <span>↗</span>
                        </p>
                      </div>
                    </button>
                  ))}
                </div>
              )}
              <div className="privacy-note">
                ◇ Screen and microphone permissions are requested only when you
                start recording. Live processing sends audio and reviewed text
                to your configured AI provider.
              </div>
            </>
          )}
          {view === "new" && (
            <>
              <div className="eyebrow">01 / CREATE A LECTURE</div>
              <h1>Start with your teaching.</h1>
              <p className="muted">
                A little context helps preserve the terms that matter.
              </p>
              <div className="new-grid">
                <section className="panel">
                  <h2>Lecture details</h2>
                  {(["title", "course", "topic"] as const).map((k) => (
                    <label className="field" key={k}>
                      {k === "title"
                        ? "Lecture title *"
                        : k === "course"
                          ? "Course"
                          : "Topic"}
                      <input
                        value={form[k]}
                        onChange={(e) =>
                          setForm({ ...form, [k]: e.target.value })
                        }
                        placeholder={
                          k === "title"
                            ? "e.g. Understanding modular arithmetic"
                            : k === "course"
                              ? "e.g. CS 421 · Cryptography"
                              : "e.g. Modular inverse"
                        }
                      />
                    </label>
                  ))}
                  <label className="field">
                    Technical vocabulary & terminology
                    <textarea
                      value={form.glossary}
                      onChange={(e) =>
                        setForm({ ...form, glossary: e.target.value })
                      }
                      placeholder="elliptic curve, secp256k1, modular inverse, preimage resistance"
                    />
                  </label>
                  <label className="field">
                    Optional lecture context
                    <textarea
                      value={form.context}
                      onChange={(e) =>
                        setForm({ ...form, context: e.target.value })
                      }
                      placeholder="Course level, previous topics, or names mentioned…"
                    />
                  </label>
                  <label className="field">
                    Processing mode
                    <select
                      value={form.mode}
                      onChange={(e) =>
                        setForm({ ...form, mode: e.target.value })
                      }
                    >
                      <option value="demo">
                        Demo · fixture transcript + offline synthetic voice
                      </option>
                      <option value="live" disabled={!health?.live_available}>
                        Live · backend OpenAI key required
                      </option>
                    </select>
                  </label>
                  <p className="tiny">
                    Demo text does not reflect your uploaded audio. Live pricing
                    estimates are unavailable; usage is recorded where providers
                    return it.
                  </p>
                </section>
                <section className="panel">
                  <h2>Your recording</h2>
                  <div className="tabs">
                    <button
                      className={capture === "upload" ? "selected" : ""}
                      onClick={() => setCapture("upload")}
                    >
                      ↑ Upload video
                    </button>
                    <button
                      className={capture === "record" ? "selected" : ""}
                      onClick={() => setCapture("record")}
                    >
                      ◉ Record screen
                    </button>
                  </div>
                  {capture === "upload" ? (
                    <label className="upload-zone">
                      <span>↥</span>
                      <h3>{file ? file.name : "Bring your lecture"}</h3>
                      <p>Choose MP4, WebM, MOV, MKV or M4V</p>
                      <input
                        type="file"
                        accept="video/*,.mkv"
                        onChange={(e) => setFile(e.target.files?.[0] || null)}
                      />
                    </label>
                  ) : (
                    <Recorder
                      onReady={(f) => {
                        setFile(f);
                        setNotice(
                          "Recording selected. Enter lecture details and create the lecture.",
                        );
                      }}
                    />
                  )}
                  {file && (
                    <p className="notice">
                      Selected: {file.name} · {(file.size / 1048576).toFixed(1)}{" "}
                      MB
                    </p>
                  )}
                  <div className="workflow-note">
                    <b>You’re in control.</b>
                    <p>
                      First inspect a 30-second sample. Then review the English
                      script. Narration generation waits for your approval.
                    </p>
                  </div>
                  <button
                    disabled={busy || !form.title.trim()}
                    onClick={create}
                  >
                    {busy ? "Creating…" : "Create lecture →"}
                  </button>
                  {uploadProgress > 0 && (
                    <progress value={uploadProgress} max={100} />
                  )}
                </section>
              </div>
            </>
          )}
          {view === "lecture" && selected && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    {selected.course || "LECTURE"} /{" "}
                    {selected.mode === "demo"
                      ? "DEMO · FIXTURE CONTENT"
                      : "LIVE PROCESSING"}
                  </div>
                  <h1>{selected.title}</h1>
                  <p className="muted">
                    {selected.topic}{" "}
                    <span className="status">{selected.status}</span>
                  </p>
                </div>
                <button
                  className="text-button danger"
                  disabled={disabled}
                  onClick={() =>
                    act(async () => {
                      if (
                        !confirm(
                          "Delete this lecture, all source files, intermediate assets and exports? Browser recovery chunks are deleted separately.",
                        )
                      )
                        return;
                      await api("/lectures/" + selected.id, "DELETE");
                      selection.current = null;
                      setSelected(null);
                      setView("dashboard");
                      await refresh();
                    })
                  }
                >
                  Delete lecture
                </button>
              </div>
              {selected.mode === "demo" && (
                <div className="demo-banner">
                  DEMO MODE · The transcript and translation are fixture text.
                  Narration is generated locally with a basic synthetic voice.
                  No live AI is used.
                </div>
              )}
              {active && (
                <div className="job-progress">
                  <div>
                    <b>{active.stage}</b>
                    <span>{Math.round(active.progress * 100)}%</span>
                  </div>
                  <progress max={1} value={active.progress} />
                  <button
                    className="text-button"
                    onClick={() =>
                      act(async () => {
                        await api("/jobs/" + active.id + "/cancel", "POST");
                        await refresh();
                      })
                    }
                  >
                    Cancel after current operation
                  </button>
                </div>
              )}
              {selected.jobs
                ?.filter(
                  (j) => j.status === "failed" || j.status === "cancelled",
                )
                .slice(0, 1)
                .map((j) => (
                  <div className="error" key={j.id}>
                    <b>
                      {j.stage}: {j.status}
                    </b>
                    <p>{j.error}</p>
                    <button
                      className="secondary"
                      disabled={disabled}
                      onClick={() =>
                        act(async () => {
                          await api("/jobs/" + j.id + "/retry", "POST");
                          await refresh();
                        })
                      }
                    >
                      Retry / resume cached work
                    </button>
                  </div>
                ))}
              <nav className="tabs workflow-tabs">
                {[
                  ["source", "01  Source & sample"],
                  ["script", "02  Review script"],
                  ["voice", "03  Voice"],
                  ["preview", "04  Preview & export"],
                ].map(([k, label]) => (
                  <button
                    className={tab === k ? "selected" : ""}
                    key={k}
                    onClick={() => setTab(k)}
                  >
                    {label}
                  </button>
                ))}
              </nav>
              {tab === "source" && (
                <div className="new-grid">
                  <section className="panel">
                    <h2>Original lecture</h2>
                    {selected.source ? (
                      <video
                        controls
                        preload="metadata"
                        src={asset(selected, "source")}
                      />
                    ) : (
                      <>
                        <label className="upload-zone">
                          <h3>Upload your video</h3>
                          <input
                            disabled={disabled}
                            type="file"
                            accept="video/*,.mkv"
                            onChange={(e) => {
                              const f = e.target.files?.[0];
                              if (f) void act(() => upload(selected, f));
                            }}
                          />
                        </label>
                        <Recorder
                          onReady={(f) => void act(() => upload(selected, f))}
                        />
                      </>
                    )}
                    {uploadProgress > 0 && (
                      <progress value={uploadProgress} max={100} />
                    )}
                    {selected.source && (
                      <a
                        className="download-link"
                        href={asset(selected, "source")}
                        download
                      >
                        ↓ Download original / recovery copy
                      </a>
                    )}
                  </section>
                  <section className="panel">
                    <h2>Check a short sample first</h2>
                    <p className="muted">
                      Process the first 30 seconds before committing to a full
                      lecture. Listen for code-switching accuracy and technical
                      terms.
                    </p>
                    <button
                      disabled={disabled || !selected.source}
                      onClick={() => job("sample")}
                    >
                      Run 30-second sample
                    </button>
                    {selected.sample && (
                      <div className="sample">
                        {selected.sample.map((s, i) => (
                          <div key={i}>
                            <b>
                              {times(s.start)} — {times(s.end)}
                            </b>
                            <p dir="auto">{s.original}</p>
                            <p>{s.english}</p>
                            <small>{s.flags.join(" · ")}</small>
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="divider" />
                    <button
                      disabled={
                        disabled ||
                        !selected.sample_ok ||
                        !!selected.segments?.length
                      }
                      onClick={() => job("process")}
                    >
                      Sample checked · Process full lecture →
                    </button>
                    <p className="tiny">
                      This starts paid transcription and translation in live
                      mode. Narration is a separate approval step.
                    </p>
                  </section>
                </div>
              )}
              {tab === "script" && (
                <>
                  <div className="editor-toolbar">
                    <div>
                      <h2>Review every explanation.</h2>
                      <p className="muted">
                        Save edits in each segment, check flagged passages, then
                        approve the script.
                      </p>
                    </div>
                    <button
                      disabled={disabled || !selected.segments?.length}
                      onClick={() =>
                        act(async () => {
                          if (
                            document.querySelector(
                              '.segment[data-dirty="true"]',
                            )
                          )
                            throw Error("Save your segment edits first.");
                          await api(`/lectures/${selected.id}/approve`, "POST");
                          await refresh();
                          setNotice(
                            "Current script approved. Open Voice to choose narration settings, then generate the preview.",
                          );
                        })
                      }
                    >
                      {selected.approved === selected.revision
                        ? "✓ Script approved"
                        : "Approve current script"}
                    </button>
                  </div>
                  <video
                    ref={video}
                    className="editor-video"
                    controls
                    src={
                      selected.source ? asset(selected, "source") : undefined
                    }
                  />
                  {selected.segments?.length ? (
                    selected.segments.map((s) => (
                      <Editor
                        key={s.id}
                        segment={s}
                        busy={disabled}
                        seek={() => {
                          if (video.current) {
                            video.current.currentTime = s.start;
                            void video.current.play();
                          }
                        }}
                        onSave={async (s, text, ack) => {
                          await act(async () => {
                            await api(
                              `/lectures/${selected.id}/segments/${s.id}`,
                              "PUT",
                              { english: text, acknowledged: ack },
                            );
                            await refresh();
                          });
                        }}
                        regenerate={() =>
                          act(async () => {
                            await api(
                              `/lectures/${selected.id}/regenerate/${s.id}`,
                              "POST",
                            );
                            await refresh();
                          })
                        }
                      />
                    ))
                  ) : (
                    <div className="empty">
                      <h3>Your script will appear here</h3>
                      <p>Process the lecture from Source & sample first.</p>
                    </div>
                  )}
                </>
              )}
              {tab === "voice" && (
                <section className="panel voice-panel">
                  <div className="eyebrow">AI-GENERATED VOICE</div>
                  <h2>A clear voice for your classroom.</h2>
                  <p className="muted">
                    Choose a standard synthetic English voice. Voice cloning is
                    outside this version.
                  </p>
                  <label className="field">
                    Voice
                    <select
                      value={voice}
                      onChange={(e) => setVoice(e.target.value)}
                      disabled={disabled}
                    >
                      <option>coral</option>
                      <option>alloy</option>
                      <option>sage</option>
                    </select>
                  </label>
                  <label className="field">
                    Pronunciation guidance
                    <textarea
                      value={pronunciation}
                      disabled={disabled}
                      onChange={(e) => setPronunciation(e.target.value)}
                      placeholder={
                        "secp256k1: say “seck P two fifty-six K one”\nRead a⁻¹ as “a inverse”.\nPause clearly around equations."
                      }
                    />
                  </label>
                  <p className="tiny">
                    Pronunciation instructions guide the voice; listen and
                    verify technical notation. Demo mode uses one basic offline
                    voice for every selection.
                  </p>
                  <div className="actions">
                    <button disabled={disabled} onClick={saveSettings}>
                      Save voice settings
                    </button>
                    <button
                      className="secondary"
                      disabled={
                        disabled ||
                        voice !== selected.voice ||
                        pronunciation !== selected.pronunciation
                      }
                      onClick={() => job("voice_preview")}
                    >
                      Generate short voice preview
                    </button>
                  </div>
                  <audio
                    key={selected.voice + (selected.jobs?.[0]?.status || "")}
                    controls
                    src={asset(selected, "voice.wav")}
                  />
                  <div className="divider" />
                  <button
                    disabled={
                      disabled ||
                      selected.approved !== selected.revision ||
                      voice !== selected.voice ||
                      pronunciation !== selected.pronunciation
                    }
                    onClick={() => job("preview")}
                  >
                    Generate narration & synchronized preview →
                  </button>
                  <p className="tiny">
                    Settings changes require renewed script approval. Unchanged
                    narration segments are cached.
                  </p>
                </section>
              )}
              {tab === "preview" && (
                <>
                  <div className="new-grid">
                    <section className="panel">
                      <h2>Synchronized English preview</h2>
                      {selected.preview ? (
                        <video
                          controls
                          preload="metadata"
                          crossOrigin="use-credentials"
                          src={asset(selected, "preview")}
                        >
                          {selected.exports["subtitles.vtt"] && (
                            <track
                              kind="captions"
                              src={asset(selected, "subtitles.vtt")}
                              srcLang="en"
                              label="English"
                            />
                          )}
                        </video>
                      ) : (
                        <div className="empty">
                          <h3>Ready when you approve.</h3>
                          <p>
                            Review the script, approve it, and generate
                            narration from Voice.
                          </p>
                        </div>
                      )}
                      <p className="tiny">
                        Video intervals stay in source order. Narration uses at
                        most 1.12× tempo, followed by frame holds where needed.
                        Watch continuous handwriting and demonstrations
                        carefully.
                      </p>
                    </section>
                    <section className="panel">
                      <h2>Export & student materials</h2>
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={burn}
                          onChange={(e) => setBurn(e.target.checked)}
                        />{" "}
                        Burn English captions into the MP4
                      </label>
                      {selected.timeline?.some((r) => r.review) && (
                        <label className="check flag">
                          <input
                            type="checkbox"
                            checked={acceptHolds}
                            onChange={(e) => setAcceptHolds(e.target.checked)}
                          />{" "}
                          I reviewed and accept the flagged frame holds below
                        </label>
                      )}
                      <button
                        disabled={disabled || !selected.preview}
                        onClick={() => job("export")}
                      >
                        Create final exports
                      </button>
                      <p className="tiny">
                        Creates MP4, SRT, VTT, full transcript, notes and timing
                        map. Notes use reviewed text only; screen equations are
                        not automatically extracted.
                      </p>
                      <div className="downloads">
                        {Object.keys(selected.exports || {}).map((name) => (
                          <a key={name} href={asset(selected, name)} download>
                            ↓ <span>{name}</span>
                            <small>Download ↗</small>
                          </a>
                        ))}
                      </div>
                    </section>
                  </div>
                  {selected.timeline?.length > 0 && (
                    <section className="panel timeline">
                      <h2>Alignment review</h2>
                      <div className="table-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>Source interval</th>
                              <th>English interval</th>
                              <th>Tempo</th>
                              <th>Frame hold</th>
                              <th>Review</th>
                            </tr>
                          </thead>
                          <tbody>
                            {selected.timeline.map((r, i) => (
                              <tr key={i}>
                                <td>
                                  {times(r.source_start)} →{" "}
                                  {times(r.source_end)}
                                </td>
                                <td>
                                  {times(r.final_start)} → {times(r.final_end)}
                                </td>
                                <td>{r.tempo.toFixed(2)}×</td>
                                <td>{r.hold.toFixed(2)}s</td>
                                <td>
                                  {r.review
                                    ? "⚑ Check screen activity"
                                    : r.id
                                      ? "Aligned"
                                      : "Source gap preserved"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </section>
                  )}
                </>
              )}
              <details className="usage">
                <summary>Processing history & provider usage</summary>
                {selected.jobs?.map((j) => (
                  <div key={j.id}>
                    <b>
                      {j.kind} · {j.status} · {j.stage}
                    </b>
                    {j.usage?.length > 0 && (
                      <pre>{JSON.stringify(j.usage, null, 2)}</pre>
                    )}
                  </div>
                ))}
              </details>
            </>
          )}
        </div>
        <footer>
          Lecture Studio <span>Teach once. Share with every section.</span>
        </footer>
      </main>
    </div>
  );
}
