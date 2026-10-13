# Verification record

Local checks performed on 13 October 2026 using macOS and Python 3.14.6.

| Check | Observed result |
| --- | --- |
| Offline automated tests | 117 passed |
| Ruff lint and formatting | Passed |
| Source and wheel build | Passed |
| Fresh wheel install outside checkout | Passed |
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
