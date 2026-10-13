# Verification record

Local checks performed on 13 October 2026 using macOS with Python 3.11.16 and Python 3.14.6.

| Check | Observed result |
| --- | --- |
| Offline automated tests | 128 passed on each Python version |
| Ruff lint and formatting | Passed |
| Source and wheel build | Passed |
| Fresh wheel install outside checkout | Passed on Python 3.11 and 3.14 after the review fixes |
| Installed help, preset listing, module and console demos | Passed with application networking blocked |
| Compatibility root launcher | Passed |
| Live HAL scan with desktop delivery disabled | adsb.lol succeeded; healthy empty surveillance result |
| Native desktop visibility and radar click | Unverified: no desktop-control surface available in this environment |
| Hosted GitHub Actions | Configured for Python 3.11 and 3.14; not run or published during this local refactor |

The integration tests exercise synthetic provider payloads through normalization,
tracking, formatting, and console delivery. Notification tests verify native
arguments, escaping, and failure handling with injected subprocess runners.
Neither those tests nor a successful command exit proves visible macOS delivery.

To finish native verification on a desktop session, enable notifications for
terminal-notifier, run live tracking, confirm a visible alert, then click it and
confirm the radar URL opens. Receiver coverage and provider uptime remain
external dependencies even after that check.

## Final review

An independent read-only branch review reproduced three functional edge cases.
All three were fixed with failing-then-passing regression tests and green full
suites on both Python versions:

- Unknown motion/ground telemetry now retains the current incoming warning,
  avoiding duplicate warnings and redundant overhead alerts.
- Identity learned during a metadata cache hit is retained for later sparse
  observations, with the original lookup expiry preserved.
- Numeric conversion rejects oversized integers safely, so a malformed aircraft
  cannot hide valid neighbors. Configuration rejects the same input class cleanly.

No Critical findings or deferred Minor findings remained. The native visual and
click check was set aside because desktop-control surfaces were unavailable;
it remains explicitly unverified rather than being inferred from command tests.

## Implementation decisions

The approved observation model does not contain an operator. Registry enrichment
therefore still fills that missing field even when registration, model, and type
are already known. The cost is one optional lookup for an uncached aircraft.

Native desktop delivery remains unverified in this environment. The cost of
that limitation is that permissions or desktop-specific failures can still block
visible alerts even when automated tests pass; console output remains available.

A temporary disk-space failure interrupted final build verification. After
removing the task’s download cache and recovering temporary space, the normal
isolated build and both fresh-install checks passed.
