"""
画面テンプレート（views/*.html）の描画

書き方（Jinja2 に似せた最小限の構文。式は Python の式）:
    {{ 式 }}                     … 値を HTML エスケープして出力（XSS対策。既定で必ずエスケープ）
    {{ raw(式) }}                … エスケープしない（プログラム側で組み立てた安全なHTMLだけに使う）
    {% if 式 %} … {% elif 式 %} … {% else %} … {% endif %}
    {% for 変数 in 式 %} … {% endfor %}
    {% set 変数 = 式 %}
    {% include "pos/_printer" %} … 別のテンプレートを同じ変数で埋め込む
    {% extends "layouts/main" %} … このテンプレートの出力を content としてレイアウトに埋め込む
    {% py %} … {% endpy %}       … 複数行の Python 文（表示用の小さな計算・関数定義だけに使う）
    {# 注釈 #}

タグだけの行は、行ごと出力から取り除く（余計な空行が出ないように）。
テンプレートはプログラムの一部（利用者の入力ではない）として扱う。
"""
import os
import re
import sys
import textwrap

from .. import paths
from ..util import html_escape


class Markup(str):
    """エスケープ済み（または安全）と分かっている HTML 文字列"""
    __slots__ = ()


def escape(value):
    """出力用のエスケープ。None は空、True は '1'、False は空（PHP の echo と同じ）"""
    if isinstance(value, Markup):
        return value
    if value is None or value is False:
        return ''
    if value is True:
        return '1'
    return html_escape(value)


def raw(value):
    return Markup('' if value is None else value)


def g(container, *keys, d=None):
    """入れ子の辞書・リストから値を取り出す（途中で無い・None なら d。PHP の $a['x']['y'] ?? d と同じ）"""
    cur = container
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, (list, tuple)) and isinstance(k, int) and -len(cur) <= k < len(cur):
            cur = cur[k]
        else:
            return d
        if cur is None:
            return d
    return d if cur is None else cur


class TemplateError(Exception):
    pass


_TAG_RE = re.compile(r'\{\{|\{%|\{#')
_NAME_RE = re.compile(r'^[a-z0-9_]+(?:/[a-z0-9_]+)*$', re.I)


class _Compiler:
    def __init__(self, name, source):
        self.name = name
        self.src = source
        self.lines = []      # 生成した Python のコード行
        self.line_map = []   # 生成したコード行 → テンプレートの行番号
        self.indent = 0
        self.stack = []
        self.extends = None

    def lineno(self, pos):
        return self.src.count('\n', 0, pos) + 1

    def emit(self, code, pos):
        self.lines.append('    ' * self.indent + code)
        self.line_map.append(self.lineno(pos))

    def error(self, msg, pos):
        raise TemplateError('%s (%s 行 %d)' % (msg, self.name, self.lineno(pos)))

    def compile(self):
        src = self.src
        pos = 0
        n = len(src)
        while pos < n:
            m = _TAG_RE.search(src, pos)
            if not m:
                self.text(src[pos:], pos)
                break
            start = m.start()
            opener = m.group(0)
            closer = {'{{': '}}', '{%': '%}', '{#': '#}'}[opener]
            end = src.find(closer, start + 2)
            if end < 0:
                self.error('タグが閉じられていません', start)
            inner = src[start + 2:end].strip()
            after = end + 2
            text = src[pos:start]
            if opener != '{{':
                # タグだけの行は、行頭の空白と行末の改行ごと取り除く
                line_start = text.rfind('\n') + 1
                nl = src.find('\n', after)
                rest = src[after:nl if nl >= 0 else n]
                if text[line_start:].strip(' \t') == '' and rest.strip(' \t\r') == '' \
                        and (line_start > 0 or pos == 0 or src[pos - 1] == '\n'):
                    text = text[:line_start]
                    after = nl + 1 if nl >= 0 else n
            self.text(text, pos)
            if opener == '{{':
                if inner == '':
                    self.error('出力する式がありません', start)
                self.emit('__w(__e(%s))' % inner, start)
            elif opener == '{%':
                after = self.statement(inner, start, after)
            pos = after
        if self.stack:
            self.error('{% end' + self.stack[-1] + ' %} がありません', n)
        return self.lines, self.line_map, self.extends

    def text(self, text, pos):
        if text:
            self.emit('__w(%r)' % text, pos)

    def statement(self, inner, pos, after):
        word, _, rest = inner.partition(' ')
        rest = rest.strip()
        if word == 'if':
            self.emit('if %s:' % rest, pos)
            self.open('if', pos)
        elif word == 'elif':
            self.expect('if', pos)
            self.indent -= 1
            self.emit('elif %s:' % rest, pos)
            self.indent += 1
            self.emit('pass', pos)
        elif word == 'else':
            self.expect('if', pos)
            self.indent -= 1
            self.emit('else:', pos)
            self.indent += 1
            self.emit('pass', pos)
        elif word == 'for':
            self.emit('for %s:' % rest, pos)
            self.open('for', pos)
        elif word in ('endif', 'endfor'):
            self.expect(word[3:], pos)
            self.stack.pop()
            self.indent -= 1
        elif word == 'set':
            self.emit(rest, pos)
        elif word == 'include':
            self.emit('__w(__include(%s))' % rest, pos)
        elif word == 'extends':
            self.extends = rest
        elif word == 'py':
            m = re.compile(r'\{%\s*endpy\s*%\}').search(self.src, after)
            if not m:
                self.error('{% endpy %} がありません', pos)
            code = textwrap.dedent(self.src[after:m.start()].strip('\n'))
            base_line = self.lineno(after)
            for i, line in enumerate(code.split('\n')):
                if line.strip():
                    self.lines.append('    ' * self.indent + line)
                    self.line_map.append(base_line + i)
            after = m.end()
            if self.src.startswith('\n', after):
                after += 1
        else:
            self.error('不明なタグ: ' + word, pos)
        return after

    def open(self, kind, pos):
        self.stack.append(kind)
        self.indent += 1
        self.emit('pass', pos)

    def expect(self, kind, pos):
        if not self.stack or self.stack[-1] != kind:
            self.error('対応する {% ' + kind + ' %} がありません', pos)


class _Compiled:
    __slots__ = ('code', 'line_map', 'extends', 'name')

    def __init__(self, name, code, line_map, extends):
        self.name = name
        self.code = code
        self.line_map = line_map
        self.extends = extends


_CACHE = {}


def load(name):
    """テンプレートを読み込んでコンパイルする（同じプロセス内ではキャッシュ）"""
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise TemplateError('テンプレート名が不正です: %r' % (name,))
    cached = _CACHE.get(name)
    if cached is not None:
        return cached
    path = os.path.join(paths.VIEWS_DIR, name + '.html')
    with open(path, 'r', encoding='utf-8') as f:
        source = f.read()
    lines, line_map, extends = _Compiler(name, source).compile()
    filename = '<template %s>' % name
    try:
        code = compile('\n'.join(lines) + '\n', filename, 'exec')
    except SyntaxError as e:
        tl = line_map[e.lineno - 1] if e.lineno and e.lineno <= len(line_map) else '?'
        raise TemplateError('テンプレートの構文エラー: %s (%s 行 %s)' % (e.msg, name, tl)) from None
    compiled = _Compiled(name, code, line_map, extends)
    _CACHE[name] = compiled
    return compiled


def _template_line(tb_frame_name, lineno):
    for c in _CACHE.values():
        if '<template %s>' % c.name == tb_frame_name and 0 < lineno <= len(c.line_map):
            return c.name, c.line_map[lineno - 1]
    return None


def describe_error(exc):
    """例外の起きたテンプレートの位置（デバッグ表示用）"""
    tb = exc.__traceback__
    where = None
    while tb is not None:
        fn = tb.tb_frame.f_code.co_filename
        if fn.startswith('<template '):
            where = _template_line(fn, tb.tb_lineno)
        tb = tb.tb_next
    return '%s 行 %s' % where if where else ''


class Renderer:
    """テンプレートを描画する。ns（変数の辞書）はテンプレート・部品・レイアウトで共有する"""

    def __init__(self, helpers=None):
        self.helpers = helpers or {}

    def render(self, name, data=None):
        ns = {}
        ns.update(self.helpers)
        ns.update(data or {})
        ns['__e'] = escape
        ns['__include'] = lambda n: self._render_into(ns, n)

        def var(var_name, default=None):
            """変数の値（未定義・None なら default。PHP の $x ?? default と同じ）"""
            v = ns.get(var_name)
            return default if v is None else v

        ns['var'] = var
        ns['defined'] = lambda var_name: var_name in ns
        return self._render_into(ns, name)

    def _render_into(self, ns, name):
        tpl = load(name)
        buf = []
        saved = ns.get('__w')
        ns['__w'] = buf.append
        try:
            exec(tpl.code, ns)
        finally:
            ns['__w'] = saved
        out = Markup(''.join(buf))
        if tpl.extends:
            layout = eval(tpl.extends, ns)
            ns['content'] = out
            return self._render_into(ns, layout)
        return out


# Python 3.6 では exec の名前空間に組み込み関数が自動で入る（__builtins__）
assert sys.version_info >= (3, 6)
