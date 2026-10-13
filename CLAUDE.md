# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this directory is

This is **not a software project** but an installed DOS game: *Leisure Suit Larry 1: In the Land of the Lounge Lizards* (Sierra On-Line VGA remake, 1991, floppy version, SCI engine, `VERSION` = 2.0). The build comes from DJ OldGames (`#info.txt`); the game is meant to be run in DOSBox. The only code is the Python tooling in `tools/` (no build system, linters or tests).

The directory is a git repository, but only `tools/`, `README.md`, `CLAUDE.md`, `.gitignore` and `.gitattributes` are under version control (whitelist in `.gitignore`): game files and export results (`export/`) are never committed.

Nearly all other files are binary resources of the 1991 original. Do not modify them unless the user explicitly asks; the only text files are `.BAT`, `RESOURCE.*` (except `.000–.002` and `.MAP`), `INSTALL.TXT`, `INTERP.TXT`, `#info.txt`.

## Running the game

From DOS/DOSBox in this directory:

- `SIERRA.BAT` (or `LSL1.BAT`, `LSL1VGA.BAT`) — starts the `SCIDHUV.EXE` interpreter with the current `RESOURCE.CFG`.
- `BLASTER.BAT` — copies `RESOURCE.SND` → `RESOURCE.CFG` (Sound Blaster) and starts the game.
- `SPEAKER.BAT` — copies `RESOURCE.SPK` → `RESOURCE.CFG` (PC speaker, `minHunk = 350k`) and starts the game.
- `INSTALL.EXE` — Sierra's standard setup program, rewrites `RESOURCE.CFG` (UI strings in `INSTALL.TXT`, help in `INSTALL.HLP`).

## Tools (`tools/`, Python 3 + `numpy`, `unicorn`, `pyopl`, `ffmpeg`)

Install dependencies with `python -m pip install --user unicorn pyopl` (pyopl is built with MSVC). The tools print Russian text; in Git Bash set `PYTHONIOENCODING=utf-8`.

- `python tools/export_music.py` — exports melodies to `export/music/` (generated, never edited by hand):
  - `midi-gm/` — General MIDI converted from the MT-32 part;
  - `midi-<device>/` — the original part of each device (adlib/mt32/cms/tandy/speaker, `MIDI_DEVICES`); program numbers are not GM; the mt32 files start with ~4.6 s of SysEx that sets up the module from patch.001 (`mt32_setup_sysex`);
  - `flac-<card>/` — one per card in `CARDS` (`sciplayer.py`: speaker, soundblaster, proaudio, cms, tandy, ps1); peak-normalized, encoded by `ffmpeg` from PATH, tags title/album/comment;
  - `vgz-soundblaster/` — VGM with YM3812, gzipped, with loop point and GD3 tag.

  A full run takes about 6 minutes. `--only 390` — selected sounds, `--midi-only` — MIDI only (seconds), `--list` — list melodies, `--info 390` — tracks and channels of a sound.
- The melody list (`MELODIES`) and titles live in `export_music.py`. Official titles (`TITLES`) exist only for the 9 songs of Lefty's jukebox (file names use `Jukebox <menu item> - <title>`, the in-game location goes into the tag): in script 110 the title strings are paired with sound numbers (`lofsa <string>` + `pushi <number>`). The rest (`PLACES`) are named after where they play; rm710 is the startup intro (leads to the age quiz in rm720), so 700 is the title theme. To find where sound N plays: in bytecode look for `pushi 43` (selector `number`, from vocab 997) `push1` `pushi N`; Sound objects keep the number in their properties (sfxFight=171, sfxNewLarry=197); the TV in rm140 plays 141+channel, channel descriptions are text 141 (2k, 2k+1).
- FLAC/VGZ are produced by **running the real drivers** in an x86 emulator (`drvemu.py`): far call to offset 0, `BP` = function number; 1 init (`ES:AX` — patch), 3 tick (60 Hz), 4 noteOff / 5 noteOn (`AL` channel, `CH` note, `CL` velocity), 7 controller (`CH` number, `CL` value), 8 program (`CL`), 10 pitch bend (`CH` lsb, `CL` msb). Intercepted `OUT`s are fed to the chip models (0x388/0x389 → pyopl/VGM, 0x42/0x43/0x61 → square-wave generator).
- Chip models are in `chips.py`: OPL2 (pyopl), OPL2Stereo (PAS: 0x788 — both chips, 0x388 — left, 0x38A — right; only operator levels go through the latter two), SAA1099×2 (CMS, ports 0x220–0x223, f = 7159090/512·2^oct/(511−n)), SN76496 (Tandy — port 0x1E0, PS/1 — 0x205), speaker. LSL1's drivers don't use SAA/SN noise or envelopes, so the models are oversampled square waves. Pitch was checked against MIDI (±0.02 semitone). MT-32 is not synthesized: no ROMs.
- `sciplayer.py` plays the interpreter's role: before starting it sends each channel CC 0x4B (poly from the channel header), CC7=127, CC10=64 and centered pitch bend; without CC7>0 `STD.DRV` stays silent. Note-on with velocity 0 is sent as note-off (function 4): `STD.DRV` ignores velocity and would otherwise retrigger the note. The CMS/Tandy/PS1 drivers set volume in the tick (function 3). `PROAUDIO.DRV` calls INT 2Fh (looking for MVSOUND.SYS) — the interrupt is skipped. Channel 15 is the control channel (program 127 = loop point) and is not passed to the driver.
- `ADL.DRV` is used instead of `SNDBLAST.DRV`: the latter's init probes the DSP via IRQ/DMA. Their OPL write streams are identical (checked on 390/310/141 with the DSP probe patched out).
- `mt32gm.py`: an MT-32 part's program number is a patch-memory slot from patch.001 (layout: 3×20 bytes of text, volume, reverb, 11+33 bytes of reverb data, 48×8 patches, timbre count, timbres of 246 bytes each with a 10-byte name, `ABCD` + another 48×8 patches, `DCBA` + 256 rhythm + 9). Groups A/B → MT-32→GM table, custom timbres → by name (`CUSTOM_TO_GM`).
- `sciresource.py` — map/volumes and LZW1 decompression; `scisound.py` — SCI1 sound parsing and shared SMF writing code.

## Architecture

- **`SCIDHUV.EXE`** — the SCI interpreter. Its error messages ("Oops!", "Out of hunk!", "Couldn't find %s", etc.) are in `INTERP.TXT` with numbers — handy for decoding error codes.
- **`RESOURCE.CFG`** — active configuration: which drivers to load (`videoDrv`, `soundDrv`, `kbdDrv`, `mouseDrv`, `memoryDrv`, `joyDrv`), `minHunk`, `language`. `RESOURCE.SND` and `RESOURCE.SPK` are presets of this file switched by the `.BAT` scripts above. Changing the configuration means editing these three files.
- **`*.DRV`** — SCI drivers: video (`VGA320.DRV`, `VGA320BW.DRV`), sound (`SNDBLAST.DRV`, `ADL.DRV`, `MT32.DRV`, `MTBLAST.DRV`, `PROAUDIO.DRV`, `CMS.DRV`, `TANDY3V*.DRV`, `IBMPS1.DRV`, `STD.DRV` — PC speaker), input (`IBMKBD.DRV`, `JOYSTICK.DRV`). Drivers named in the config but absent here (`STDMOUSE.DRV`, `ARM.DRV`) are apparently handled or ignored by the interpreter — the game works with this config. `LARRY.DRV` is not a real driver but a 24-byte text file with three numbers.
- **`RESOURCE.MAP` + `RESOURCE.000–002`** — SCI game resources (pics, views, scripts, sounds, texts): the map says which volume and offset holds each resource.
  - `RESOURCE.MAP`: 6-byte entries `<u16 id><u32 loc>`, `id = type<<11 | number`, `loc = volume<<28 | offset`, terminated by `FFFF`. Types: 0 view, 1 pic, 2 script, 3 text, 4 sound, 6 vocab, 7 font, 8 cursor, 9 patch.
  - In a volume each resource has an 8-byte header `<u16 id><u16 packed+4><u16 unpacked><u16 method>`; method 0 — uncompressed, 2 — LZW1 (MSB-first codes, 9→12 bits, 0x100 reset, 0x101 end), 3/4 — LZW1 with view/pic reordering.
- **Sound (type 4 resources, 146 of them)** — SCI1 format: one resource holds tracks for all devices. Header: `[device type][{u16 ?, u16 offset, u16 size}…]FF` …, final `FF`. Channel data is Sierra's MIDI-like stream (2-byte header: MIDI channel, poly/prio; delta, `F8` = +240 ticks, running status, `FC` = end). Channels are shared: several devices reference the same offsets. A channel whose first byte is `FE` is a digital sample: `<u16 rate><u16 size><u16 loopStart><u16 loopEnd>`, then 8-bit unsigned PCM.
  - The driver returns its device ID from function 0 (`CH`; `AL` — patch resource number, `CL` — polyphony, bit `0x10` in `AH` — has a DAC): `SNDBLAST`/`ADL`/`PROAUDIO` → `0x00`, patch 3 (OPL2 instruments); `MT32`/`MTBLAST` → `0x0C`, patch 1; `CMS` → `0x09`, patch 101; `TANDY3V`/`IBMPS1` → `0x13`, patch 101; `STD` (speaker) → `0x12`, no patch, 1 voice. Digital samples exist in tracks `0x00`, `0x0C`, `0x13`; the speaker track has none. Tracks `0x06` and `0x16` are not requested by any bundled driver.
- **`LSL1SG.000–019`** — saved games; **`LSL1SG.DIR`** — save directory with their names (binary "number + string" list). Deleting or editing these files affects the user's progress.
- `PKUNZIP.EXE`, `ADVENTUR.ES`, `OLDGAMES.URL` — extraneous files from the distribution, not part of the game.
