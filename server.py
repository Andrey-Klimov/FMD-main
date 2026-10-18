"""FMD — HTTP-сервер статического сайта.

Отдаёт содержимое `public/` и подменяет авторизацию ChatGPT/Sites,
которая доступна только на платформе Cloudflare.

Запуск:  python3 -u server.py

Адрес:  всегда 0.0.0.0. Переменная HOST намеренно игнорируется: если
        она равна 127.0.0.1, прокси платформы не достучится до сервера и
        отдаёт 502 с "connection refused".
Порт:   переменная окружения PORT (её задаёт Railway), иначе 5000.
"""
from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import shutil
import socket
import sys
import time
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
INDEX = PUBLIC / "index.html"

# Прокси Railway подключается к контейнеру снаружи, поэтому слушать
# можно только на всех интерфейсах. 127.0.0.1 здесь гарантированный 502.
BIND_HOST = "0.0.0.0"

# Стандартная таблица MIME на разных платформах неполна, а тип ответа
# для .js и .css определяется по-разному в зависимости от версии Python.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/pdf", ".pdf")
mimetypes.add_type("application/zip", ".zip")
mimetypes.add_type("text/css", ".css")

# Хешированные имена в assets/ и logos/ меняются только при новой сборке.
IMMUTABLE = ("/assets/", "/logos/")


def log(message: str) -> None:
    print(f"[fmd] {message}", flush=True)


def resolve_port() -> int:
    raw = os.environ.get("PORT")
    if raw:
        try:
            return int(raw)
        except ValueError:
            log(f"PORT={raw!r} не число, беру 5000")
    return 5000


class Handler(SimpleHTTPRequestHandler):
    """Раздача файлов из `public/` с честными Content-Length и кэшем."""

    protocol_version = "HTTP/1.1"
    server_version = "FMD"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def end_headers(self):
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith(IMMUTABLE):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        elif path in ("/", "/index.html"):
            self.send_header("Cache-Control", "no-cache")
        else:
            self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def send_payload(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:
        self.dispatch()

    def do_HEAD(self) -> None:
        self.dispatch()

    def dispatch(self) -> None:
        path = posixpath.normpath(urllib.parse.unquote(urllib.parse.urlsplit(self.path).path))

        if path == "/health":
            self.send_payload(
                HTTPStatus.OK,
                json.dumps({"status": "ok", "index": INDEX.is_file()}).encode(),
                "application/json",
            )
            return

        if path == "/api/session":
            # Авторизация Sites недоступна вне платформы: посетитель — гость.
            self.send_payload(
                HTTPStatus.OK,
                json.dumps(
                    {
                        "authenticated": False,
                        "user": None,
                        "signInUrl": "/signin-with-chatgpt?return_to=%2F",
                        "signOutUrl": None,
                    }
                ).encode(),
                "application/json",
            )
            return

        if path.startswith(("/signin-with-chatgpt", "/signout")):
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        # Папка public не приехала в контейнер: отвечаем внятной страницей
        # вместо падения, чтобы в браузере было видно настоящую причину.
        if not INDEX.is_file():
            self.send_payload(
                HTTPStatus.SERVICE_UNAVAILABLE,
                f"FMD: не найден {INDEX}".encode(),
                "text/plain; charset=utf-8",
            )
            return

        self.path = "/index.html" if path == "/" else self.path
        source = super().send_head()
        if source is None:
            return
        try:
            if self.command != "HEAD":
                shutil.copyfileobj(source, self.wfile)
        finally:
            source.close()

    def log_message(self, fmt, *args):
        sys.stdout.write(f"[fmd] {self.address_string()} {fmt % args}\n")
        sys.stdout.flush()


def bind(port: int, attempts: int = 5) -> ThreadingHTTPServer:
    """Поднимает сервер, повторяя попытку, если порт ещё занят."""
    for attempt in range(1, attempts + 1):
        try:
            return ThreadingHTTPServer((BIND_HOST, port), Handler)
        except OSError as exc:
            log(f"не удалось занять {BIND_HOST}:{port} ({exc}), попытка {attempt}/{attempts}")
            time.sleep(2)
    raise SystemExit(f"порт {port} занят после {attempts} попыток")


def main() -> None:
    port = resolve_port()

    log(f"python {sys.version.split()[0]}, pid {os.getpid()}")
    log(f"корень: {ROOT}")
    log(f"PORT из окружения: {os.environ.get('PORT')!r} -> слушаем {BIND_HOST}:{port}")
    log(f"HOST из окружения: {os.environ.get('HOST')!r} (игнорируется, нужен {BIND_HOST})")
    log(f"index.html: {'найден' if INDEX.is_file() else 'ОТСУТСТВУЕТ -> сайт отдаст 503'}")

    server = bind(port)
    server.daemon_threads = True

    # Проверяем, что порт действительно виден снаружи контейнера.
    with socket.socket() as probe:
        probe.settimeout(2)
        reachable = probe.connect_ex((BIND_HOST, port)) == 0
    log(f"порт {port} {'принимает внешние подключения' if reachable else 'НЕДОСТУПЕН ИЗВНЕ'}")

    log("готов к работе")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("остановлен")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
