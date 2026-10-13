"""Партия MT-32 -> General MIDI.

Номер программы в партии MT-32 — это ячейка patch memory, которую игра заполняет из
patch.001: ячейка указывает на встроенный тембр (группы A/B) или на собственный тембр
игры (группа MEM, у него есть имя). Встроенные тембры переводятся стандартной таблицей
MT-32 -> GM, собственные — по имени.
"""
import struct

from scisound import parse_events, _meta, _mtrk, CONTROL_CHANNEL, SCI_CONTROLLERS

# Встроенные тембры MT-32 (A: 0-63, B: 64-127) -> программа GM
MT32_TO_GM = [
    0, 1, 0, 2, 4, 4, 5, 3, 16, 17, 18, 16, 16, 19, 20, 21,
    6, 6, 6, 7, 7, 7, 8, 112, 62, 62, 63, 63, 38, 38, 39, 39,
    88, 95, 52, 98, 97, 99, 14, 54, 102, 96, 53, 102, 81, 100, 14, 80,
    48, 48, 49, 45, 41, 40, 42, 42, 43, 46, 45, 24, 25, 28, 27, 104,
    32, 32, 34, 33, 36, 37, 35, 35, 79, 73, 72, 72, 74, 75, 64, 65,
    66, 67, 71, 71, 68, 69, 70, 22, 56, 59, 57, 57, 60, 60, 58, 61,
    61, 11, 11, 98, 14, 9, 14, 13, 12, 107, 107, 77, 78, 78, 76, 76,
    47, 117, 127, 118, 118, 116, 115, 119, 115, 112, 55, 124, 123, 0, 14, 117,
]

# Собственные тембры LSL1 (по префиксу имени) -> программа GM
CUSTOM_TO_GM = {
    "AcouPiano": 0, "T-Bone": 57, "Banjo": 105, "StrSect": 48, "Oboe": 68,
    "FrHorn": 60, "Feed Back": 30, "SnglVox": 53, "Scrubin": 28, "Glock": 9,
    "TJBGtr": 24, "Calliope": 82, "WoodBlox": 115, "Thump": 116, "Pizz": 45,
    "RevHTonk": 3, "Arena": 16,
}
GM_SOUND_EFFECT = 122  # для тембров-звукоэффектов (Squirt, CarHorn, Toilet…)
GROUP_A, GROUP_B, GROUP_MEM, GROUP_RHYTHM = range(4)


def parse_mt32_patch(data):
    """patch.001 -> (список 96 патчей (group, timbre, key_shift), имена собственных тембров)."""
    p = 60 + 2 + 1 + 11 + 33  # 3 строки по 20, громкость, реверб, sysex реверба, таблица реверба
    patches = [tuple(data[p + i * 8:p + i * 8 + 3]) for i in range(48)]
    p += 48 * 8
    count = data[p]
    p += 1
    names = [data[p + i * 246:p + i * 246 + 10].decode("latin-1").strip() for i in range(count)]
    p += count * 246
    if struct.unpack_from(">H", data, p)[0] == 0xABCD:
        patches += [tuple(data[p + 2 + i * 8:p + 2 + i * 8 + 3]) for i in range(48)]
    return patches, names


def _roland_sysex(address, data, chunk=128):
    """Запись в память MT-32 (DT1), порезанная на куски; адрес — три 7-битных байта."""
    lin = (address >> 16) << 14 | ((address >> 8) & 0x7F) << 7 | (address & 0x7F)
    out = []
    for i in range(0, len(data), chunk):
        a = lin + i
        body = bytes((a >> 14 & 0x7F, a >> 7 & 0x7F, a & 0x7F)) + bytes(data[i:i + chunk])
        out.append(b"\x41\x10\x16\x12" + body + bytes(((-sum(body)) & 0x7F, 0xF7)))
    return out


def mt32_setup_sysex(data):
    """patch.001 -> SysEx (без F0), которыми драйвер MT32.DRV настраивает модуль перед игрой:
    текст на дисплее, patch memory 0–47, собственные тембры, patch memory 48–95, ритм-сет
    и резерв партиалов."""
    msgs = _roland_sysex(0x200000, data[0:20])
    p = 60 + 2 + 1 + 11 + 33
    msgs += _roland_sysex(0x050000, data[p:p + 48 * 8])
    p += 48 * 8
    count = data[p]
    p += 1
    for i in range(count):
        msgs += _roland_sysex(0x080000 + (i << 9), data[p:p + 246])
        p += 246
    if struct.unpack_from(">H", data, p)[0] == 0xABCD:
        msgs += _roland_sysex(0x050300, data[p + 2:p + 2 + 48 * 8])
        p += 2 + 48 * 8
    if struct.unpack_from(">H", data, p)[0] == 0xDCBA:
        msgs += _roland_sysex(0x030110, data[p + 2:p + 2 + 256])
        msgs += _roland_sysex(0x100004, data[p + 2 + 256:p + 2 + 256 + 9])
    return msgs


class GmMapper:
    def __init__(self, patch001):
        self.patches, self.names = parse_mt32_patch(patch001)

    def program(self, mt32_program):
        """-> (программа GM, сдвиг в полутонах)."""
        if mt32_program >= len(self.patches):
            return MT32_TO_GM[mt32_program & 0x7F], 0
        group, timbre, key_shift = self.patches[mt32_program]
        shift = key_shift - 24
        if group in (GROUP_A, GROUP_B):
            return MT32_TO_GM[group * 64 + timbre], shift
        if group == GROUP_MEM and timbre < len(self.names):
            name = self.names[timbre]
            for prefix, gm in CUSTOM_TO_GM.items():
                if name.startswith(prefix):
                    return gm, shift
        return GM_SOUND_EFFECT, shift


def to_gm_midi(channels, mapper, title, loop_tick=None):
    """SMF format 1 в General MIDI из каналов партии MT-32 (PPQN 30 при 120 BPM = 60 тиков/с)."""
    head = [_meta(0, 0x03, title.encode("latin-1", "replace")),
            _meta(0, 0x51, struct.pack(">I", 500000)[1:])]
    if loop_tick is not None:
        head.append(_meta(loop_tick, 0x06, b"loopStart"))
    tracks = [_mtrk(head)]
    for ch in channels:
        if ch.digital or ch.number == CONTROL_CHANNEL:
            continue
        events, _ = parse_events(ch.body)
        out = []
        shift = {}  # MIDI-канал -> сдвиг нот текущей программы
        for tick, kind, raw in events:
            if kind != "midi":
                continue  # sysex MT-32 в GM не нужен
            status, chan = raw[0] & 0xF0, raw[0] & 0x0F
            if chan == CONTROL_CHANNEL:
                continue
            if status == 0xB0 and raw[1] in SCI_CONTROLLERS:
                continue
            if status == 0xC0 and chan != 9:
                gm, shift[chan] = mapper.program(raw[1])
                raw = bytes((raw[0], gm))
            elif status in (0x80, 0x90) and chan != 9:
                note = min(127, max(0, raw[1] + shift.get(chan, 0)))
                raw = bytes((raw[0], note, raw[2]))
            out.append((tick, raw))
        if out:
            tracks.append(_mtrk(out))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), 30)
    return header + b"".join(tracks)
