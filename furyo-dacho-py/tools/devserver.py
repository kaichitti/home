#!/usr/bin/env python3
"""
手元のパソコンで動作確認するための簡易サーバー（本番の XREA では使わない）

  python3 tools/devserver.py [ポート番号（既定 8090）]

  http://127.0.0.1:8090/index.cgi        … テナント（事業者）側
  http://127.0.0.1:8090/admin/index.cgi  … システム管理者側
  http://127.0.0.1:8090/setup.cgi        … 初回セットアップ（migrate.cgi・check.cgi も同様）
"""
import os
import sys
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.wsgi import admin_app, tenant_app  # noqa: E402
from app.maintenance import check, migrate, setup  # noqa: E402

MAINTENANCE = {'/setup.cgi': setup.application, '/migrate.cgi': migrate.application, '/check.cgi': check.application}


def router(environ, start_response):
    path = environ.get('PATH_INFO', '/')
    if path in ('/admin', '/admin/', '/admin/index.cgi'):
        environ['SCRIPT_NAME'] = '/admin/index.cgi'
        environ['PATH_INFO'] = ''
        return admin_app(environ, start_response)
    if path in ('/', '/index.cgi'):
        environ['SCRIPT_NAME'] = '/index.cgi'
        environ['PATH_INFO'] = ''
        return tenant_app(environ, start_response)
    if path in MAINTENANCE:
        environ['SCRIPT_NAME'] = path
        environ['PATH_INFO'] = ''
        return MAINTENANCE[path](environ, start_response)
    start_response('404 Not Found', [('Content-Type', 'text/plain; charset=UTF-8')])
    return [b'Not Found']


class ThreadingServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write('%s %s\n' % (self.address_string(), fmt % args))


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    httpd = make_server('127.0.0.1', port, router, server_class=ThreadingServer, handler_class=QuietHandler)
    print('http://127.0.0.1:%d/index.cgi' % port)
    httpd.serve_forever()
