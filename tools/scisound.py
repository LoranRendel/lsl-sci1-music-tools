"""Разбор звуковых ресурсов SCI1 и конвертация в Standard MIDI File / WAV."""
import struct
import wave

DEVICES = {
    0x00: "adlib",    # SNDBLAST.DRV, ADL.DRV, PROAUDIO.DRV (OPL2, patch 3)
    0x06: "dev06",    # ни один драйвер из комплекта не запрашивает
    0x09: "cms",      # CMS.DRV (patch 101)
    0x0C: "mt32",     # MT32.DRV, MTBLAST.DRV (patch 1)
    0x12: "speaker",  # STD.DRV
    0x13: "tandy",    # TANDY3V.DRV, IBMPS1.DRV (patch 101)
    0x16: "dev16",    # ни один драйвер из комплекта не запрашивает
}
TICKS_PER_SECOND = 60
CONTROL_CHANNEL = 15
LOOP_POINT = 127
# Контроллеры, которые понимает только звуковая система Sierra.
SCI_CONTROLLERS = {0x4B, 0x4C, 0x4E, 0x50, 0x51, 0x52, 0x60}


class Channel:
    def __init__(self, data, offset, size):
        self.offset = offset
        self.size = size
        self.number = data[offset]
        self.poly = data[offset + 1] & 0x0F
        self.prio = data[offset + 1] >> 4
        self.body = data[offset + 2:offset + size]
        self.digital = self.number == 0xFE

    def sample(self):
        """(rate, pcm) для цифрового канала: 8-бит unsigned PCM."""
        rate, size, _loop_start, _loop_end = struct.unpack_from("<4H", self.body, 0)
        return rate, self.body[8:8 + size]


def parse_sound(data):
    """Возвращает список (device_id, [Channel]) в порядке следования в ресурсе."""
    tracks, p = [], 0
    while data[p] != 0xFF:
        device = data[p]
        p += 1
        entries = []
        while data[p] != 0xFF:
            entries.append(struct.unpack_from("<HHH", data, p))
            p += 6
        p += 1
        if device == 0xF0:  # служебная дорожка, каналов-данных не содержит
            continue
        tracks.append((device, [Channel(data, off, size) for _unk, off, size in entries]))
    return tracks


def parse_events(body):
    """Поток канала -> [(abs_tick, kind, payload)], kind: 'midi' | 'sysex'."""
    events, p, status, tick = [], 0, 0, 0
    while p < len(body):
        while body[p] == 0xF8:
            tick += 240
            p += 1
        tick += body[p]
        p += 1
        if body[p] & 0x80:
            status = body[p]
            p += 1
        if status == 0xFC:
            break
        kind = status & 0xF0
        if kind in (0xC0, 0xD0):
            events.append((tick, "midi", bytes((status, body[p]))))
            p += 1
        elif kind in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
            events.append((tick, "midi", bytes((status, body[p], body[p + 1]))))
            p += 2
        elif status == 0xF0:
            end = body.index(0xF7, p)
            events.append((tick, "sysex", body[p:end + 1]))
            p = end + 1
        else:
            raise ValueError(f"неизвестный статус 0x{status:02X} на позиции {p}")
    return events, tick


def _varlen(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def _meta(tick, mtype, payload):
    return tick, bytes((0xFF, mtype)) + _varlen(len(payload)) + payload


def _mtrk(events):
    out, last = bytearray(), 0
    for tick, raw in sorted(events, key=lambda e: e[0]):
        out += _varlen(tick - last) + raw
        last = tick
    out += b"\x00\xFF\x2F\x00"
    return b"MTrk" + struct.pack(">I", len(out)) + out


def to_midi(channels, title, setup=()):
    """SMF format 1: дорожка темпа + по дорожке на канал SCI.

    Тики SCI идут с частотой 60 Гц: PPQN 30 при темпе 120 BPM даёт ровно 60 тиков/с.
    События управляющего канала 15 (точка цикла, cue) записываются маркерами.
    setup — SysEx (без F0), которые нужно отправить до начала (настройка MT-32): они идут
    по одному в 2 тика (настоящему MT-32 нужны паузы), мелодия сдвигается на это время.
    """
    lead = 2 * len(setup)
    tempo = [_meta(0, 0x03, title.encode("latin-1", "replace")),
             _meta(0, 0x51, struct.pack(">I", 500000)[1:])]
    tempo += [(2 * i, b"\xF0" + _varlen(len(s)) + s) for i, s in enumerate(setup)]
    tracks = [_mtrk(tempo)]
    for ch in channels:
        if ch.digital:
            continue
        events, _ = parse_events(ch.body)
        out = [_meta(0, 0x03, f"SCI channel {ch.number} poly={ch.poly} prio={ch.prio}".encode("ascii"))]
        for tick, kind, raw in events:
            tick += lead
            if kind == "sysex":
                out.append((tick, b"\xF0" + _varlen(len(raw)) + raw))
                continue
            status = raw[0]
            if status & 0x0F == CONTROL_CHANNEL:
                if status & 0xF0 == 0xC0:
                    text = "loop" if raw[1] == LOOP_POINT else f"cue {raw[1]}"
                    out.append(_meta(tick, 0x06, text.encode("ascii")))
                continue
            if status & 0xF0 == 0xB0 and raw[1] in SCI_CONTROLLERS:
                continue
            out.append((tick, raw))
        tracks.append(_mtrk(out))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), 30)
    return header + b"".join(tracks)


def write_wav(path, rate, pcm):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(rate)
        w.writeframes(pcm)
