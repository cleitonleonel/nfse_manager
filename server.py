"""Entry point compatível com os scripts do desktop, sidecar Tauri e execução via Python."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import sys


def _resolve_backend_dir() -> Path:
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    candidate = base_dir / "backend"
    if candidate.exists():
        return candidate
    return Path(__file__).resolve().parent / "backend"


BACKEND_DIR = _resolve_backend_dir()
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _configure_environment(data_dir: str | None = None, disable_scheduler: bool = False) -> None:
    if data_dir:
        os.environ["NFSE_DATA_DIR"] = str(Path(data_dir).expanduser().resolve())
    if disable_scheduler:
        os.environ["NFSE_SCHEDULER_MODE"] = "disabled"
    if getattr(sys, "frozen", False):
        os.environ.setdefault("NFSE_DISABLE_SELF_UPDATE", "1")


def _allocate_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NFSe Manager Pro Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host de escuta (padrão: 0.0.0.0)")
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Porta TCP de escuta (padrão: 8000; use 0 para porta livre automática)",
    )
    parser.add_argument("--data-dir", default=None, help="Diretório raiz de dados (NFSE_DATA_DIR)")
    parser.add_argument(
        "--disable-scheduler",
        action="store_true",
        help="Desabilita o agendador/worker interno neste processo",
    )
    return parser.parse_args(argv)


def __getattr__(name: str):
    if name == "app":
        _configure_environment()
        from app.main import app as fastapi_app

        return fastapi_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    args = _parse_args()
    _configure_environment(data_dir=args.data_dir, disable_scheduler=args.disable_scheduler)

    from app.main import app  # noqa: E402
    import uvicorn  # noqa: E402

    actual_port = args.port if args.port != 0 else _allocate_free_port(args.host)
    print(f"NFSE_SERVER_READY port={actual_port}", flush=True)

    config = uvicorn.Config(app, host=args.host, port=actual_port)
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
