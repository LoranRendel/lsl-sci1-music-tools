"""Чтение ресурсов SCI из RESOURCE.MAP / RESOURCE.00N (вариант карты SCI01)."""
import os
import struct

TYPE_NAMES = {
    0: "view", 1: "pic", 2: "script", 3: "text", 4: "sound", 5: "memory",
    6: "vocab", 7: "font", 8: "cursor", 9: "patch", 10: "bitmap",
    11: "palette",
}


def unpack_lzw1(src, unpacked_size):
    """Метод сжатия 2 (LZW1): коды MSB-first, 9..12 бит, 0x100 — сброс, 0x101 — конец."""
    bits = int.from_bytes(src, "big")
    total = len(src) * 8
    pos = 0
    out = bytearray()
    numbits, cur, end = 9, 0x102, 0x1FF
    tok_data, tok_next = {}, {}
    started = False
    lastbits = lastchar = 0
    while len(out) < unpacked_size and pos + numbits <= total:
        code = (bits >> (total - pos - numbits)) & ((1 << numbits) - 1)
        pos += numbits
        if code == 0x101:
            break
        if not started:
            out.append(code & 0xFF)
            lastbits, lastchar, started = code, code & 0xFF, True
            continue
        if code == 0x100:
            numbits, cur, end = 9, 0x102, 0x1FF
            started = False
            continue
        token, stack = code, []
        if token >= cur:
            token = lastbits
            stack.append(lastchar)
        while 0xFF < token < 0x1004:
            stack.append(tok_data[token])
            token = tok_next[token]
        lastchar = token & 0xFF
        stack.append(lastchar)
        out.extend(reversed(stack))
        if cur <= end:
            tok_data[cur], tok_next[cur] = lastchar, lastbits
            cur += 1
            if cur == end and numbits < 12:
                numbits += 1
                end = (end << 1) + 1
        lastbits = code
    return bytes(out[:unpacked_size])


class ResourceManager:
    def __init__(self, game_dir):
        self.game_dir = game_dir
        self.index = {}  # (type, number) -> (volume, offset)
        with open(os.path.join(game_dir, "RESOURCE.MAP"), "rb") as f:
            data = f.read()
        for i in range(0, len(data) - 5, 6):
            rid, loc = struct.unpack_from("<HI", data, i)
            if rid == 0xFFFF:
                break
            self.index[(rid >> 11, rid & 0x7FF)] = (loc >> 28, loc & 0x0FFFFFFF)
        self._volumes = {}

    def _volume(self, n):
        if n not in self._volumes:
            with open(os.path.join(self.game_dir, f"RESOURCE.{n:03d}"), "rb") as f:
                self._volumes[n] = f.read()
        return self._volumes[n]

    def numbers(self, rtype):
        return sorted(n for t, n in self.index if t == rtype)

    def load(self, rtype, number):
        vol, off = self.index[(rtype, number)]
        data = self._volume(vol)
        rid, packed, unpacked, method = struct.unpack_from("<HHHH", data, off)
        if rid != (rtype << 11 | number):
            raise ValueError(f"{TYPE_NAMES.get(rtype, rtype)}.{number}: заголовок в томе не совпадает с картой")
        raw = data[off + 8:off + 8 + packed - 4]
        if method == 0:
            return raw
        if method == 2:
            return unpack_lzw1(raw, unpacked)
        raise NotImplementedError(f"{TYPE_NAMES.get(rtype, rtype)}.{number}: метод сжатия {method}")
