"""One-command launcher for EventEats.

Usage:
    python run.py

What it does (in order):
    1. Self-bootstraps into the project's `.venv` (creates it if missing).
    2. Installs requirements.txt if Django / stripe / dotenv aren't importable.
    3. Verifies the Stripe CLI is installed and `stripe login` has been done.
    4. Fetches the webhook signing secret via `stripe listen --print-secret`
       and writes it into `.env` (only that one line is touched).
    5. Runs `python manage.py migrate --noinput`.
    6. Starts `stripe listen --forward-to localhost:8000/stripe/webhook/`
       and `python manage.py runserver 127.0.0.1:8000` concurrently,
       streaming both outputs to the current terminal with [stripe] / [django]
       prefixes.
    7. On Ctrl+C, terminates both child processes cleanly.

This file is purely additive: nothing else in the project is modified, and
the original manual workflow described in WEBHOOKS_SETUP.md still works.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
REQUIREMENTS = ROOT / "requirements.txt"
MANAGE_PY = ROOT / "manage.py"

IS_WINDOWS = os.name == "nt"
VENV_PY = VENV_DIR / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")

DJANGO_HOST = "127.0.0.1"
DJANGO_PORT = "8000"
WEBHOOK_PATH = "/stripe/webhook/"


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------

def info(msg: str) -> None:
    print(f"[run] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[run] WARNING: {msg}", flush=True)


def fail(msg: str, code: int = 1) -> "None":
    print(f"[run] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Step 1: re-exec into the project's venv
# ---------------------------------------------------------------------------

def ensure_in_venv() -> None:
    """If we're not already running with `.venv`'s python, switch to it.

    Creates `.venv` first if it does not exist.
    """
    try:
        already = Path(sys.executable).resolve() == VENV_PY.resolve()
    except FileNotFoundError:
        already = False

    if already:
        return

    if not VENV_PY.exists():
        info(f"Creating virtual environment at {VENV_DIR} ...")
        try:
            subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
        except subprocess.CalledProcessError as exc:
            fail(f"Failed to create virtual environment: {exc}")

    info(f"Re-launching inside virtual environment: {VENV_PY}")
    try:
        os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])
    except OSError as exc:
        fail(f"Failed to re-exec into venv python: {exc}")


# ---------------------------------------------------------------------------
# Step 2: install dependencies if needed
# ---------------------------------------------------------------------------

def ensure_dependencies() -> None:
    missing = []
    for mod in ("django", "stripe", "dotenv"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)

    if not missing:
        return

    info(f"Installing Python dependencies (missing: {', '.join(missing)}) ...")
    if not REQUIREMENTS.exists():
        fail(f"requirements.txt not found at {REQUIREMENTS}")

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)]
        )
    except subprocess.CalledProcessError as exc:
        fail(f"pip install failed: {exc}")


# ---------------------------------------------------------------------------
# Step 3: Stripe CLI + login checks
# ---------------------------------------------------------------------------

def stripe_install_hint() -> str:
    if sys.platform == "darwin":
        return (
            "Install the Stripe CLI once with Homebrew:\n"
            "    brew install stripe/stripe-cli/stripe\n"
            "Then run: stripe login   (approve in your browser)"
        )
    if IS_WINDOWS:
        return (
            "Install the Stripe CLI once. Easiest options:\n"
            "    scoop install stripe\n"
            "    OR download from https://github.com/stripe/stripe-cli/releases/latest\n"
            "Then run: stripe login   (approve in your browser)"
        )
    return (
        "Install the Stripe CLI once. See:\n"
        "    https://docs.stripe.com/stripe-cli\n"
        "Then run: stripe login   (approve in your browser)"
    )


def find_stripe_cli() -> str:
    path = shutil.which("stripe")
    if not path:
        print(
            "[run] ERROR: Stripe CLI was not found on your PATH.\n\n"
            + stripe_install_hint(),
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)
    return path


def stripe_is_logged_in(stripe_path: str) -> bool:
    """Return True if `stripe` has an active account configured."""
    try:
        result = subprocess.run(
            [stripe_path, "config", "--list"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False

    if result.returncode != 0:
        return False

    text = (result.stdout or "") + (result.stderr or "")
    lowered = text.lower()
    if "test_mode_api_key" in lowered or "live_mode_api_key" in lowered:
        return True
    if "device_name" in lowered and "account_id" in lowered:
        return True
    return False


def ensure_stripe_ready() -> str:
    stripe_path = find_stripe_cli()
    if not stripe_is_logged_in(stripe_path):
        print(
            "[run] ERROR: Stripe CLI is installed but not logged in.\n\n"
            "Please run this once in your terminal, approve in the browser,\n"
            "then re-run `python run.py`:\n\n"
            "    stripe login\n",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)
    return stripe_path


# ---------------------------------------------------------------------------
# Step 4: webhook secret -> .env
# ---------------------------------------------------------------------------

def ensure_env_file() -> None:
    if ENV_FILE.exists():
        return
    if ENV_EXAMPLE.exists():
        info(".env not found; copying from .env.example")
        ENV_FILE.write_text(ENV_EXAMPLE.read_text())
        warn(
            "A new .env was created from .env.example. "
            "Please fill in STRIPE_PUBLISHABLE_KEY and STRIPE_SECRET_KEY, "
            "then re-run `python run.py`."
        )
        sys.exit(1)
    fail(".env not found and .env.example is missing; cannot continue.")


def read_env_var(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line[len(key) + 1:]
    return None


def set_env_var(path: Path, key: str, value: str) -> bool:
    """Update or add `KEY=value` in the env file. Returns True if changed."""
    lines = path.read_text().splitlines() if path.exists() else []
    out: list[str] = []
    found = False
    changed = False
    new_line = f"{key}={value}"
    for ln in lines:
        if ln.startswith(f"{key}="):
            found = True
            if ln != new_line:
                changed = True
                out.append(new_line)
            else:
                out.append(ln)
        else:
            out.append(ln)
    if not found:
        out.append(new_line)
        changed = True

    if changed:
        path.write_text("\n".join(out) + "\n")
    return changed


def fetch_webhook_secret(stripe_path: str) -> str:
    info("Fetching Stripe webhook signing secret ...")
    try:
        result = subprocess.run(
            [stripe_path, "listen", "--print-secret"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        fail("`stripe listen --print-secret` timed out. Is your network OK?")
    except OSError as exc:
        fail(f"Could not run Stripe CLI: {exc}")

    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip()
        fail(
            "Could not fetch the webhook signing secret from Stripe CLI.\n"
            f"Stripe CLI said: {msg}\n"
            "Try running `stripe login` again."
        )

    secret = (result.stdout or "").strip().splitlines()[-1].strip() if result.stdout else ""
    if not secret.startswith("whsec_"):
        fail(
            "Stripe CLI did not return a webhook secret. "
            f"Got: {secret!r}. Try running `stripe login` again."
        )
    return secret


def sync_webhook_secret(stripe_path: str) -> None:
    secret = fetch_webhook_secret(stripe_path)
    current = read_env_var(ENV_FILE, "STRIPE_WEBHOOK_SECRET")
    if current == secret:
        info("STRIPE_WEBHOOK_SECRET in .env is already up to date.")
        return
    set_env_var(ENV_FILE, "STRIPE_WEBHOOK_SECRET", secret)
    info("Updated STRIPE_WEBHOOK_SECRET in .env.")


# ---------------------------------------------------------------------------
# Step 5: migrations
# ---------------------------------------------------------------------------

def run_migrations() -> None:
    info("Running database migrations ...")
    try:
        subprocess.check_call(
            [sys.executable, str(MANAGE_PY), "migrate", "--noinput"],
            cwd=str(ROOT),
        )
    except subprocess.CalledProcessError as exc:
        fail(f"`manage.py migrate` failed: {exc}")


# ---------------------------------------------------------------------------
# Step 6: spawn stripe listen + runserver concurrently
# ---------------------------------------------------------------------------

def _stream_output(proc: subprocess.Popen, prefix: str) -> None:
    assert proc.stdout is not None
    try:
        for raw in iter(proc.stdout.readline, b""):
            if not raw:
                break
            try:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            except Exception:
                line = repr(raw)
            print(f"{prefix} {line}", flush=True)
    except Exception as exc:
        print(f"{prefix} <output stream error: {exc}>", flush=True)


def _spawn(cmd: list[str], cwd: Path) -> subprocess.Popen:
    creation_flags = 0
    preexec_fn = None
    if IS_WINDOWS:
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        preexec_fn = os.setsid  # so we can signal the whole group on shutdown

    return subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        creationflags=creation_flags,
        preexec_fn=preexec_fn,
    )


def _terminate(proc: subprocess.Popen, label: str) -> None:
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            except Exception:
                proc.terminate()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception:
                proc.terminate()
    except Exception as exc:
        print(f"[run] could not terminate {label}: {exc}", flush=True)

    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            if IS_WINDOWS:
                proc.kill()
            else:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except Exception:
                    proc.kill()
        except Exception:
            pass


def run_servers(stripe_path: str) -> int:
    forward_url = f"localhost:{DJANGO_PORT}{WEBHOOK_PATH}"
    stripe_cmd = [stripe_path, "listen", "--forward-to", forward_url]
    django_cmd = [
        sys.executable,
        str(MANAGE_PY),
        "runserver",
        f"{DJANGO_HOST}:{DJANGO_PORT}",
    ]

    info(f"Starting Stripe webhook forwarder -> {forward_url}")
    stripe_proc = _spawn(stripe_cmd, ROOT)

    # Give the Stripe CLI a moment so its banner prints first.
    time.sleep(0.5)

    info(f"Starting Django dev server -> http://{DJANGO_HOST}:{DJANGO_PORT}")
    django_proc = _spawn(django_cmd, ROOT)

    threads = [
        threading.Thread(
            target=_stream_output, args=(stripe_proc, "[stripe]"), daemon=True
        ),
        threading.Thread(
            target=_stream_output, args=(django_proc, "[django]"), daemon=True
        ),
    ]
    for t in threads:
        t.start()

    shutdown_started = {"value": False}

    def shutdown(*_args) -> None:
        if shutdown_started["value"]:
            return
        shutdown_started["value"] = True
        print("\n[run] Shutting down ...", flush=True)
        _terminate(django_proc, "django")
        _terminate(stripe_proc, "stripe")

    if not IS_WINDOWS:
        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)
    else:
        signal.signal(signal.SIGINT, shutdown)
        try:
            signal.signal(signal.SIGBREAK, shutdown)  # type: ignore[attr-defined]
        except Exception:
            pass

    exit_code = 0
    try:
        while True:
            stripe_done = stripe_proc.poll()
            django_done = django_proc.poll()
            if stripe_done is not None and django_done is not None:
                exit_code = django_done if django_done is not None else stripe_done
                break
            if stripe_done is not None and not shutdown_started["value"]:
                warn(f"Stripe CLI exited (code {stripe_done}); stopping Django too.")
                shutdown()
                exit_code = stripe_done
                break
            if django_done is not None and not shutdown_started["value"]:
                warn(f"Django exited (code {django_done}); stopping Stripe too.")
                shutdown()
                exit_code = django_done
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        shutdown()

    for t in threads:
        t.join(timeout=2)

    return exit_code


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if not MANAGE_PY.exists():
        fail(f"manage.py not found at {MANAGE_PY}; run this from the project root.")

    ensure_in_venv()
    ensure_dependencies()
    ensure_env_file()
    stripe_path = ensure_stripe_ready()
    sync_webhook_secret(stripe_path)
    run_migrations()
    return run_servers(stripe_path)


if __name__ == "__main__":
    sys.exit(main())
