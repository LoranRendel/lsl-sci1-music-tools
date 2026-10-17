# lsl-sci1-music-tools

Tools for exporting the music of *Leisure Suit Larry 1: In the Land of the Lounge Lizards* (Sierra On-Line VGA remake, 1991, SCI1 engine) to MIDI, FLAC, VGZ and — for the PC speaker — Furnace modules and a browser player.

The game's own sound drivers (`*.DRV`) are executed in an x86 emulator, and their writes to the sound hardware are fed into chip models. Each FLAC therefore sounds the way that card played the music in the game, using the part Sierra arranged for that card.

The game itself is **not** included: the scripts are meant to be placed in the `tools/` subdirectory of an installed copy of the game.

## Requirements

- Python 3 with `numpy`, `unicorn`, `pyopl` (`python -m pip install --user numpy unicorn pyopl`; `pyopl` needs a C compiler, e.g. MSVC on Windows)
- `ffmpeg` in `PATH` (FLAC encoding)

## Usage

```sh
python tools/export_music.py              # export all 32 melodies to export/music/ (~6 min)
python tools/export_music.py --only 390   # selected sounds
python tools/export_music.py --fast       # everything except FLAC and VGZ (a few seconds)
python tools/export_music.py --list       # list melodies
python tools/export_music.py --info 390   # tracks and channels of a sound resource
```

Console output is in Russian; in Git Bash on Windows set `PYTHONIOENCODING=utf-8`.

## Output

| Folder | Contents |
|---|---|
| `flac-speaker/` | PC speaker (`STD.DRV`) |
| `flac-soundblaster/` | AdLib / Sound Blaster (`ADL.DRV`, OPL2 via pyopl) |
| `flac-proaudio/` | Pro AudioSpectrum (`PROAUDIO.DRV`, dual OPL2, stereo) |
| `flac-cms/` | Creative Music System / Game Blaster (`CMS.DRV`, 2× SAA1099, stereo) |
| `flac-tandy/` | Tandy 1000 (`TANDY3V.DRV`, SN76496) |
| `flac-ps1/` | IBM PS/1 Audio (`IBMPS1.DRV`, SN76496) |
| `vgz-soundblaster/` | AdLib register log as VGM (YM3812), with loop point and GD3 tags — for VGM players |
| `spk-log/` | PC speaker part as a timer-divisor-per-tick log (`.spk.gz`, ~1 KB per melody) — exactly what `STD.DRV` wrote to the timer |
| `furnace-speaker/` | PC speaker part as [Furnace](https://github.com/tildearrow/furnace) modules (`.fur`, Intel 8253 chip): one row per 60 Hz tick, note + `E5xx` fine pitch (within ~1 cent of the driver), loop via `0Bxx` |
| `speaker-player.html` | Self-contained browser player for all speaker logs (WebAudio square wave, seek; repeat works for every melody — from the loop point if it has one, otherwise from the start; "play next" is greyed out while repeat is on); the selected melody and settings are kept in the URL hash, e.g. `speaker-player.html#song=390&loop=1&next=0&vol=35` |
| `midi-gm/` | General MIDI converted from the MT-32 part (most complete arrangement) |
| `midi-<device>/` | Original part for each device (`adlib`, `mt32`, `cms`, `tandy`, `speaker`); program numbers refer to the device's own patch, not GM. MT-32 files begin with the SysEx setup from `patch.001`, so they play with the game's custom timbres on an MT-32 or Munt |

MT-32 audio is not rendered (no ROMs).

## Playing the files

- `.vgz` — any VGM player (VGMPlay, foobar2000 with vgmstream / foo_input_vgm).
- `.fur` — [Furnace](https://github.com/tildearrow/furnace) 0.6.8 or newer; set *Chip Manager → PC Speaker → Speaker type → Cone* for a more speaker-like tone. The module loops like the game.
- `speaker-player.html` — open in any modern browser; no installation needed.
- `midi-<device>/` — the parts are not General MIDI; use them for study in a MIDI editor (or `midi-mt32/` with an MT-32 / Munt). For ordinary listening use `midi-gm/`.

## Melody names

Only the nine songs of Lefty's jukebox have official titles (taken from the jukebox menu in script 110), e.g. `390 - Jukebox 9 - That's a Sweet Moon, Honey`. The other melodies are named after the place in the game where the scripts play them, e.g. `700 - Title Theme`, `143 - TV Channel 3 - The Revenge of the Software Developers`.

## Modules

| File | Purpose |
|---|---|
| `sciresource.py` | `RESOURCE.MAP` / volume reader, LZW1 decompression |
| `scisound.py` | SCI1 sound resource parser, Standard MIDI File writer |
| `drvemu.py` | Runs a SCI sound driver in Unicorn and records its port writes |
| `sciplayer.py` | Feeds a song to a driver tick by tick (the interpreter's role); card list; FLAC and VGM writers |
| `chips.py` | Chip models: OPL2, dual OPL2, SAA1099, SN76496, PC speaker |
| `speaker.py` | PC speaker log (per-tick PIT divisor), `.spk.gz` reader/writer, HTML player |
| `furnace.py` | Speaker log → Furnace module (format version 228, opens in Furnace 0.6.8.x) |
| `mt32gm.py` | MT-32 → General MIDI mapping and MT-32 setup SysEx from `patch.001` |
| `export_music.py` | Command-line entry point, melody list and titles |

See `CLAUDE.md` for format and driver details.
