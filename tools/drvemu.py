"""Запуск настоящего звукового драйвера SCI (*.DRV) в эмуляторе x86 (unicorn).

Драйвер — 16-битный код реального режима. Вход: far call на смещение 0, BP = номер
функции, параметры в регистрах. Все обращения драйвера к портам перехватываются:
так получается поток записей в OPL2 (Sound Blaster) или в таймер/порт спикера.
"""
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INSN, UC_HOOK_INTR
from unicorn.x86_const import (
    UC_X86_INS_IN, UC_X86_INS_OUT,
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX, UC_X86_REG_BP,
    UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES,
    UC_X86_REG_SS, UC_X86_REG_SP, UC_X86_REG_IP, UC_X86_REG_EAX, UC_X86_REG_AL,
)

DRV_SEG = 0x1000
DATA_SEG = 0x3000
STACK_SEG = 0x5000
STUB_SEG = 0x0050  # здесь стоит HLT, на него возвращается retf драйвера

# Номера функций драйвера (одинаковы для STD.DRV и SNDBLAST.DRV)
FN_INFO, FN_INIT, FN_TERM, FN_TICK = 0, 1, 2, 3
FN_NOTE_OFF, FN_NOTE_ON, FN_CONTROLLER, FN_PROGRAM, FN_PITCH_BEND = 4, 5, 7, 8, 10
FN_MASTER_VOLUME = 12


class Driver:
    def __init__(self, path, port_in=None, on_int=None):
        with open(path, "rb") as f:
            self.code = f.read()
        self.uc = Uc(UC_ARCH_X86, UC_MODE_16)
        self.uc.mem_map(0, 0x100000)
        self.uc.mem_write(DRV_SEG * 16, self.code)
        self.uc.mem_write(STUB_SEG * 16, b"\xF4")
        self.writes = []  # (port, value) за время текущего вызова
        self._port_in = port_in or (lambda port, size: 0)
        self._on_int = on_int
        self.uc.hook_add(UC_HOOK_INSN, self._on_in, None, 1, 0, UC_X86_INS_IN)
        self.uc.hook_add(UC_HOOK_INSN, self._on_out, None, 1, 0, UC_X86_INS_OUT)
        self.uc.hook_add(UC_HOOK_INTR, self._on_intr)

    def _on_in(self, uc, port, size, user):
        return self._port_in(port, size)

    def _on_out(self, uc, port, size, value, user):
        self.writes.append((port, value & 0xFF))

    def _on_intr(self, uc, intno, user):
        if self._on_int is not None:
            self._on_int(uc, intno)  # после возврата выполнение идёт со следующей инструкции
            return
        raise RuntimeError(f"драйвер вызвал INT {intno:#x}: не поддерживается")

    def put_data(self, data):
        """Кладёт данные (например, патч) в память; возвращает (segment, offset)."""
        self.uc.mem_write(DATA_SEG * 16, bytes(data))
        return DATA_SEG, 0

    def call(self, fn, ax=0, bx=0, cx=0, dx=0, es=0, di=0, si=0):
        uc = self.uc
        for reg, val in ((UC_X86_REG_AX, ax), (UC_X86_REG_BX, bx), (UC_X86_REG_CX, cx),
                         (UC_X86_REG_DX, dx), (UC_X86_REG_SI, si), (UC_X86_REG_DI, di),
                         (UC_X86_REG_BP, fn), (UC_X86_REG_ES, es), (UC_X86_REG_DS, DATA_SEG),
                         (UC_X86_REG_SS, STACK_SEG)):
            uc.reg_write(reg, val)
        sp = 0xFFF0 - 4
        uc.mem_write(STACK_SEG * 16 + sp, (0).to_bytes(2, "little") + STUB_SEG.to_bytes(2, "little"))
        uc.reg_write(UC_X86_REG_SP, sp)
        uc.reg_write(UC_X86_REG_CS, DRV_SEG)
        uc.reg_write(UC_X86_REG_IP, 0)
        uc.emu_start(DRV_SEG * 16, STUB_SEG * 16, count=5_000_000)
        return uc.reg_read(UC_X86_REG_AX), uc.reg_read(UC_X86_REG_CX)

    def take_writes(self):
        w, self.writes = self.writes, []
        return w
