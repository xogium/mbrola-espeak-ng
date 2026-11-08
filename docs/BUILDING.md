# Building

There are two native builds. Both use `tools/build_native.py`, which needs
Python 3.11 or later, `git`, `cmake` and a C compiler.

The script checks out the exact commits pinned in `native/versions.json`,
applies the patches in `native/patches/`, builds, and copies the results
into a staging folder.

## Windows (the real add-on)

Requirements: Visual Studio 2022 or Build Tools 2022 with the "Desktop
development with C++" workload, CMake 3.16 or later, Git, Python 3.11 or later.

    python tools\build_native.py --target windows

This puts the following into `addon\synthDrivers\mbrola_espeak\`:

    bin\espeak-ng-mbrola.dll   eSpeak NG 1.52.0 built with USE_MBROLA=ON (x64)
    bin\mbrola.dll             MBROLA one-channel library (x64)
    espeak-ng-data\            eSpeak NG data, including voices\mb and mbrola_ph
    espeak-ng-data\mbrola\     empty; imported voices are linked here at run time

Then check the architecture and build the add-on package:

    python tools\check_pe_arch.py addon\synthDrivers\mbrola_espeak\bin\*.dll
    python tools\build_addon.py

Both DLLs use the static C runtime (`/MT`), so they do not depend on any
particular Visual C++ runtime being installed.

You do not need a Windows machine for this. The `windows-native` CI job on
GitHub Actions does the same thing and uploads the result as an artifact.

## Linux test harness (for end-to-end tests only)

    sudo apt-get install cmake ninja-build      # or your distro's equivalent
    python tools/build_native.py --target linux-harness

This builds `libmbrola.so` and `libespeak-ng.so` into `build/linux-stage/`.
Nothing from it is shipped.

On Windows, eSpeak NG reaches MBROLA through a DLL: `LoadLibraryA("mbrola.dll")`
followed by `GetProcAddress`. On Linux, upstream eSpeak NG normally starts the
`mbrola` *program* and talks to it over pipes, which is a different code path.
So the harness build replaces eSpeak NG's `mbrowrap.c` with
`native/linux-test-harness/mbrowrap_dlopen.c`, which does the same thing as
the Windows code using `dlopen`/`dlsym`. The end-to-end tests then exercise
the same library API, the same patched sources and the same Python code that
run inside NVDA.

## Running the tests

    python -m pip install pytest
    python -m pytest -m "not e2e"                  # unit tests, no native code needed

    # end-to-end: needs the harness build and at least the en1 voice
    git clone --depth 1 --filter=blob:none --sparse https://github.com/numediart/MBROLA-voices test-voices
    git -C test-voices sparse-checkout set data/en1 data/us1
    MBROLA_ESPEAK_STAGE=build/linux-stage MBROLA_TEST_VOICES=test-voices/data python -m pytest -m e2e

## Patches carried

Each patch starts with a plain-language explanation. In short:

- `mbrola/0001`: a function-pointer return type mismatch (`int` vs `long`)
  in the library build. On 64-bit Linux this is undefined behaviour. On
  Windows x64 it happens to be harmless.
- `mbrola/0002`: `close_MBR()` crashed when no voice was loaded, and
  `init_MBR()` leaked the previous voice on every voice switch.
- `espeak-ng/0001`: after an MBROLA voice had been used, normal eSpeak NG
  voices stayed at the MBROLA sample rate (16 kHz instead of 22.05 kHz).
- `espeak-ng/0002`: with MBROLA voices, pitch changes from SSML
  (`<prosody pitch>`) were applied only after the phonemes they were meant
  for had been sent to MBROLA, so they had no effect. NVDA uses this to
  raise the pitch of capital letters ("Capital pitch change percentage").

All four are worth sending upstream.
