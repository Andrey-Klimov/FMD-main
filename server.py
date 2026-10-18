"""FMD — HTTP-сервер статического сайта.

Отдаёт содержимое `public/` и подменяет авторизацию ChatGPT/Sites,
которая доступна только на платформе Sites.

Запуск:  python3 server.py
Порт:    переменная окружения PORT (Railway) либо 5000 по умолчанию.
Адрес:   переменная окружения HOST, по умолчанию 0.0.0.0.
"""
from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import shutil
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"

HOST = os.environ.get("HOST") or "0.0.0.0"
PORT = int(os.environ.get("PORT") or "5000")

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
                HTTPStatus.OK, json.dumps({"status": "ok"}).encode(), "application/json"
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
        print(f"{self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    if not (PUBLIC / "index.html").is_file():
        raise SystemExit(f"Не найден {PUBLIC / 'index.html'} — папка public повреждена.")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"FMD слушает http://{HOST}:{PORT} (файлы: {PUBLIC})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
