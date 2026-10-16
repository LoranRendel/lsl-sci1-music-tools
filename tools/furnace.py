"""Лог спикера (speaker.py) -> модуль Furnace (.fur) с микросхемой Intel 8253 (PC Speaker).

Формат — старый блок INFO (версия 228, Furnace 0.6.8.x), см. papers/format.md в репозитории
Furnace. Одна строка паттерна = один тик (скорость 1, 60 тиков/с). Частота драйвера
записывается нотой + E5xx (подстройка: 128 шагов на полутон, линейная высота), поэтому
расхождение с игрой — меньше цента. Точка цикла — начало отдельного паттерна, в конце
стоит 0Bxx (переход к нему); без цикла — FFxx (стоп).
"""
import math
import struct
import zlib

from speaker import changes

FORMAT_VERSION = 228
PIT_CLOCK = 1193182
CHIP_PC_SPEAKER = 0x93
ROWS = 256
NOTE_OFF = 180
FX_PITCH, FX_JUMP_ORDER, FX_NEXT_PATTERN, FX_STOP = 0xE5, 0x0B, 0x0D, 0xFF


def _str(s):
    return s.encode("utf-8") + b"\0"


def _block(tag, body):
    return tag + struct.pack("<I", len(body)) + body


def note_of(divisor):
    """Делитель PIT -> (нота Furnace, значение E5xx). Нота 0 = C-(-5); 440 Гц звучит
    на ноте 105 (так показал рендер самого Furnace), то есть нота Furnace = MIDI + 36."""
    semis = 69 + 12 * math.log2(PIT_CLOCK / divisor / 440)
    note = round(semis)
    fine = max(0, min(255, 0x80 + round((semis - note) * 128)))
    return note + 36, fine


def _rows(divisors, loop_tick):
    """-> [(начало, конец)] отрезков тиков по паттернам; точка цикла начинает паттерн."""
    bounds = [0, len(divisors)] if loop_tick is None else [0, loop_tick, len(divisors)]
    out = []
    for a, b in zip(bounds, bounds[1:]):
        out += [(t, min(t + ROWS, b)) for t in range(a, b, ROWS)]
    return out


def _pattern(cells):
    """cells: {строка: (note|None, [(fx, val)…])} -> данные PATN (сжатие пустых строк)."""
    out, row = bytearray(), 0
    for r in sorted(cells):
        gap = r - row
        while gap > 0:  # пропуск: 0x80|N — N+2 строк, 0x00 — одна строка
            if gap == 1:
                out.append(0)
                gap = 0
            else:
                n = min(gap, 128)  # 0xFF занят под «конец паттерна»
                out.append(0x80 | (n - 2))
                gap -= n
        note, fx = cells[r]
        # Как в DivEngine::saveFur: эффект 0 — биты 3/4 маски, эффекты 1–3 — бит 5 и второй
        # байт (в нём отмечены все колонки, включая нулевую)
        mask = (1 if note is not None else 0) | (0x18 if fx else 0) | (0x20 if len(fx) > 1 else 0)
        out.append(mask)
        if mask & 0x20:
            out.append(sum(3 << (2 * i) for i in range(len(fx))))
        if note is not None:
            out.append(note)
        for f, v in fx:
            out += bytes((f, v))
        row = r + 1
    out.append(0xFF)
    return bytes(out)


def build(divisors, loop_tick, title, author="Sierra On-Line", album=""):
    segs = _rows(divisors, loop_tick)
    loop_order = None if loop_tick is None else next(i for i, (a, _) in enumerate(segs) if a == loop_tick)
    events = dict(changes(divisors))
    patterns = []
    fine_now = 0x80
    for i, (a, b) in enumerate(segs):
        cells = {}
        for t in range(a, b):
            if t not in events:
                continue
            d = events[t]
            if d:
                note, fine = note_of(d)
                fx = [(FX_PITCH, fine)] if fine != fine_now or t == a == loop_tick else []
                fine_now = fine
                cells[t - a] = (note, fx)
            else:
                cells[t - a] = (NOTE_OFF, [])
        if loop_tick is not None and a == loop_tick and a not in events:
            # Вход в цикл: восстановить звук, который шёл в этот момент
            d = divisors[a]
            note, fine = note_of(d) if d else (NOTE_OFF, fine_now)
            cells[0] = (note, [(FX_PITCH, fine)] if d else [])
        last = b - a - 1
        if i + 1 == len(segs):
            jump = (FX_STOP, 0) if loop_order is None else (FX_JUMP_ORDER, loop_order)
        elif b - a < ROWS:
            jump = (FX_NEXT_PATTERN, 0)
        else:
            jump = None
        if jump:
            note, fx = cells.get(last, (None, []))
            # колонка 0 — E5xx, колонка 1 — переходы; E5 с текущей подстройкой ничего не меняет
            cells[last] = (note, (fx or [(FX_PITCH, fine_now)]) + [jump])
        patterns.append(_pattern(cells))

    n_ord = len(segs)
    info = bytearray()
    info += struct.pack("<BBBB", 0, 1, 1, 1)                 # time base, speed 1/2, arp
    info += struct.pack("<f", 60.0)
    info += struct.pack("<HHBB", ROWS, n_ord, 4, 60)         # длина паттерна, порядков, подсветка
    info += struct.pack("<HHHI", 0, 0, 0, len(patterns))     # инструменты, волны, сэмплы, паттерны
    info += bytes([CHIP_PC_SPEAKER]) + bytes(31)             # микросхемы
    info += bytes([64]) + bytes(31)                          # громкость (устар.)
    info += bytes(32)                                        # панорама (устар.)
    info += bytes(128)                                       # указатели на флаги микросхем
    info += _str(title) + _str(author)
    info += struct.pack("<f", 440.0)
    # limit slides, linear pitch (2 = полностью линейная), loop modality, затем флаги совместимости
    info += bytes([0, 2, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1])
    ptr_pos = len(info)
    info += bytes(4 * len(patterns))                         # указатели на паттерны (позже)
    info += bytes(range(n_ord))                              # порядки: паттерн i в порядке i
    info += bytes([2])                                       # колонок эффектов
    info += bytes([3]) + bytes([0])                          # показан (и в осциллографе), не свёрнут
    info += _str("") + _str("")                              # имя канала, короткое имя
    info += _str("Converted from the PC speaker driver (STD.DRV) output, one row per 60 Hz tick")
    info += struct.pack("<f", 1.0)                           # master volume
    ext = bytearray(28)                                      # расширенные флаги совместимости
    ext[13] = 4                                              # pitch slide speed
    ext[16] = 1                                              # new volume scaling
    ext[22] = 2                                              # cut/delay policy
    ext[24] = 1                                              # automatic system name
    info += ext
    info += struct.pack("<HH", 150, 150)                     # virtual tempo
    info += _str("") + _str("") + bytes([0]) + bytes(3)      # имя/комментарий подпесни, доп. подпесен
    info += _str("PC Speaker") + _str(album) + _str("") * 4
    info += struct.pack("<fff", 1.0, 0.0, 0.0)               # громкость/панорама микросхемы
    info += struct.pack("<I", 0) + bytes([1])                # patchbay: нет связей, авто
    info += bytes(8)                                         # ещё флаги совместимости
    info += bytes([1]) + bytes([1]) + bytes(15)              # speed pattern: [1]
    info += bytes([0])                                       # grooves
    dir_pos = len(info)
    info += bytes(12)                                        # указатели на каталоги (позже)

    header_len = 32
    info_block = _block(b"INFO", bytes(info))
    pos = header_len + len(info_block)
    blobs, ptrs, dirs = [], [], []
    for _ in range(3):  # каталоги инструментов, волн, сэмплов — пустые, но обязательны
        blob = _block(b"ADIR", struct.pack("<I", 0))
        dirs.append(pos)
        blobs.append(blob)
        pos += len(blob)
    for i, data in enumerate(patterns):
        body = struct.pack("<BBH", 0, 0, i) + _str("") + data
        blob = _block(b"PATN", body)
        ptrs.append(pos)
        blobs.append(blob)
        pos += len(blob)
    info_block = bytearray(info_block)
    struct.pack_into(f"<{len(ptrs)}I", info_block, 8 + ptr_pos, *ptrs)
    struct.pack_into("<III", info_block, 8 + dir_pos, *dirs)
    header = b"-Furnace module-" + struct.pack("<HHI", FORMAT_VERSION, 0, header_len) + bytes(8)
    return header + bytes(info_block) + b"".join(blobs)


def write_fur(path, divisors, loop_tick, title, album=""):
    with open(path, "wb") as f:
        f.write(zlib.compress(build(divisors, loop_tick, title, album=album), 9))
