"""Shared test settings. The runs' politeness pauses are real seconds between real requests; a test asks fakes in
memory, so it need not wait (the suite took about 3.5 minutes, nearly all of it these pauses)."""

import functools

import pytest


@pytest.fixture(autouse=True)
def no_politeness_pauses(monkeypatch):
    from agoranome_inspector import measure, signs

    monkeypatch.setattr(measure, "Settings", functools.partial(
        measure.Settings, host_pause=0, retry_pause=0, confirm_pause=0))
    chunk, _, sleep = signs.ChainReader.__init__.__defaults__
    monkeypatch.setattr(signs.ChainReader.__init__, "__defaults__", (chunk, 0, sleep))
