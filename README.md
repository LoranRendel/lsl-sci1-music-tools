# lsl-sci1-music-tools

Tools for exporting the music of *Leisure Suit Larry 1: In the Land of the Lounge Lizards* (Sierra On-Line VGA remake, 1991, SCI1 engine) to MIDI, FLAC and VGZ.

The game's own sound drivers (`*.DRV`) are executed in an x86 emulator, and their writes to the sound hardware are fed into chip models. Each FLAC therefore sounds the way that card played the music in the game, using the part Sierra arranged for that card.

The game itself is **not** included: the scripts are meant to be placed in the `tools/` subdirectory of an installed copy of the game.

## Requirements

- Python 3 with `numpy`, `unicorn`, `pyopl` (`python -m pip install --user numpy unicorn pyopl`; `pyopl` needs a C compiler, e.g. MSVC on Windows)
- `ffmpeg` in `PATH` (FLAC encoding)

## Usage

```sh
python tools/export_music.py              # export all 32 melodies to export/music/ (~6 min)
python tools/export_music.py --only 390   # selected sounds
python tools/export_music.py --midi-only  # MIDI only (a few seconds)
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
| `midi-gm/` | General MIDI converted from the MT-32 part (most complete arrangement) |
| `midi-<device>/` | Original part for each device (`adlib`, `mt32`, `cms`, `tandy`, `speaker`); program numbers refer to the device's own patch, not GM. MT-32 files begin with the SysEx setup from `patch.001`, so they play with the game's custom timbres on an MT-32 or Munt |

MT-32 audio is not rendered (no ROMs).

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
| `mt32gm.py` | MT-32 → General MIDI mapping and MT-32 setup SysEx from `patch.001` |
| `export_music.py` | Command-line entry point, melody list and titles |

See `CLAUDE.md` for format and driver details.
