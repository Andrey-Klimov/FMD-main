"""Собрать и опубликовать FMD из папки MSFO analyst через Cloudflare Pages."""
from pathlib import Path
import argparse, functools, http.server, shutil, subprocess, sys
from build_site import build

ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-only',action='store_true',help='Только собрать fmd_public, без публикации')
    parser.add_argument('--serve',action='store_true',help='Собрать и открыть локальный сервер на 127.0.0.1:8000')
    parser.add_argument('--setup',action='store_true',help='Первый запуск: вход в Cloudflare и создание проекта Pages')
    parser.add_argument('--project',default='fmd-financial-multiples',help='Имя проекта в вашем аккаунте Cloudflare')
    args=parser.parse_args()
    output=build(ROOT,ROOT/'fmd_public')
    if args.build_only:return
    if args.serve:
        handler=functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(output))
        print('Локальный просмотр: http://127.0.0.1:8000 (Ctrl+C — выход)')
        with http.server.ThreadingHTTPServer(('127.0.0.1',8000),handler) as server:
            try:server.serve_forever()
            except KeyboardInterrupt:pass
        return
    npx=shutil.which('npx') or shutil.which('npx.cmd')
    if not npx:raise SystemExit('Для публикации установите Node.js LTS (с npm/npx), затем повторите команду. Сайт уже собран в fmd_public.')
    cli=[npx,'--yes','wrangler@4']
    # Arguments are passed as a list; no shell interpolation and no .env is loaded.
    if args.setup:
        subprocess.run(cli+['login'],cwd=ROOT,check=True)
        subprocess.run(cli+['pages','project','create',args.project,'--production-branch','main'],cwd=ROOT,check=True)
    print('Публикация на Cloudflare Pages. Адрес появится после успешной загрузки.')
    subprocess.run(cli+['pages','deploy',str(output),'--project-name',args.project,'--branch','main'],cwd=ROOT,check=True)

if __name__=='__main__':
    try:main()
    except subprocess.CalledProcessError as exc:
        print('Публикация не завершена. Проверьте сообщение Cloudflare выше. Для первого запуска используйте --setup; для существующего проекта укажите --project.',file=sys.stderr)
        sys.exit(exc.returncode)
