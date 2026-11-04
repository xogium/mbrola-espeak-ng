"""NVDA-independent core of the MBROLA for eSpeak NG add-on.

Nothing in this package imports NVDA, wx or Windows-only modules, so all of it
runs under plain pytest on any OS. The NVDA-facing adapters live one level up
(``synthDrivers/mbrola_espeak/__init__.py``, ``_nvda_audio.py``,
``_nvda_commands.py``) and in ``globalPlugins/mbrolaVoiceManager``.

Module map (dependencies point downwards only):

    voice_library  -> voice_catalog, voice_store, voice_sync, layout
    engine         -> audio, espeak_binding, params
    ssml           -> speech_items
    voice_store    -> voice_file
    errors         (used by all)
"""
