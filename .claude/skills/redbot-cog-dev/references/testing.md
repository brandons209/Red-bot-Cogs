# Testing cog logic without Red

Loading Red and discord.py to test a scoring function is slow and awkward, so the interesting logic
never gets tested. The fix that worked for `antibot`: keep the decision logic in modules that import
nothing from discord or redbot, and drive time through a caller-supplied `now`. Those modules run
and test standalone; the cog file is only the wiring.

## What to separate

Pull out anything that is a pure function of its inputs: similarity scoring, clustering, threshold
and gate decisions, hashing. `antibot` splits these into `simhash.py`, `signatures.py`, and
`detectors.py`, none of which import discord or redbot. The cog (`antibot.py`) reads Config, builds
plain inputs, calls into those modules, and dispatches actions on the result.

Signs a function belongs in a pure module: it takes ids, counts, timestamps, and strings rather than
`discord.Member` objects; it returns a decision or score rather than sending a message; and it has
branching worth testing (a gate with several conditions, a re-arm rule, a tie-break).

## Make time and imports injectable

Take the current time as an argument so a test can replay a sequence deterministically:

```python
def record(self, ..., now: float, *, window, cooldown):
    recent = [e for e in self._events if now - e.ts <= window]
    ...
```

Support running the file both inside the package and standalone with a dual import, so tests can put
the cog directory on `sys.path` without installing anything:

```python
try:
    from .simhash import hamming      # package import (inside the cog)
except ImportError:
    from simhash import hamming       # standalone import (tests)
```

## Writing the tests

With logic isolated, tests are plain assertions over decisions, no bot fixture needed. Feed a
scripted timeline and check the trip:

```python
from detectors import CrossChannelDetector

def test_burst_trips_once_then_rearms():
    d = CrossChannelDetector()
    # same message across 3 channels within the window -> one trip
    for chan in (1, 2, 3):
        tripped, _ = d.record(g, u, chan, mid, nhash="x", simhash=0, now=100.0,
                              channels=3, window=10, simhash_distance=8, cooldown=60)
    assert tripped
    # still bursting inside the cooldown -> no second trip
    tripped, _ = d.record(g, u, 4, mid, nhash="x", simhash=0, now=105.0,
                          channels=3, window=10, simhash_distance=8, cooldown=60)
    assert not tripped
```

The repo ships no committed tests today. When you add a new pure-logic module, land its tests with
it in a `tests/` directory next to the cog, and keep them import-light so they run under plain
`pytest` without a Red install.
