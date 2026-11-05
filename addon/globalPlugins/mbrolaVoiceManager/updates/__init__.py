"""Updating the add-on from its GitHub releases, without any NVDA or wx code.

Like ``synthDrivers/mbrola_espeak/core``, nothing in this package imports
NVDA, wx or Windows-only modules, so all of it runs under plain pytest. The
NVDA side (threads, dialogs, installing the package) is ``../update_ui.py``.

Module map (dependencies point downwards only):

    messages   -> errors, releases          what the user is told (translatable)
    download   -> errors, releases, version  fetch the package and prove it is ours
    releases   -> errors, version            the latest GitHub release -> an offer, or none
    schedule                                 "check automatically" setting, once a day
    web        -> errors                     the only module that touches the network
    version                                  "v0.2.0" -> (0, 2, 0)
    errors                                   UpdateError and its kinds
"""
