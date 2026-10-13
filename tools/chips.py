"""Простые модели звуковых микросхем по записям в порты (с точностью до тика).

Драйверы CMS и Tandy/PS/1 в мелодиях LSL1 используют только тоновые каналы (без шума и
огибающих), поэтому достаточно меандров с нужной частотой и громкостью. Меандры строятся с
передискретизацией, чтобы не было алиасинга.
"""
import numpy as np

RATE = 44100
OVERSAMPLE = 16
PIT_CLOCK = 1193182
SN_CLOCK = 3579545   # SN76496 в Tandy 1000 / IBM PS/1
SAA_CLOCK = 7159090  # SAA1099 на Creative Music System / Game Blaster


class SquareBank:
    """Набор меандров с непрерывной фазой; render() — один отрезок для всех голосов."""

    def __init__(self):
        self.phase = {}

    def render(self, voices, samples, channels):
        """voices: [(key, freq, [amp по каналам])] -> float32 [samples, channels]."""
        out = np.zeros((samples, channels), dtype=np.float32)
        n = samples * OVERSAMPLE
        for key, freq, amps in voices:
            if freq <= 0 or not any(amps):
                continue
            step = freq / (RATE * OVERSAMPLE)
            ph = self.phase.get(key, 0.0)
            t = ph + np.arange(n) * step
            wave = np.where((t % 1.0) < 0.5, 1.0, -1.0).reshape(samples, OVERSAMPLE).mean(axis=1)
            self.phase[key] = (ph + n * step) % 1.0
            for c in range(channels):
                if amps[c]:
                    out[:, c] += wave * amps[c]
        return out


class SquareChip:
    """Микросхема, звук которой — набор меандров (voices())."""

    def tick(self, samples):
        if not hasattr(self, "_bank"):
            self._bank = SquareBank()
        return self._bank.render(self.voices(), samples, self.channels)


class OPL2:
    """Одна OPL2 (AdLib / Sound Blaster): индекс 0x388, данные 0x389. Эмулятор — pyopl."""
    channels = 1
    ports = {0x388: (0,)}

    def __init__(self):
        import pyopl
        self.chips = [pyopl.opl(RATE, 2, 1) for _ in range(self.channels)]
        self.index = {}

    def write(self, port, value):
        if port in self.ports:
            self.index[port] = value
        elif port - 1 in self.ports:
            for c in self.ports[port - 1]:
                self.chips[c].writeReg(self.index.get(port - 1, 0), value)

    def tick(self, samples):
        out = np.zeros((samples, self.channels), dtype=np.float32)
        for c, chip in enumerate(self.chips):
            done = 0
            while done < samples:  # pyopl отдаёт не больше 512 сэмплов за вызов
                n = min(512, samples - done)
                buf = bytearray(n * 2)
                chip.getSamples(buf)
                out[done:done + n, c] = np.frombuffer(bytes(buf), "<i2") / 32768
                done += n
        return out


class OPL2Stereo(OPL2):
    """Pro AudioSpectrum: две OPL2. 0x788 — запись в обе, 0x388 — левая, 0x38A — правая
    (через них драйвер пишет только уровни операторов, то есть панораму)."""
    channels = 2
    ports = {0x788: (0, 1), 0x388: (0,), 0x38A: (1,)}


class Speaker(SquareChip):
    """PIT канал 2 (порты 0x42/0x43) + ворота спикера (порт 0x61, биты 0 и 1)."""
    channels = 1

    def __init__(self, amplitude=0.3):
        self.divisor, self.gate, self.lo, self.amp = 0, False, None, amplitude

    def write(self, port, value):
        if port == 0x43:
            self.lo = None
        elif port == 0x42:
            if self.lo is None:
                self.lo = value
            else:
                self.divisor, self.lo = self.lo | value << 8, None
        elif port == 0x61:
            self.gate = value & 3 == 3

    def voices(self):
        if self.gate and self.divisor:
            return [(0, PIT_CLOCK / self.divisor, [self.amp])]
        return []


class SN76496(SquareChip):
    """3 тоновых канала: f = clock / (32 * N), затухание 2 дБ на шаг, 15 — тишина."""
    channels = 1

    def __init__(self, port, amplitude=0.22):
        self.port, self.amp = port, amplitude
        self.period = [0] * 4
        self.atten = [15] * 4
        self.latch = (0, False)

    def write(self, port, value):
        if port != self.port:
            return
        if value & 0x80:
            ch, is_vol = (value >> 5) & 3, bool(value & 0x10)
            self.latch = (ch, is_vol)
            if is_vol:
                self.atten[ch] = value & 0x0F
            else:
                self.period[ch] = (self.period[ch] & 0x3F0) | (value & 0x0F)
        else:
            ch, is_vol = self.latch
            if is_vol:
                self.atten[ch] = value & 0x0F
            else:
                self.period[ch] = (self.period[ch] & 0x0F) | ((value & 0x3F) << 4)

    def voices(self):
        out = []
        for ch in range(3):
            if self.atten[ch] < 15:
                n = self.period[ch] or 1024
                out.append((ch, SN_CLOCK / (32 * n), [self.amp * 10 ** (-self.atten[ch] * 2 / 20)]))
        return out


class SAA1099Pair(SquareChip):
    """Две SAA1099 (CMS): у каждой 6 тоновых каналов со своей громкостью слева/справа.

    Порты: base+1 — адрес регистра, base — данные (0x220/0x221 и 0x222/0x223).
    f = clock / 512 * 2^октава / (511 - частота).
    """
    channels = 2

    def __init__(self, base=0x220, amplitude=0.07):
        self.base, self.amp = base, amplitude
        self.addr = [0, 0]
        self.reg = [[0] * 32, [0] * 32]

    def write(self, port, value):
        chip, is_addr = divmod(port - self.base, 2)
        if chip not in (0, 1):
            return
        if is_addr:
            self.addr[chip] = value & 0x1F
        else:
            self.reg[chip][self.addr[chip]] = value

    def voices(self):
        out = []
        for chip in range(2):
            r = self.reg[chip]
            if not r[0x1C] & 1:
                continue
            for ch in range(6):
                if not r[0x14] >> ch & 1:
                    continue
                left, right = r[ch] & 0x0F, r[ch] >> 4
                if not (left or right):
                    continue
                octave = (r[0x10 + ch // 2] >> (4 * (ch & 1))) & 7
                freq = SAA_CLOCK / 512 * (1 << octave) / (511 - r[0x08 + ch])
                out.append(((chip, ch), freq, [self.amp * left / 15, self.amp * right / 15]))
        return out


def render(chip, init, ticks, samples_per_tick):
    """Записи в порты по тикам -> float32 [samples, channels]."""
    for port, value in init:
        chip.write(port, value)
    parts = []
    for writes in ticks:
        for port, value in writes:
            chip.write(port, value)
        parts.append(chip.tick(samples_per_tick))
    return np.concatenate(parts)
