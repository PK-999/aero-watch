# Contributing

Use Python 3.11 or newer. Install the development tools from the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Before changing behavior, add a regression test using synthetic observations or
provider fixtures. Keep the tracker and prediction functions free of network,
sleep, and notification calls. Inject HTTP sessions and subprocess runners at
their boundaries. Tests block live HTTP requests automatically.

Run the checks used by CI:

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m build
python scripts/verify_install.py dist/*.whl
```

The installation check downloads dependencies into a temporary virtual
environment, then blocks network access while exercising the installed commands
outside the checkout. Temporary files are removed on exit.

Use `aero-watch --demo` to inspect the complete alert sequence without APIs or
desktop notifications. Live API checks are opt-in:

```bash
aero-watch hal_area --once --no-notifications
```

For changes to native notifications, run a macOS smoke check with notifications
enabled and confirm both the visible alert and radar click. Automated tests
verify command construction and failure handling; they cannot confirm macOS
permissions, Focus settings, or visual delivery.

Keep changes focused, preserve author attribution and the MIT license, and
describe behavior changes and verification in your pull request. When changing
the default settings or locations, update both `config/` and
`src/aerowatch/data/`: the former is editable checkout configuration, the latter
ships in the installed package. Provider fixtures must remain synthetic.
