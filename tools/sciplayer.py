"""Проигрывание мелодии SCI1 через настоящий драйвер и запись результата.

Роль интерпретатора: раз в тик (60 Гц) вызвать сервисную функцию драйвера и передать ему
MIDI-события этого тика. Драйвер сам распределяет голоса и пишет в порты; записи
собираются по тикам и превращаются в WAV (OPL2 — через эмулятор pyopl, спикер —
модели микросхем из chips.py) или в VGM (журнал записей в YM3812).
"""
import gzip
import os
import struct
import subprocess

import numpy as np

import chips
from drvemu import (Driver, FN_INIT, FN_TICK, FN_NOTE_OFF, FN_NOTE_ON, FN_CONTROLLER,
                    FN_PROGRAM, FN_PITCH_BEND)
from scisound import parse_events, CONTROL_CHANNEL, LOOP_POINT, TICKS_PER_SECOND

RATE = 44100
SAMPLES_PER_TICK = RATE // TICKS_PER_SECOND  # 735 — ровно один wait 0x62 в VGM
TAIL_TICKS = 2 * TICKS_PER_SECOND             # «хвост» на затухание нот после конца
OPL_INDEX, OPL_DATA = 0x388, 0x389
GAME_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MIDI_FN = {0x80: FN_NOTE_OFF, 0x90: FN_NOTE_ON, 0xB0: FN_CONTROLLER, 0xC0: FN_PROGRAM,
           0xE0: FN_PITCH_BEND}


class Song:
    """События каналов одной дорожки, слитые по времени."""

    def __init__(self, channels):
        self.channels = [c for c in channels if not c.digital]
        self.events = []  # (tick, порядок, bytes)
        self.end_tick = 0
        self.loop_tick = None
        for order, ch in enumerate(self.channels):
            events, end = parse_events(ch.body)
            self.end_tick = max(self.end_tick, end)
            for i, (tick, kind, raw) in enumerate(events):
                if kind != "midi":
                    continue
                if raw[0] & 0x0F == CONTROL_CHANNEL:
                    if raw[0] & 0xF0 == 0xC0 and raw[1] == LOOP_POINT:
                        self.loop_tick = tick  # действует последняя точка цикла
                    continue
                self.events.append((tick, order, i, raw))
        self.events.sort()

    def init_messages(self):
        """Что интерпретатор посылает драйверу перед стартом мелодии."""
        msgs = []
        used = sorted({ev[3][0] & 0x0F for ev in self.events})
        for ch in self.channels:
            if ch.number != CONTROL_CHANNEL:
                msgs.append(bytes((0xB0 | ch.number, 0x4B, ch.poly)))
        for c in used:
            msgs += [bytes((0xB0 | c, 0x07, 127)), bytes((0xB0 | c, 0x0A, 64)),
                     bytes((0xE0 | c, 0x00, 0x40))]
        return msgs


def send(driver, raw):
    fn = MIDI_FN.get(raw[0] & 0xF0)
    if fn == FN_NOTE_ON and raw[2] == 0:
        # Конец ноты в данных Sierra — note-on с громкостью 0. Интерпретатор передаёт его
        # как note-off: STD.DRV громкость не проверяет и иначе запустил бы ноту заново.
        fn = FN_NOTE_OFF
    if fn is None:
        return
    p1 = raw[1]
    p2 = raw[2] if len(raw) > 2 else 0
    if fn == FN_PROGRAM:
        p1, p2 = 0, raw[1]  # программа передаётся в CL
    driver.call(fn, ax=raw[0] & 0x0F, cx=(p1 << 8) | p2)


def run(driver, song, tail=True):
    """Возвращает список записей в порты по тикам: [[(port, value), ...], ...]."""
    for raw in song.init_messages():
        send(driver, raw)
    driver.take_writes()  # инициализационные записи относим к тику 0
    ticks, i = [], 0
    total = song.end_tick + (TAIL_TICKS if tail else 0)
    for tick in range(total + 1):
        driver.call(FN_TICK)
        while i < len(song.events) and song.events[i][0] == tick:
            send(driver, song.events[i][3])
            i += 1
        ticks.append(driver.take_writes())
    return ticks


class Card:
    """Звуковая карта: драйвер, его патч, дорожка в звуковом ресурсе и модель микросхемы."""

    def __init__(self, key, title, driver, patch, device, chip, on_int=None):
        self.key, self.title, self.driver, self.patch = key, title, driver, patch
        self.device, self.chip, self.on_int = device, chip, on_int

    def start(self, rm):
        """Загружает и инициализирует драйвер; -> (driver, записи в порты при init)."""
        drv = Driver(os.path.join(rm.game_dir, self.driver), on_int=self.on_int)
        if self.patch is None:
            drv.call(FN_INIT)
        else:
            seg, off = drv.put_data(rm.load(9, self.patch))
            drv.call(FN_INIT, ax=off, es=seg)
        return drv, drv.take_writes()

    def render(self, rm, channels):
        """Каналы дорожки -> float32 [samples, channels] (с хвостом на затухание)."""
        drv, init = self.start(rm)
        return chips.render(self.chip(), init, run(drv, Song(channels)), SAMPLES_PER_TICK)


def _no_mvsound(uc, intno):
    """PROAUDIO.DRV спрашивает через INT 2Fh про MVSOUND.SYS — отвечаем «не установлен»."""


# Карты, чьи партии различаются по звучанию. AdLib и Sound Blaster играют музыку одинаково
# (OPL-поток ADL.DRV и SNDBLAST.DRV совпадает), MT-32 без ПЗУ синтезировать нечем.
CARDS = [
    Card("speaker", "PC-спикер", "STD.DRV", None, 0x12, chips.Speaker),
    Card("soundblaster", "AdLib / Sound Blaster", "ADL.DRV", 3, 0x00, chips.OPL2),
    Card("proaudio", "Pro AudioSpectrum (стерео)", "PROAUDIO.DRV", 3, 0x00, chips.OPL2Stereo, _no_mvsound),
    Card("cms", "Creative Music System / Game Blaster", "CMS.DRV", 101, 0x09, chips.SAA1099Pair),
    Card("tandy", "Tandy 1000 (3 голоса)", "TANDY3V.DRV", 101, 0x13, lambda: chips.SN76496(0x1E0)),
    Card("ps1", "IBM PS/1 Audio", "IBMPS1.DRV", 101, 0x13, lambda: chips.SN76496(0x205)),
]


def write_flac(audio, path, tags=None, peak=0.89):
    """float32 [samples, channels] -> 16-бит FLAC (через ffmpeg), с нормализацией по пику."""
    top = float(np.abs(audio).max())
    if top > 0:
        audio = audio * (peak / top)
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(RATE),
           "-ac", str(audio.shape[1]), "-i", "-"]
    for key, value in (tags or {}).items():
        cmd += ["-metadata", f"{key}={value}"]
    cmd += ["-c:a", "flac", "-compression_level", "8", path]
    subprocess.run(cmd, input=(audio * 32767).astype("<i2").tobytes(), check=True)


def opl_register_writes(writes):
    """(port, value) -> [(reg, value)] для OPL."""
    out, index = [], 0
    for port, value in writes:
        if port == OPL_INDEX:
            index = value
        elif port == OPL_DATA:
            out.append((index, value))
    return out


def _gd3(title, game, system, author, notes):
    strings = [title, "", game, "", system, "", author, "", "1991", "", notes]
    body = b"".join(s.encode("utf-16-le") + b"\0\0" for s in strings)
    return b"Gd3 " + struct.pack("<II", 0x100, len(body)) + body


def write_vgm(init, ticks, loop_tick, path, title, author="", notes=""):
    """VGM 1.51 с YM3812 (OPL2), 735 сэмплов на тик; loop_tick — точка повтора или None.
    Файл с расширением .vgz пишется сжатым gzip (так VGZ и устроен)."""
    data, loop_offset = bytearray(), None
    for reg, val in opl_register_writes(init):
        data += bytes((0x5A, reg, val))
    for n, writes in enumerate(ticks):
        if loop_tick is not None and n == loop_tick:
            loop_offset = len(data)
        for reg, val in opl_register_writes(writes):
            data += bytes((0x5A, reg, val))
        data += b"\x62"
    data += b"\x66"
    header_size = 0x80
    gd3 = _gd3(title, "Leisure Suit Larry 1: In the Land of the Lounge Lizards (VGA)",
               "IBM PC / AdLib (Sound Blaster)", author,
               notes or "Записано с ADL.DRV из игры, эмуляция драйвера")
    total = len(ticks) * SAMPLES_PER_TICK
    hdr = bytearray(header_size)
    hdr[0:4] = b"Vgm "
    struct.pack_into("<I", hdr, 0x04, header_size + len(data) + len(gd3) - 4)
    struct.pack_into("<I", hdr, 0x08, 0x151)
    struct.pack_into("<I", hdr, 0x14, header_size + len(data) - 0x14)
    struct.pack_into("<I", hdr, 0x18, total)
    if loop_offset is not None:
        struct.pack_into("<I", hdr, 0x1C, header_size + loop_offset - 0x1C)
        struct.pack_into("<I", hdr, 0x20, (len(ticks) - loop_tick) * SAMPLES_PER_TICK)
    struct.pack_into("<I", hdr, 0x34, header_size - 0x34)
    struct.pack_into("<I", hdr, 0x50, 3579545)  # YM3812
    opener = gzip.open if path.lower().endswith(".vgz") else open
    with opener(path, "wb") as f:
        f.write(hdr + data + gd3)
