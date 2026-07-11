# Threshold pings need hysteresis

Any feature that pings when a metric crosses a threshold cannot use a raw compare. Both reference
cogs shipped that naive version first and both had to be fixed in production: a metric hovering near
the threshold, or a brief dip, re-pings on every poll. This is the single bug that cost the most
iteration, so reach for the model below from the start.

## The failure the naive version causes

`serverwatch` pings a role when a game server fills past N players. The first version pinged
whenever `current >= threshold`. Two things went wrong:

- A server averaging 16 players against a threshold of 12 pinged every cooldown period forever,
  because it never dropped below 12.
- Even after adding a cooldown, a TF2 map change briefly empties and refills the server; the count
  dips under 12 and crosses back up, which the code read as a fresh crossing and pinged again.

The lesson: "crossed the threshold" is not the same as "went from clearly-below to at-or-above." You
need state that remembers whether this rule has already fired, and a floor low enough that normal
noise near the threshold does not re-arm it.

## The model

Give each rule three pieces of state: `armed` (is it allowed to fire), `below_since` (when it
started sitting below the re-arm floor), and `last_fire`. Then:

- **Fire** only when at or above the threshold, `armed` is true, and at least `cooldown` seconds
  have passed since the last fire. On firing, set `armed = False`.
- **Re-arm** only after the metric drops below a floor set at a *percentage* of the threshold
  (`rearm_pct`, e.g. 60%) and stays there for a grace period (`rearm_grace`). A dip that stays above
  the floor, like a map-change shuffle, leaves the rule spent so it cannot re-ping.
- **Hold** on missing data (server offline / query failed): neither fire nor re-arm, so a flapping
  source does not generate noise.

The percentage floor is what defeats the hover case: a 16-player rule at 60% re-arms only under ~10,
so a population bouncing between 15 and 18 never re-arms. The grace period defeats the brief-dip
case. The cooldown is a final backstop against any fast crossing.

```python
if current >= threshold:
    below_since = None
    if armed and (now - last_fire) >= cooldown:
        # ... send the ping ...
        armed = False
        last_fire = now
else:
    floor = threshold * rearm_pct / 100.0
    if current < floor:
        if below_since is None:
            below_since = now
        if not armed and (now - below_since) >= rearm_grace:
            armed = True
    else:
        below_since = None  # above the floor: cancel any pending re-arm
```

## Applying it elsewhere

`antibot`'s `CrossChannelDetector` reuses the same armed/cooldown shape for a burst of identical
messages across channels: fire once on the burst, re-arm only after the user goes quiet. A simpler
variant fits detectors that *want* to keep acting on ongoing abuse: `antibot`'s role-ping detector
uses a pure cooldown gate with no re-arm, so if the offender can still ping, they keep getting
actioned instead of going silent after one hit.

Pick per feature: hysteresis when repeated alerts are noise (server filled up, burst happened);
pure cooldown when repeated action is the point (the abuser is still abusing). Expose
`rearm_pct`, `rearm_grace`, and `cooldown` as config so an operator can tune them per server.
