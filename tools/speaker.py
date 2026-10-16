"""Партия PC-спикера как лог: делитель таймера PIT на каждый тик (60 Гц), 0 — тишина.

Спикер умеет только меандр одной частоты, поэтому этот лог — всё, что драйвер STD.DRV
делает со звуком, и он точный (как VGM для AdLib). Из него строятся модуль Furnace
(furnace.py) и HTML-проигрыватель.

Файл лога (.spk.gz) — gzip от:
    "SPKL" | u8 версия = 1 | u8 тиков/с = 60 | u16 0 | u32 число тиков | i32 тик цикла (-1 нет)
    | u16 делитель × число тиков
"""
import base64
import gzip
import html
import json
import os
import struct

import chips
from sciplayer import CARDS, Song, run
from scisound import TICKS_PER_SECOND

SPEAKER = 0x12
MAGIC = b"SPKL"


def speaker_log(rm, channels):
    """Каналы дорожки спикера -> (делители по тикам, тик цикла или None).

    Хвост после конца мелодии не нужен: у спикера нет затухания."""
    card = next(c for c in CARDS if c.device == SPEAKER)
    song = Song(channels)
    drv, init = card.start(rm)
    sp = chips.Speaker()
    for port, value in init:
        sp.write(port, value)
    divisors = []
    for writes in run(drv, song, tail=False):
        for port, value in writes:
            sp.write(port, value)
        divisors.append(sp.divisor if sp.gate and sp.divisor else 0)
    return divisors, song.loop_tick


def write_log(path, divisors, loop_tick):
    data = MAGIC + struct.pack("<BBHIi", 1, TICKS_PER_SECOND, 0, len(divisors),
                               -1 if loop_tick is None else loop_tick)
    data += struct.pack(f"<{len(divisors)}H", *divisors)
    with gzip.open(path, "wb", 9) as f:
        f.write(data)


def read_log(path):
    with gzip.open(path, "rb") as f:
        data = f.read()
    if data[:4] != MAGIC:
        raise ValueError(f"{path}: не лог спикера")
    _ver, _rate, _res, count, loop = struct.unpack_from("<BBHIi", data, 4)
    divisors = list(struct.unpack_from(f"<{count}H", data, 16))
    return divisors, None if loop < 0 else loop


def changes(divisors):
    """[(тик, делитель)] — только моменты, когда делитель меняется."""
    out, last = [], None
    for tick, d in enumerate(divisors):
        if d != last:
            out.append((tick, d))
            last = d
    return out


def write_player(log_dir, path, album):
    """HTML-проигрыватель всех логов из log_dir (WebAudio, меандр как у спикера)."""
    songs = []
    for name in sorted(os.listdir(log_dir)):
        if not name.endswith(".spk.gz"):
            continue
        divisors, loop = read_log(os.path.join(log_dir, name))
        flat = [v for pair in changes(divisors) for v in pair]
        songs.append({"title": name[:-len(".spk.gz")], "ticks": len(divisors), "loop": loop,
                      "ev": base64.b64encode(struct.pack(f"<{len(flat)}I", *flat)).decode()})
    page = PLAYER_HTML.replace("__ALBUM__", html.escape(album))
    page = page.replace("__SONGS__", json.dumps(songs, ensure_ascii=False).replace("</", "<\\/"))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)


PLAYER_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PC Speaker Player</title>
<style>
:root {
  --bg: #f4f1ea; --panel: #fffdf8; --ink: #1d1b16; --muted: #6b665c; --line: #ddd6c8;
  --accent: #b4441c; --accent-ink: #fff; --hover: #efe9dd;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #15140f; --panel: #1e1c17; --ink: #ece6d8; --muted: #9a9384; --line: #34302a;
    --accent: #e0703f; --accent-ink: #15140f; --hover: #2a2721;
  }
}
:root[data-theme="dark"] {
  --bg: #15140f; --panel: #1e1c17; --ink: #ece6d8; --muted: #9a9384; --line: #34302a;
  --accent: #e0703f; --accent-ink: #15140f; --hover: #2a2721;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 20px; margin: 0 0 2px; }
.sub { color: var(--muted); margin: 0 0 20px; font-size: 13px; }
.deck { position: sticky; top: 0; background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; padding: 14px 16px; margin-bottom: 16px; z-index: 1; }
.now { font-weight: 600; min-height: 1.45em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row { display: flex; align-items: center; gap: 12px; margin-top: 10px; flex-wrap: wrap; }
button { font: inherit; border: 1px solid var(--line); background: var(--panel); color: var(--ink);
  border-radius: 6px; padding: 5px 12px; cursor: pointer; }
button.main { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); min-width: 84px; }
button:focus-visible, input:focus-visible, li:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.bar { flex: 1 1 200px; height: 6px; background: var(--line); border-radius: 3px; position: relative; cursor: pointer; }
.fill { position: absolute; inset: 0 auto 0 0; width: 0; background: var(--accent); border-radius: 3px; }
.mark { position: absolute; top: -3px; width: 2px; height: 12px; background: var(--muted); display: none; }
.time { font-variant-numeric: tabular-nums; color: var(--muted); font-size: 13px; }
label { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-size: 13px; }
ol { list-style: none; margin: 0; padding: 0; border: 1px solid var(--line); border-radius: 10px;
  background: var(--panel); overflow: hidden; }
li { display: flex; gap: 12px; padding: 8px 14px; border-top: 1px solid var(--line); cursor: pointer; }
li:first-child { border-top: 0; }
li:hover { background: var(--hover); }
li.on { color: var(--accent); font-weight: 600; }
li .t { flex: 1; min-width: 0; overflow-wrap: anywhere; }
li .d { color: var(--muted); font-variant-numeric: tabular-nums; font-size: 13px; }
</style>
</head>
<body>
<main>
  <h1>PC Speaker</h1>
  <p class="sub">__ALBUM__ — партия спикера, восстановленная из записей драйвера STD.DRV в таймер (60 тиков/с)</p>
  <section class="deck" aria-label="Проигрыватель">
    <div class="now" id="now">Выберите мелодию</div>
    <div class="row">
      <button class="main" id="play" disabled>▶ Играть</button>
      <div class="bar" id="bar" role="slider" aria-label="Позиция" tabindex="0"><div class="fill" id="fill"></div><div class="mark" id="mark" title="Точка цикла"></div></div>
      <span class="time" id="time">0:00 / 0:00</span>
    </div>
    <div class="row">
      <label><input type="checkbox" id="loop" checked> Повтор (с точки цикла ↻, если есть)</label>
      <label><input type="checkbox" id="next" checked> Затем следующая</label>
      <label>Громкость <input type="range" id="vol" min="0" max="100" value="35"></label>
    </div>
  </section>
  <ol id="list"></ol>
</main>
<script>
const SONGS = __SONGS__;
const PIT = 1193182, RATE = 60, AHEAD = 0.6;
const $ = id => document.getElementById(id);
const fmt = s => Math.floor(s / 60) + ":" + String(Math.floor(s % 60)).padStart(2, "0");

for (const s of SONGS) {
  const raw = Uint8Array.from(atob(s.ev), c => c.charCodeAt(0));
  const v = new Uint32Array(raw.buffer);
  s.events = [];
  for (let i = 0; i < v.length; i += 2) s.events.push([v[i], v[i + 1]]);
}

let ctx = null, gain = null, osc = null, master = null;
let cur = -1, playing = false, timer = null;
let startTime = 0, startTick = 0, schedTick = 0, idx = 0;

function audio() {
  if (!ctx) {
    ctx = new AudioContext();
    master = ctx.createGain();
    master.connect(ctx.destination);
    setVolume();
  }
  return ctx;
}
function setVolume() { if (master) master.gain.value = ($("vol").value / 100) ** 2 * 0.5; }

function stopVoice() {
  if (osc) { try { osc.stop(); } catch (e) {} osc.disconnect(); osc = null; }
  if (gain) { gain.disconnect(); gain = null; }
}

// Ставит в очередь события с тика `from`; время тика t = startTime + (t - startTick) / RATE.
function seek(tick) {
  stopVoice();
  const c = audio();
  osc = c.createOscillator(); osc.type = "square";
  gain = c.createGain(); gain.gain.value = 0;
  osc.connect(gain); gain.connect(master);
  startTime = c.currentTime + 0.05; startTick = tick;
  const ev = SONGS[cur].events;
  idx = 0;
  while (idx + 1 < ev.length && ev[idx + 1][0] <= tick) idx++;
  apply(ev[idx][1], startTime);
  idx++;
  schedTick = tick;
  osc.start(startTime);
  pump();
}
function apply(div, t) {
  if (div) { osc.frequency.setValueAtTime(PIT / div, t); gain.gain.setValueAtTime(1, t); }
  else gain.gain.setValueAtTime(0, t);
}
function pump() {
  if (!playing) return;
  const s = SONGS[cur], ev = s.events;
  const until = startTick + (ctx.currentTime + AHEAD - startTime) * RATE;
  while (idx < ev.length && ev[idx][0] <= until) {
    apply(ev[idx][1], startTime + (ev[idx][0] - startTick) / RATE);
    idx++;
  }
  schedTick = until;
  if (idx >= ev.length && until >= s.ticks) {
    const endTime = startTime + (s.ticks - startTick) / RATE;
    if ($("loop").checked) {
      // Продолжаем с точки цикла (у мелодий без неё — с начала) без разрыва:
      // сдвигаем начало отсчёта
      const from = s.loop ?? 0;
      startTime = endTime; startTick = from;
      idx = 0;
      while (idx + 1 < ev.length && ev[idx + 1][0] <= from) idx++;
      apply(ev[idx][1], startTime); idx++;
    } else if (ctx.currentTime >= endTime) {
      gain.gain.setValueAtTime(0, endTime);
      if ($("next").checked && cur + 1 < SONGS.length) { select(cur + 1, true); return; }
      stop(); return;
    } else {
      gain.gain.setValueAtTime(0, endTime);
    }
  }
  draw();
  timer = setTimeout(pump, 100);
}
function position() {
  if (!playing) return startTick;
  return Math.min(SONGS[cur].ticks, startTick + Math.max(0, ctx.currentTime - startTime) * RATE);
}
function draw() {
  if (cur < 0) return;
  const s = SONGS[cur], p = position();
  $("fill").style.width = (100 * p / s.ticks) + "%";
  $("time").textContent = fmt(p / RATE) + " / " + fmt(s.ticks / RATE);
}
function play() {
  audio().resume();
  playing = true; $("play").textContent = "■ Стоп";
  seek(startTick >= SONGS[cur].ticks ? 0 : startTick);
}
function stop() {
  startTick = position();
  playing = false; clearTimeout(timer); stopVoice();
  $("play").textContent = "▶ Играть"; draw();
}
function select(i, autoplay) {
  if (playing) { playing = false; clearTimeout(timer); stopVoice(); }
  cur = i; startTick = 0;
  const s = SONGS[i];
  $("now").textContent = s.title;
  $("play").disabled = false;
  const mark = $("mark");
  if (s.loop !== null) { mark.style.display = "block"; mark.style.left = (100 * s.loop / s.ticks) + "%"; }
  else mark.style.display = "none";
  document.querySelectorAll("li").forEach((li, k) => li.classList.toggle("on", k === i));
  saveHash();
  if (autoplay) play(); else { $("play").textContent = "▶ Играть"; draw(); }
}

// Состояние в адресе: #song=390&loop=1&next=1&vol=35 — ссылку можно сохранить или передать.
// Песня по номеру звука (начало названия до « - »).
const songId = s => s.title.split(" - ")[0];
function saveHash() {
  const p = new URLSearchParams();
  if (cur >= 0) p.set("song", songId(SONGS[cur]));
  p.set("loop", $("loop").checked ? 1 : 0);
  p.set("next", $("next").checked ? 1 : 0);
  p.set("vol", $("vol").value);
  const hash = "#" + p.toString();
  if (location.hash !== hash) history.replaceState(null, "", hash);
}
function loadHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  if (p.has("loop")) $("loop").checked = p.get("loop") !== "0";
  if (p.has("next")) $("next").checked = p.get("next") !== "0";
  const vol = parseInt(p.get("vol"), 10);
  if (vol >= 0 && vol <= 100) { $("vol").value = vol; setVolume(); }
  const i = SONGS.findIndex(s => songId(s) === p.get("song"));
  // Без нажатия браузер не даст начать звук, поэтому песня только выбирается
  if (i >= 0 && i !== cur) select(i, playing);
}

const list = $("list");
SONGS.forEach((s, i) => {
  const li = document.createElement("li");
  li.tabIndex = 0;
  li.innerHTML = '<span class="t"></span><span class="d"></span>';
  li.querySelector(".t").textContent = s.title;
  li.querySelector(".d").textContent = fmt(s.ticks / RATE) + (s.loop !== null ? " ↻" : "");
  li.onclick = () => select(i, true);
  li.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(i, true); } };
  list.appendChild(li);
});
$("play").onclick = () => playing ? stop() : play();
$("vol").oninput = () => { setVolume(); saveHash(); };
$("loop").onchange = $("next").onchange = saveHash;
window.addEventListener("hashchange", loadHash);
loadHash();
saveHash();
function seekTo(frac) {
  if (cur < 0) return;
  const t = Math.round(Math.max(0, Math.min(1, frac)) * SONGS[cur].ticks);
  if (playing) seek(t); else { startTick = t; draw(); }
}
$("bar").onclick = e => { const r = $("bar").getBoundingClientRect(); seekTo((e.clientX - r.left) / r.width); };
$("bar").onkeydown = e => {
  if (cur < 0) return;
  const step = { ArrowLeft: -5, ArrowRight: 5 }[e.key];
  if (step) { e.preventDefault(); seekTo((position() + step * RATE) / SONGS[cur].ticks); }
};
</script>
</body>
</html>
"""
