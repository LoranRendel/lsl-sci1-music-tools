"""Экспорт мелодий игры: MIDI, FLAC для каждой звуковой карты, VGZ, партия спикера.

    python tools/export_music.py              # все мелодии в export/music
    python tools/export_music.py --only 390   # выбранные
    python tools/export_music.py --fast       # всё, кроме FLAC и VGZ (несколько секунд)
    python tools/export_music.py --list       # список мелодий
    python tools/export_music.py --info 390   # дорожки и каналы звука

Результат:
    midi-gm/           General MIDI из партии MT-32 (самая полная аранжировка)
    midi-<устройство>/ исходная партия каждого устройства (MIDI_DEVICES): номера программ —
                       инструменты его патча, а не GM; у MT-32 в начале SysEx из patch.001
    flac-<карта>/      настоящий драйвер карты в эмуляторе + модель микросхемы
                       (карты — CARDS в sciplayer.py)
    vgz-soundblaster/  AdLib/Sound Blaster: VGM (журнал записей в YM3812, с циклом), сжатый gzip
    spk-log/           PC-спикер: делитель таймера на каждый тик (speaker.py), ~1 КБ на мелодию
    furnace-speaker/   PC-спикер: модуль трекера Furnace (furnace.py)
    speaker-player.html  проигрыватель всех логов спикера в браузере
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sciresource import ResourceManager  # noqa: E402
from scisound import DEVICES, TICKS_PER_SECOND, parse_events, parse_sound, to_midi  # noqa: E402
from sciplayer import CARDS, GAME_DIR, Song, run, write_flac, write_vgm  # noqa: E402
from mt32gm import GmMapper, mt32_setup_sysex, to_gm_midi  # noqa: E402
from speaker import SPEAKER, speaker_log, write_log, write_player  # noqa: E402
from furnace import write_fur  # noqa: E402

SOUND, PATCH = 4, 9
ALBUM = "Leisure Suit Larry 1 VGA"
ADLIB, MT32 = 0x00, 0x0C
# Устройства, чьи партии выгружаются в midi-<имя>/ (дорожки 0x06 и 0x16 драйверы игры не берут)
MIDI_DEVICES = {"adlib": ADLIB, "mt32": MT32, "cms": 0x09, "tandy": 0x13, "speaker": 0x12}

# Названия из музыкального автомата в баре Lefty's (script 110: меню из пар
# «строка — номер звука», в порядке пунктов меню).
TITLES = {
    206: "Taxicab from Hell",
    410: 'Air For A "G" String',
    320: "I Can Can You",
    310: "Mantovani's Revenge",
    351: 'Theme from "Bo-Larry"',
    411: '"Wedding March" by Bloughengrin',
    610: "Prelude to an Afternoon of Fawn",
    510: "Her Albert Has Some Iguana Gas",
    390: "That's a Sweet Moon, Honey",
}
JUKEBOX = list(TITLES)  # порядок словаря = порядок пунктов меню автомата

# Остальные мелодии названы по месту в игре: где и когда их запускают скрипты
# (селектор number: у объекта Sound, свойства объектов Sound, тексты рядом с запуском).
# Знак «?» в комментарии — назначение выведено по косвенным признакам.
PLACES = {
    # Песни автомата звучат и в своих локациях (там их тоже запускают скрипты)
    206: "Taxi",                                          # rm200
    410: "Quiki-Wed Chapel",                              # rm410
    320: "Casino Cabaret",                                # rm320
    310: "Casino, Glass Elevator, Hotel Hallway",         # rm310, rm330, rm340
    351: "Hotel Top Floor",                               # rm350
    411: "Quiki-Wed Chapel - Wedding",                    # rm410
    610: "Disco",                                         # rm610
    510: "Quiki-Mart",                                    # rm510
    390: "Honeymoon Suite - Radio",                       # rm390, радио у кровати
    110: "Lefty's Bar",                                   # rm110, rm120 (коридор)
    120: "Outside the Quiki-Mart",                        # rm500 ?
    135: "Lefty's Restroom - Flood",                      # rm130, после засора унитаза ?
    141: "TV Channel 1 - Soap Opera",                     # rm140: канал k -> звук 141+k,
    142: "TV Channel 2 - Motel-69 Commercial",            #   описания — текст 141 (2k, 2k+1)
    143: "TV Channel 3 - The Revenge of the Software Developers",
    144: "TV Channel 4 - Jungle Documentary",
    145: "TV Channel 5 - Beautiful Day in the Neighborhood",
    146: "TV Channel 6 - Mud Wrestlers Nude Bicycle Race",
    147: "TV Channel 7 - Naugahyde Goddesses of Oakhurst",
    148: "TV Channel 8 - Adult Show (Hooker's Room)",     # rm140 и rm150
    150: "Hooker's Bedroom",                              # rm150
    165: "Fire Escape",                                   # rm160, ленточка на перилах ?
    170: "Back Alley",                                    # rm170 (мусорный бак)
    171: "Fight",                                         # объект sfxFight (rm170), также rm390, rm700
    190: "Death - Sierra Recycling Plant",                # script 0 -> rm190
    197: "Death - New Larry",                             # объект sfxNewLarry (rm190)
    312: "Casino 2",                                      # rm310, сразу после 310 ?
    381: "Penthouse",                                     # rm360
    395: "Honeymoon Suite",                               # rm390, при входе ?
    396: "Honeymoon Suite - Fawn's Surprise",             # rm390, «Close your eyes» ?
    611: "Disco - Dancing",                               # rm610 ?
    700: "Title Theme",                                   # rm710 (заставка при запуске), rm370 (концовка)
}

# Мелодии: звуки без цифрового сэмпла, где в партии Sound Blaster не меньше 150 нот
# и 15 разных высот. Короткие эффекты и однонотные шумы сюда не попадают.
MELODIES = [110, 120, 135, 141, 142, 143, 144, 145, 146, 147, 148, 150, 165, 170, 171, 190,
            197, 206, 310, 312, 320, 351, 381, 390, 395, 396, 410, 411, 510, 610, 611, 700]


def title_of(number):
    if number in TITLES:
        return f"Jukebox {JUKEBOX.index(number) + 1} - {TITLES[number]}"
    return PLACES.get(number) or f"sound {number}"


def tag_notes(number):
    if number in TITLES:
        return (f"Музыкальный автомат в баре Lefty's, пункт {JUKEBOX.index(number) + 1}. "
                f"В игре также звучит: {PLACES[number]}")
    return "Название по месту в игре (не официальное)"


def file_name(number):
    safe = title_of(number).replace('"', "'")
    for ch in '<>:/\\|?*':
        safe = safe.replace(ch, "")
    return f"{number:03d} - {safe}"


def print_info(rm, number):
    data = rm.load(SOUND, number)
    print(f"sound.{number}: {len(data)} байт — {title_of(number)}")
    for dev, channels in parse_sound(data):
        print(f"  {DEVICES.get(dev, hex(dev))} (0x{dev:02X})")
        for ch in channels:
            if ch.digital:
                rate, pcm = ch.sample()
                print(f"    @{ch.offset:<6} цифровой: {rate} Гц, {len(pcm) / rate:.2f} с")
            else:
                events, ticks = parse_events(ch.body)
                print(f"    @{ch.offset:<6} канал {ch.number:2} poly={ch.poly} prio={ch.prio}: "
                      f"{len(events)} событий, {ticks / TICKS_PER_SECOND:.1f} с")


def export(rm, out_dir, numbers, audio=True):
    dirs = {"midi-gm": "midi-gm", "vgm": "vgz-soundblaster", "spk": "spk-log", "fur": "furnace-speaker"}
    dirs.update({"midi-" + key: "midi-" + key for key in MIDI_DEVICES})
    dirs.update({card.key: "flac-" + card.key for card in CARDS})
    dirs = {k: os.path.join(out_dir, v) for k, v in dirs.items()}
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    mapper = GmMapper(rm.load(PATCH, 1))
    mt32_setup = mt32_setup_sysex(rm.load(PATCH, 1))
    for number in numbers:
        tracks = dict(parse_sound(rm.load(SOUND, number)))
        name = file_name(number)
        title = title_of(number)
        notes = tag_notes(number)

        missing = []
        for card in CARDS if audio else ():
            if card.device in tracks:
                tags = {"title": title, "album": f"{ALBUM} — {card.title}",
                        "track": str(number), "date": "1991", "comment": notes}
                write_flac(card.render(rm, tracks[card.device]),
                           os.path.join(dirs[card.key], name + ".flac"), tags)
            else:
                missing.append(card.key)

        song = Song(tracks[ADLIB])
        adlib = next(c for c in CARDS if c.key == "soundblaster")
        if audio:
            drv, init = adlib.start(rm)
            write_vgm(init, run(drv, Song(tracks[ADLIB]), tail=song.loop_tick is None), song.loop_tick,
                      os.path.join(dirs["vgm"], name + ".vgz"), title, notes=notes)

        mt32 = Song(tracks[MT32])
        with open(os.path.join(dirs["midi-gm"], name + ".mid"), "wb") as f:
            f.write(to_gm_midi(tracks[MT32], mapper, title, mt32.loop_tick))
        for key, dev in MIDI_DEVICES.items():
            if dev in tracks:
                with open(os.path.join(dirs["midi-" + key], name + ".mid"), "wb") as f:
                    f.write(to_midi(tracks[dev], title, mt32_setup if dev == MT32 else ()))

        if SPEAKER in tracks:
            divisors, spk_loop = speaker_log(rm, tracks[SPEAKER])
            write_log(os.path.join(dirs["spk"], name + ".spk.gz"), divisors, spk_loop)
            write_fur(os.path.join(dirs["fur"], name + ".fur"), divisors, spk_loop, title, ALBUM)

        length = song.end_tick / TICKS_PER_SECOND
        loop = "" if song.loop_tick is None else f", цикл с {song.loop_tick / TICKS_PER_SECOND:.1f} с"
        absent = f"; нет партии для: {', '.join(missing)}" if missing else ""
        print(f"{name}: {length:.1f} с{loop}{absent}")
    write_player(dirs["spk"], os.path.join(out_dir, "speaker-player.html"), ALBUM)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", default=GAME_DIR, help="каталог игры (по умолчанию — родитель tools/)")
    ap.add_argument("--out", default=os.path.join(GAME_DIR, "export", "music"))
    ap.add_argument("--only", type=int, nargs="+", metavar="N", help="номера звуков")
    ap.add_argument("--fast", action="store_true", help="без FLAC и VGZ (несколько секунд)")
    ap.add_argument("--list", action="store_true", help="список мелодий")
    ap.add_argument("--info", type=int, metavar="N", help="дорожки и каналы звука N")
    args = ap.parse_args()

    rm = ResourceManager(args.game)
    if args.info is not None:
        print_info(rm, args.info)
    elif args.list:
        for n in MELODIES:
            print(file_name(n))
    else:
        export(rm, args.out, args.only or MELODIES, audio=not args.fast)


if __name__ == "__main__":
    main()
