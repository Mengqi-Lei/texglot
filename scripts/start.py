"""Open the local app, checking service ownership before starting a second copy."""

import argparse
import json
import os
import platform
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.compiler import available_compilers  # noqa: E402
from app.config import DATA  # noqa: E402
from app.platforms import configure_stdio  # noqa: E402


def main():
    configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        type=int,
        default=int(
            os.environ.get("TEXGLOT_PORT", os.environ.get("MOYI_PORT", "8765"))
        ),
    )
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="check installation without starting a service",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    built = (ROOT / "frontend/dist/index.html").exists()
    if args.check:
        compilers = available_compilers()
        print(
            json.dumps(
                {
                    "platform": platform.system(),
                    "python": sys.executable,
                    "frontend": built,
                    "compilers": compilers,
                },
                ensure_ascii=False,
            )
        )
        return 0 if built and any(compilers.values()) else 1
    url = f"http://127.0.0.1:{args.port}"
    open_browser = (
        not args.no_browser
        and os.environ.get("TEXGLOT_NO_BROWSER", os.environ.get("MOYI_NO_BROWSER"))
        != "1"
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url + "/api/health", timeout=2) as response:
            health = json.load(response)
    except urllib.error.HTTPError:
        raise SystemExit(f"Port {args.port} belongs to another application.") from None
    except (OSError, ValueError):
        health = None
    if health is not None:
        if health.get("name") != "TeXGlot" or not health.get("ok"):
            raise SystemExit(f"Port {args.port} belongs to another application.")
        if Path(health.get("data_dir", "")).resolve() != DATA:
            raise SystemExit(
                "Another TeXGlot data directory is using this port. Set TEXGLOT_PORT to a different port."
            )
        print("TeXGlot已经在运行：" + url)
        if open_browser:
            webbrowser.open(url)
        return 0
    if not built:
        raise SystemExit(
            "请先运行 install-texglot.cmd"
            if os.name == "nt"
            else "请先运行 ./scripts/setup.sh"
        )
    os.chdir(ROOT)
    print(
        "TeXGlot已启动：" + url + "\n关闭此终端或按 Ctrl+C 可停止。任务进度会保留。",
        flush=True,
    )
    if open_browser:
        timer = threading.Timer(1.5, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()
    from app.server import run

    try:
        run(args.port)
    except KeyboardInterrupt:
        pass
    except (RuntimeError, OSError) as exc:
        raise SystemExit(str(exc)) from None
    return 0


if __name__ == "__main__":
    sys.exit(main())
