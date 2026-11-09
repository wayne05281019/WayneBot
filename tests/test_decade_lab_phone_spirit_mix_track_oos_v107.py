# -*- coding: utf-8 -*-
"""v107 sealed keep mask shim：鍵集合煙測（不改買訊）。"""
from __future__ import annotations

from scripts.decade_lab_phone_spirit_mix_track_oos_v107 import BUY_SIGNAL, PHONE_SYNC, _champ_masks


def test_v107_flags_and_callable():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert callable(_champ_masks)
