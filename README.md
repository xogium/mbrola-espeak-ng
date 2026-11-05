# MBROLA voices for NVDA (eSpeak NG + MBROLA)

An NVDA add-on that adds a synthesizer called "eSpeak NG with MBROLA". It
speaks with MBROLA diphone voices (en1, us1, de6, fr1 and many more), with
eSpeak NG doing the text processing, just as `espeak-ng -v mb-en1` does on
Linux.

Target: NVDA 2026.1 and later, which run as a 64-bit process. Tested
against the NVDA 2026.3 source. Everything native is built for x64 only.

## Why an add-on has to bring its own eSpeak NG

NVDA's built-in eSpeak NG is compiled without MBROLA support. Its build
script (`nvdaHelper/espeak/sconscript`) leaves out `mbrowrap.c` with the
comment "we don't use MBROLA", and it also drops the `voices/mb` data. That
cannot be switched on at run time, so this add-on ships:

1. its own eSpeak NG DLL, built with `USE_MBROLA=ON` and renamed
   `espeak-ng-mbrola.dll` so it can never be confused with NVDA's `espeak.dll`;
2. `mbrola.dll`, the MBROLA engine built as a 64-bit DLL from the official
   open-source code at https://github.com/numediart/MBROLA;
3. eSpeak NG's data, including the MBROLA voice definitions (`voices/mb`) and
   phoneme translation tables (`mbrola_ph`).

It ships no MBROLA *voices*. They have their own licences, mostly
non-commercial, and you import them in NVDA's settings (see below).

## How it fits together

    NVDA
     |- synthDrivers/mbrola_espeak/__init__.py   NVDA SynthDriver (adapter only)
     |    |- _nvda_commands.py                   NVDA speech commands -> core items
     |    |- _nvda_audio.py                      core AudioSink -> nvwave.WavePlayer
     |    `- core/                               no NVDA imports, tested with pytest
     |         engine.py          worker thread, cancel, index reporting
     |         espeak_binding.py  ctypes binding to espeak-ng-mbrola.dll
     |         ssml.py            speech items -> eSpeak SSML
     |         voice_catalog.py   eSpeak's MBROLA voice definitions
     |         voice_store.py     import / list / remove voices (file or zip)
     |         voice_sync.py      mirror the store into espeak-ng-data/mbrola
     |         voice_file.py      MBROLA database header check
     `- globalPlugins/mbrolaVoiceManager/         "MBROLA voices" settings panel

Imported voices are kept in `<NVDA user config>\mbrolaVoices`, so add-on
updates do not delete them. When the synthesizer starts, they are
hard-linked (or copied) into the add-on's `espeak-ng-data\mbrola`, which is
the only place eSpeak NG looks on Windows.

More detail: `docs/ARCHITECTURE.md`. Building: `docs/BUILDING.md`.

## Translations

The add-on is available in English and French. NVDA picks the language of
its own interface.

- Messages: `addon/locale/<lang>/LC_MESSAGES/nvda.po`. Only the `.po` is kept
  in the repository; `tools/build_addon.py` compiles it to the `nvda.mo` that
  NVDA loads.
- Add-on summary and description: `addon/locale/<lang>/manifest.ini`.
- User guide: `addon/doc/<lang>/readme.html`.

`tools/i18n.py` needs nothing but Python:

    python tools/i18n.py update fr    # add new messages to the French file, drop removed ones
    python tools/i18n.py check        # untranslated, fuzzy or broken entries
    python tools/i18n.py pot          # template for a new language

Every message needs a `# Translators:` comment, and a translation must keep
the same `{placeholders}` and one `&` for a keyboard shortcut. The tests
check all of this, and the build refuses a translation with wrong
placeholders.

## Getting voices

Download a voice from https://github.com/numediart/MBROLA-voices (each voice
is in `data/<name>/`). In NVDA, open NVDA menu > Preferences > Settings >
MBROLA voices, choose "Import voice...", and pick either the voice file
itself (for example `en1`) or a `.zip` that contains it. Then choose the
"eSpeak NG with MBROLA" synthesizer and pick a voice.

The file must keep its original name (`en1`, `de6`, ...). That name is how
eSpeak NG knows which voice it is.

## Licences

- Add-on code in this repository: GPL-3.0-or-later (see `LICENSE`).
- eSpeak NG: GPL-3.0-or-later.
- MBROLA engine: AGPL-3.0-or-later. Its section 13 is about network use, which
  an NVDA add-on does not involve. Distributing the binary requires offering
  the corresponding source, which the pinned commit plus `native/patches`
  provides.
- MBROLA voices: each voice has its own licence, usually free for
  non-commercial use only. Never commit them to this repository.

## Branches

The work is split into three stacked branches, each building on the previous:

1. `agent/native-build`: pinned sources, patches, build script, 64-bit check, CI.
2. `agent/core`: the NVDA-independent core, with unit and end-to-end tests.
3. `agent/nvda-addon`: the NVDA synth driver, settings panel, packaging.

Each branch contains the previous one, so merging `agent/nvda-addon` alone
brings in everything. Merging them one at a time, in that order, gives the
same result. Every branch passes its own tests.

## Status and testing

What has been verified, on 64-bit Linux, using the harness that mirrors
the Windows DLL path:

- MBROLA builds and runs as a 64-bit library; the real en1 and us1 voices
  speak through eSpeak NG via the add-on's own Python binding.
- The whole add-on stack (driver, engine, voice import, index reporting,
  cancel, voice switching, tearing the driver down and creating it again)
  runs against the real libraries with fake NVDA modules: 145 tests.

Not yet verified:

- The Windows build itself. The CI job `windows-native` builds both DLLs
  with MSVC x64, checks they are x64, runs the end-to-end tests on Windows
  and packages the `.nvda-addon`, but it has not been run yet. Push the
  branches to GitHub to run it.
- Running inside a real NVDA 2026.3: the settings panel (wx) and audio
  through nvwave have only been checked against NVDA's source, not run.

## Known limitations (v0.2)

- Automatic language switching is not offered with this synthesizer. eSpeak
  NG reports unreliable timing when a sentence switches between an MBROLA
  voice (16 kHz) and a normal eSpeak voice (22.05 kHz), and mixing the two
  sample rates in one stream would play part of the sentence at the wrong
  speed. Proper support means synthesizing each language segment
  separately; that is planned.
- No "rate boost" yet (NVDA's built-in eSpeak uses the sonic library for it).
- No variants (the "!v" voice variants) yet.
