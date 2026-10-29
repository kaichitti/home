"""
CSV の出力（PHP の fputcsv と同じ書式）

Excel で開いたときに数式として実行されないよう、先頭が = + - @ タブ CR のセルは
先頭に ' を付けて無害化する（CSV インジェクション対策）。
"""
import re

_NEEDS_QUOTE = re.compile(r'[,"\\\n\r\t ]')
_FORMULA_START = ('=', '+', '-', '@', '\t', '\r')


def safe(value):
    """数式として評価されないように無害化する"""
    s = '' if value is None else str(value)
    if s != '' and s.startswith(_FORMULA_START):
        return "'" + s
    return s


def _field(value):
    if value is None or value is False:
        s = ''
    elif value is True:
        s = '1'
    else:
        s = str(value)
    if not _NEEDS_QUOTE.search(s):
        return s
    # PHP と同じく " は "" にする（ただし \ の直後の " はそのまま）
    out = ['"']
    escaped = False
    for ch in s:
        if ch == '\\':
            escaped = True
        elif not escaped and ch == '"':
            out.append('"')
        else:
            escaped = False
        out.append(ch)
    out.append('"')
    return ''.join(out)


def row(values):
    """1行分（末尾の改行 \\n まで。PHP の fputcsv と同じ）"""
    return ','.join(_field(v) for v in values) + '\n'
