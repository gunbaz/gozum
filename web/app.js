import { WavRecorder } from "./wav-recorder.js";

const STEP_INTERVAL_MS = 2500; // pause between frames while a goal is active
const FRAME_WIDTH = 768;
const DISCLAIMER =
  "Gözüm bir yön bulma yardımcısıdır. Baston, rehber köpek veya bir insanın yerine geçmez. " +
  "Yolun güvenli olduğuna karar vermez. Bir şey bulmak için düğmeye dokun ve hedefini söyle.";

const $ = (id) => document.getElementById(id);
const video = $("video");
const overlay = $("overlay");
const talk = $("talk");

const state = {
  started: false,
  sessionId: null,
  pendingGoal: null,
  awaitingReply: false,
  running: false,
  timer: null,
  recorder: null,
  wakeLock: null,
  voice: null,
};

// ---------- speech output: aria-live for screen readers + speechSynthesis ----------

function pickVoice() {
  const voices = speechSynthesis.getVoices();
  state.voice = voices.find((v) => v.lang?.toLowerCase().startsWith("tr")) || null;
}
if ("speechSynthesis" in window) {
  pickVoice();
  speechSynthesis.addEventListener("voiceschanged", pickVoice);
}

function say(text) {
  $("say").textContent = text;
  if (!("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  // Speak sentence by sentence: long utterances get cut off on some Chrome builds.
  for (const sentence of text.match(/[^.!?]+[.!?]?/g) || [text]) {
    const u = new SpeechSynthesisUtterance(sentence.trim());
    u.lang = "tr-TR";
    if (state.voice) u.voice = state.voice;
    speechSynthesis.speak(u);
  }
}

// ---------- camera, wake lock ----------

async function startCamera() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } },
    audio: false,
  });
  video.srcObject = stream;
  await video.play();
}

async function keepAwake() {
  try {
    state.wakeLock = await navigator.wakeLock?.request("screen");
  } catch {
    /* not supported or denied: the app still works, the screen may dim */
  }
}

function captureFrame() {
  const scale = FRAME_WIDTH / (video.videoWidth || FRAME_WIDTH);
  const canvas = document.createElement("canvas");
  canvas.width = FRAME_WIDTH;
  canvas.height = Math.round((video.videoHeight || 576) * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.7);
}

function drawBox(box) {
  const ctx = overlay.getContext("2d");
  overlay.width = overlay.clientWidth;
  overlay.height = overlay.clientHeight;
  ctx.clearRect(0, 0, overlay.width, overlay.height);
  if (!box) return;
  const [x0, y0, x1, y1] = box.map((v, i) => (v / 1000) * (i % 2 ? overlay.height : overlay.width));
  ctx.strokeStyle = "#ffd400";
  ctx.lineWidth = 4;
  ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
}

// ---------- agent loop ----------

function logTrace(entry) {
  const line = document.createElement("div");
  line.textContent = typeof entry === "string" ? entry : JSON.stringify(entry);
  $("trace").prepend(line);
}

function stopLoop() {
  state.running = false;
  clearTimeout(state.timer);
}

async function tick(reply) {
  if (!state.running) return;
  const body = { session_id: state.sessionId, frame: captureFrame() };
  if (state.pendingGoal) {
    body.goal = state.pendingGoal;
    state.pendingGoal = null;
  }
  if (reply) body.user_reply = reply;

  let data;
  try {
    const res = await fetch("/api/step", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.status);
    data = await res.json();
  } catch (err) {
    stopLoop();
    say("Bağlantı sorunu oldu. Tekrar denemek için düğmeye dokun.");
    logTrace(`hata: ${err.message}`);
    return;
  }

  state.sessionId = data.session_id;
  data.trace.forEach(logTrace);
  drawBox(data.box);
  say(data.speak);

  if (data.done) {
    stopLoop();
  } else if (data.awaiting_reply) {
    stopLoop();
    state.awaitingReply = true;
    talk.textContent = "Cevap vermek için dokun";
  } else {
    state.timer = setTimeout(() => tick(), STEP_INTERVAL_MS);
  }
}

function startGoal(goal) {
  stopLoop();
  state.awaitingReply = false;
  state.pendingGoal = goal;
  state.running = true;
  logTrace(`hedef: ${goal}`);
  say(`Tamam: ${goal}. Telefonu önüne tut.`);
  state.timer = setTimeout(() => tick(), 1200);
}

function reply(text) {
  state.awaitingReply = false;
  state.running = true;
  talk.textContent = "Konuşmak için dokun";
  logTrace(`cevap: ${text}`);
  tick(text);
}

function handleUtterance(text) {
  if (!text) {
    say("Seni duyamadım. Tekrar dokunup konuş.");
  } else if (state.awaitingReply) {
    reply(text);
  } else {
    startGoal(text);
  }
}

// ---------- first interaction, push-to-talk ----------

async function ensureStarted() {
  if (state.started) return;
  state.started = true;
  say(DISCLAIMER); // speaking inside a tap also unlocks audio on iOS
  try {
    await startCamera();
  } catch {
    say("Kameraya erişemedim. Tarayıcı izinlerini kontrol et.");
  }
  keepAwake();
}

talk.addEventListener("click", async () => {
  if (!state.started) {
    await ensureStarted();
    return;
  }
  if (!state.recorder) {
    stopLoop();
    window.speechSynthesis?.cancel();
    state.recorder = new WavRecorder();
    try {
      await state.recorder.start();
    } catch {
      state.recorder = null;
      say("Mikrofona erişemedim. Tarayıcı izinlerini kontrol et.");
      return;
    }
    talk.classList.add("recording");
    talk.textContent = "Dinliyorum… bitirince dokun";
    return;
  }
  const wav = await state.recorder.stop();
  state.recorder = null;
  talk.classList.remove("recording");
  talk.textContent = state.awaitingReply ? "Cevap vermek için dokun" : "Konuşmak için dokun";

  const form = new FormData();
  form.append("audio", wav, "speech.wav");
  try {
    const res = await fetch("/api/transcribe", { method: "POST", body: form });
    if (!res.ok) throw new Error(res.status);
    const { text } = await res.json();
    logTrace(`duyulan: ${text}`);
    handleUtterance(text);
  } catch (err) {
    say("Sesini yazıya çeviremedim. Tekrar dene veya yazarak hedef ver.");
    logTrace(`hata: ${err.message}`);
  }
});

$("typed").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("goal").value.trim();
  $("goal").value = "";
  await ensureStarted();
  handleUtterance(text);
});

$("stop").addEventListener("click", () => {
  stopLoop();
  state.awaitingReply = false;
  window.speechSynthesis?.cancel();
  say("Durdurdum.");
});

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && state.started) keepAwake();
});

fetch("/api/health")
  .then((r) => r.json())
  .then((h) => {
    if (h.mock) $("mock").style.display = "inline-block";
  })
  .catch(() => {});
