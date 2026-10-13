"""Install a built wheel in isolation and exercise its offline entry points."""

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        parser.error("Pass an existing .whl file built by python -m build")
    with tempfile.TemporaryDirectory(prefix="aerowatch-install-") as temporary:
        root = Path(temporary)
        environment = root / "environment"
        venv.create(environment, with_pip=True)
        binaries = environment / ("Scripts" if os.name == "nt" else "bin")
        python = binaries / ("python.exe" if os.name == "nt" else "python")
        executable = binaries / ("aero-watch.exe" if os.name == "nt" else "aero-watch")
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", str(wheel)],
            cwd=root,
            env=env,
            check=True,
            timeout=180,
        )
        # Prevent smoke commands from relying on accidental network connectivity.
        guard = root / "offline"
        guard.mkdir()
        (guard / "sitecustomize.py").write_text(
            "import socket\n"
            "def reject(*args, **kwargs):\n"
            "    raise RuntimeError('Installed smoke commands must stay offline')\n"
            "socket.getaddrinfo = reject\n"
            "socket.socket.connect = reject\n",
            encoding="utf-8",
        )
        env["PYTHONPATH"] = str(guard)
        for command in (
            [str(executable), "--help"],
            [str(executable), "--list-locations"],
            [str(executable), "--demo"],
            [str(python), "-m", "aerowatch", "--demo"],
        ):
            result = subprocess.run(
                command,
                cwd=root,
                env=env,
                check=True,
                timeout=10,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if "--list-locations" in command and not all(
                key in result.stdout for key in ("hal_area", "blr_airport", "entire_blr")
            ):
                raise RuntimeError("Installed package is missing location presets")
            if "--demo" in command:
                expected = {"INCOMING": 1, "TAKEOFF": 1, "DEPARTED": 2}
                if any(result.stdout.count(label) != count for label, count in expected.items()):
                    raise RuntimeError("Installed demo is missing expected flight events")
                if "synthetic" not in result.stdout.lower():
                    raise RuntimeError("Demo must identify synthetic observations")
            print(f"PASS: {' '.join(command[1:])}")
    print("Installed wheel verified outside the checkout; all smoke commands stayed offline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
