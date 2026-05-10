import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_KEYS_LOG = PROJECT_ROOT / "decrypted" / "wechat_keys.log"

from wechat_apps import resolve_wechat_app, resolve_wechat_executable

JS_HOOK = r'''
function buf2hex(buffer) {
    var a = new Uint8Array(buffer); var h = '';
    for (var i = 0; i < a.length; i++) h += ('0' + a[i].toString(16)).slice(-2);
    return h;
}
var found = false;
Process.enumerateModules().forEach(function(m) {
    if (found) return;
    m.enumerateExports().forEach(function(exp) {
        if (found) return;
        if (exp.name === "CCKeyDerivationPBKDF") {
            found = true;
            send({kind: "status", message: "[*] Hook installed on " + m.name});
            Interceptor.attach(exp.address, {
                onEnter: function(args) {
                    this.pwLen = args[2].toInt32();
                    this.saltLen = args[4].toInt32();
                    this.rounds = args[6].toInt32();
                    this.pw = args[1];
                    this.salt = args[3];
                    this.dk = args[7];
                    this.dkLen = args[8].toInt32();
                },
                onLeave: function(retval) {
                    if (this.pwLen < 4 || this.pwLen > 256) return;
                    if (this.saltLen < 4 || this.saltLen > 64) return;
                    var saltHex = buf2hex(this.salt.readByteArray(this.saltLen));
                    var dkHex = buf2hex(this.dk.readByteArray(this.dkLen));
                    var pwHex = buf2hex(this.pw.readByteArray(this.pwLen));
                    send({
                        kind: "pbkdf2",
                        rounds: this.rounds,
                        pw: pwHex,
                        salt: saltHex,
                        dk: dkHex
                    });
                }
            });
        }
    });
});
if (!found) send({kind: "status", message: "[!] CCKeyDerivationPBKDF not found"});
'''


def default_wechat_app() -> str:
    return resolve_wechat_app()


def append_key_record(out_path: Path, payload: dict, include_pw: bool = False) -> None:
    block = (
        f"rounds={payload['rounds']}\n"
        f"salt={payload['salt']}\n"
        f"dk={payload['dk']}\n\n"
    )
    if include_pw:
        block = (
            f"rounds={payload['rounds']}\n"
            f"pw={payload['pw']}\n"
            f"salt={payload['salt']}\n"
            f"dk={payload['dk']}\n\n"
        )
    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(block)


def on_message(msg, _data, out_path: Path, include_pw: bool = False):
    if msg.get("type") == "send":
        payload = msg.get("payload")
        if isinstance(payload, dict):
            kind = payload.get("kind")
            if kind == "status":
                print(f"[frida] {payload.get('message')}", flush=True)
            elif kind == "pbkdf2":
                append_key_record(out_path, payload, include_pw=include_pw)
                print(
                    f"[frida] [PBKDF2] r={payload.get('rounds')} salt={payload.get('salt', '')[:16]}...",
                    flush=True,
                )
        else:
            print(f"[frida] {payload}", flush=True)
    elif msg.get("type") == "error":
        print(f"[frida-error] {msg}", flush=True)


def wait_for_process(device, name: str, timeout: int = 120):
    start = time.time()
    while time.time() - start < timeout:
        for process in device.enumerate_processes():
            if process.name == name:
                return process.pid
        time.sleep(1)
    return None


def summarize_log(out_path: Path) -> int:
    if not out_path.exists():
        return 0
    text = out_path.read_text(encoding="utf-8")
    return len([block for block in text.split("\n\n") if re.search(r"salt=.*\ndk=", block)])


def count_usable_keys(out_path: Path) -> int:
    if not out_path.exists():
        return 0
    text = out_path.read_text(encoding="utf-8")
    count = 0
    for block in text.split("\n\n"):
        if "rounds=256000" not in block:
            continue
        if re.search(r"salt=[a-f0-9]+\ndk=[a-f0-9]+", block):
            count += 1
    return count


def attach_with_retry(device, pid: int, attempts: int = 3, delay: int = 2):
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            print(f"[*] Attaching to PID={pid} attempt={attempt}/{attempts}", flush=True)
            return device.attach(pid)
        except Exception as exc:
            last_error = exc
            print(f"[!] Frida attach failed: {type(exc).__name__}: {exc}", flush=True)
            if attempt < attempts:
                time.sleep(delay)
    raise RuntimeError(
        "Unable to attach Frida to the spawned WeChat process. "
        "Quit the target WeChat app, confirm macOS Developer Tools permissions, and retry spawn mode."
    ) from last_error


def main():
    parser = argparse.ArgumentParser(description="Extract WeChat SQLCipher keys via frida")
    parser.add_argument("--wechat-app")
    parser.add_argument("--bundle-id", help="Launch the WeChat app with this CFBundleIdentifier")
    parser.add_argument("--pid", type=int, help="Attach to an explicit process id in attach mode")
    parser.add_argument("--out", default=str(DEFAULT_KEYS_LOG))
    parser.add_argument("--wait", type=int, default=300)
    parser.add_argument("--min-usable-keys", type=int, default=2, help="Stop early after this many SQLCipher-style keys are captured")
    parser.add_argument("--settle-seconds", type=int, default=8, help="Extra seconds to wait after enough usable keys are seen")
    parser.add_argument("--attach-attempts", type=int, default=3)
    parser.add_argument("--attach-retry-delay", type=int, default=2)
    parser.add_argument("--mode", choices=["spawn", "attach"], default="spawn")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--include-pw", action="store_true", help="Also store the PBKDF input bytes. Off by default because dk is sufficient.")
    args = parser.parse_args()

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and args.reset:
        out_path.unlink()

    try:
        import frida
    except ImportError:
        sys.exit("[!] frida is not installed. Run: python3 -m pip install -r requirements.txt")

    device = frida.get_local_device()

    wechat_app = resolve_wechat_app(bundle_id=args.bundle_id, app_path=args.wechat_app)
    bin_path = resolve_wechat_executable(bundle_id=args.bundle_id, app_path=args.wechat_app)

    if args.mode == "spawn":
        if not os.path.exists(bin_path):
            sys.exit(f"[!] WeChat binary not found: {bin_path}")
        print(f"[*] Spawning {bin_path}", flush=True)
        pid = device.spawn([bin_path])
    elif args.pid:
        pid = args.pid
        print(f"[*] Attach mode. Using PID={pid}", flush=True)
    else:
        print("[*] Attach mode. Launch WeChat now:", flush=True)
        print(f"    {bin_path}", flush=True)
        pid = wait_for_process(device, "WeChat", timeout=120)
        if not pid:
            sys.exit("[!] Timed out waiting for WeChat process")

    session = attach_with_retry(device, pid, attempts=args.attach_attempts, delay=args.attach_retry_delay)
    script = session.create_script(JS_HOOK)
    script.on("message", lambda msg, data: on_message(msg, data, out_path, include_pw=args.include_pw))
    script.load()

    if args.mode == "spawn":
        device.resume(pid)

    print("[*] Hook active. Log in to WeChat and wait. You do not need to open any chat unless sync later fails.", flush=True)
    start = time.time()
    enough_seen_at = None
    try:
        while time.time() - start < args.wait:
            time.sleep(5)
            if out_path.exists():
                usable_keys = count_usable_keys(out_path)
                print(
                    f"[*] elapsed={int(time.time() - start)}s log={out_path.stat().st_size}B keys={summarize_log(out_path)} usable={usable_keys}",
                    flush=True,
                )
                if args.min_usable_keys > 0 and usable_keys >= args.min_usable_keys:
                    if enough_seen_at is None:
                        enough_seen_at = time.time()
                        print("[*] Enough usable keys captured. Waiting briefly for any final key events.", flush=True)
                    elif time.time() - enough_seen_at >= args.settle_seconds:
                        print("[*] Auto-stopping key capture.", flush=True)
                        break
    except KeyboardInterrupt:
        print("[*] Interrupted by user; keeping captured keys and detaching.", flush=True)

    try:
        session.detach()
    except Exception:
        pass
    print(f"[*] Done. Keys written to: {out_path}", flush=True)


if __name__ == "__main__":
    main()
