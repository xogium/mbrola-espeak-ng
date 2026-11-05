# Architecture

## Layers and boundaries

    NVDA ------------------------------------------------------------
      synthDrivers/mbrola_espeak/__init__.py    SynthDriver: settings, voice list, wiring
      synthDrivers/mbrola_espeak/_nvda_commands.py   NVDA speech commands -> core items
      synthDrivers/mbrola_espeak/_nvda_audio.py      AudioSink on top of nvwave.WavePlayer
      globalPlugins/mbrolaVoiceManager/         settings panel (wx) for importing voices
    ------------------------------------------------------------------ no NVDA below this line
      core/voice_library.py    wiring of catalog + store + sync
      core/engine.py           worker thread, ordering, cancel, index timing
      core/espeak_binding.py   ctypes <-> espeak-ng-mbrola.dll
      core/ssml.py             speech items -> SSML
      core/voice_store.py      import/list/remove voice files and zips
      core/voice_sync.py       store -> espeak-ng-data/mbrola
      core/voice_catalog.py    parse espeak-ng-data/voices/mb/*
      core/voice_file.py       MBROLA header check
      core/audio.py            AudioSink protocol, split audio at index marks
      core/params.py           0-100 sliders <-> eSpeak values
      core/layout.py           every path in one place
    ------------------------------------------------------------------ native
      espeak-ng-mbrola.dll  --LoadLibraryA("mbrola.dll")-->  mbrola.dll

Rules:

- `core` never imports NVDA, wx or Windows-only modules, so all of it runs
  under pytest on any OS.
- The NVDA modules only translate and wire. All decisions live in `core`.
- Dependencies inside `core` only point downwards (see `core/__init__.py`).
- Each core module has one job and its own test file.

## Threads

There is one worker thread per engine. It makes every eSpeak NG call
(`set_voice`, `set_parameter`, `synth`), so the C library is never entered
from two threads at once. NVDA's thread only queues work and reads cached
values, so it never waits on synthesis.

Cancelling is lock-free. The engine bumps a generation counter and stops
the audio sink. The synthesis callback returns "abort" as soon as it sees
the new generation, queued utterances from the old generation are skipped,
and index callbacks from the old generation are dropped. Voice and
parameter changes are never dropped by a cancel.

## Audio and indexes

eSpeak NG runs in `AUDIO_OUTPUT_SYNCHRONOUS` mode and hands each block of
16-bit mono PCM to a callback. The engine splits each block at the `<mark>`
positions and feeds the pieces to the sink, attaching "index reached"
callbacks. NVDA's `WavePlayer` runs those callbacks when that audio has
actually been played, which is what say-all and cursor tracking rely on.

Positions come from `espeak_EVENT.sample`, a sample count, not from
`audio_position`, which is in milliseconds. eSpeak NG computes the
milliseconds using whatever sample rate is current when the event is
created, and that is wrong around MBROLA voice changes.

## Sample rate

MBROLA voices are almost all 16 kHz; eSpeak NG's own voices are 22.05 kHz.
The sink is told the rate after every voice change (`espeak_ng_GetSampleRate`).
Within one utterance the rate is assumed constant, which is why automatic
language switching (which can jump between an MBROLA voice and an eSpeak
voice mid-sentence) is not advertised to NVDA (still true in v0.2).

## Voices

    <NVDA config>\mbrolaVoices\en1          the store (survives add-on updates)
            |  hard link, or copy if linking fails
            v
    <add-on>\synthDrivers\mbrola_espeak\espeak-ng-data\mbrola\en1   where eSpeak NG looks

The store is the source of truth. `voice_sync` runs when the synthesizer
starts and after every import or removal, and only touches files named like
known MBROLA databases.

Importing checks the MBROLA header (magic, version, diphone count, sample
rate) before writing. Files are written to a temporary name and renamed
into place. Zip members are only ever used by base name, so paths such as
`../../x` cannot escape the store, and oversized members are refused.

## Why the DLL loading works

eSpeak NG calls `LoadLibraryA("mbrola.dll")` with a bare name. Windows would
search NVDA's program folder, not the add-on's. But if a module with that
base name is already loaded in the process, Windows returns it. The binding
therefore loads `mbrola.dll` from its full path *before* it loads eSpeak NG.
This needs no change to eSpeak NG and no change to the process-wide DLL
search path.

The eSpeak NG DLL is named `espeak-ng-mbrola.dll` so it can never be
confused with NVDA's own `espeak.dll`, which may be loaded in the same
process when the user switches synthesizers.
