"""
共通の小さな関数（日時・数値・文字列）

PHP版と同じ表示・判定になるよう、PHP の関数（number_format, mb_convert_kana など）と
同じ動きをするものをここにまとめている。
"""
import datetime
import json
import re
import unicodedata
from urllib.parse import quote
from urllib.parse import urlencode as _urlencode_pairs

# 日本時間（夏時間が無いため固定の +9 時間でよい）
JST = datetime.timezone(datetime.timedelta(hours=9))


# ---------------------------------------------------------------------------
# 日時
# ---------------------------------------------------------------------------

def now():
    """現在の日本時間（タイムゾーン情報なし）"""
    return datetime.datetime.now(JST).replace(tzinfo=None, microsecond=0)


def today_str():
    return now().strftime('%Y-%m-%d')


def now_str():
    return now().strftime('%Y-%m-%d %H:%M:%S')


def parse_date(value):
    """'YYYY-MM-DD' 形式の実在する日付なら date、それ以外は None"""
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        return None
    try:
        return datetime.datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def parse_datetime(value):
    """'YYYY-MM-DD HH:MM[:SS]'（区切りは空白または T）を datetime に。解釈できなければ None"""
    if not isinstance(value, str):
        return None
    value = trim(value).replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def add_months(d, months):
    """PHP の strtotime('-N months') と同じ（日付があふれた分は翌月へ繰り越す）"""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    first = datetime.date(y, m, 1)
    return first + datetime.timedelta(days=d.day - 1)


def fiscal_year(date_value):
    """会計年度（4月始まり）。例: 2024-03-31 → 2023, 2024-04-01 → 2024"""
    if isinstance(date_value, str):
        date_value = parse_date(date_value) or now().date()
    return date_value.year if date_value.month >= 4 else date_value.year - 1


WEEKDAYS = ['月', '火', '水', '木', '金', '土', '日']


def jp_datetime(value, with_time=True):
    """'2026年10月23日(金) 14:05' の形式（解釈できない値はそのまま返す）"""
    dt = parse_datetime(str(value)) if value is not None else None
    if dt is None:
        return '' if value is None else str(value)
    s = '%d年%d月%d日(%s)' % (dt.year, dt.month, dt.day, WEEKDAYS[dt.weekday()])
    return s + ' ' + dt.strftime('%H:%M') if with_time else s


# ---------------------------------------------------------------------------
# 数値
# ---------------------------------------------------------------------------

INT64_MAX = 9223372036854775807


# PHP が数値の前後に許す空白（半角のみ。全角スペースなどは含まない）
_PHP_NUM_SPACE = ' \t\n\r\x0b\x0c'
# 文字列の先頭の数値部分（PHP と同じく半角数字だけ。小数・指数表記を含む）
_PHP_NUM_PREFIX = re.compile(r'[ \t\n\r\x0b\x0c]*([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)')
INT64_MIN = -INT64_MAX - 1


def _clamp_int64(n):
    return max(INT64_MIN, min(INT64_MAX, n))


def _float_to_int(f):
    """PHP の (int)浮動小数点数 と同じ（範囲外は 64 ビットで折り返す。無限大・NaN は 0）"""
    if f != f or f in (float('inf'), float('-inf')):
        return 0
    n = int(f)
    if INT64_MIN <= n <= INT64_MAX:
        return n
    n %= 1 << 64
    return n - (1 << 64) if n > INT64_MAX else n


def to_int(value, default=0):
    """PHP の (int) キャストと同じ結果にする（解釈できない値は 0）
    - 文字列は先頭の数値部分だけを使う（"12abc" → 12、"1e3" → 1000、"１２"（全角）→ 0）
    - 配列は空なら 0、そうでなければ 1"""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _float_to_int(value)
    if isinstance(value, (list, tuple, dict)):
        return 1 if value else 0
    m = _PHP_NUM_PREFIX.match(str(value))
    if not m:
        return 0
    num = m.group(1)
    if re.fullmatch(r'[+-]?[0-9]+', num):
        return _clamp_int64(int(num))
    f = float(num)
    if f in (float('inf'), float('-inf')):
        return 0
    return _clamp_int64(int(f))


def is_digits(value):
    """PHP の ctype_digit と同じ（文字列で、1文字以上の半角数字のみ）"""
    return isinstance(value, str) and re.fullmatch(r'[0-9]+', value) is not None


_NUMERIC_RE = re.compile(r'[ \t\n\r\v\f]*[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?[ \t\n\r\v\f]*')


def is_numeric(value):
    """PHP 8 の is_numeric と同じ判定（前後の空白・指数表記を許す）"""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return isinstance(value, str) and _NUMERIC_RE.fullmatch(value) is not None


def number_format(value, decimals=0):
    """PHP の number_format（3桁区切り。小数は四捨五入）"""
    if value is None or value == '':
        value = 0
    if isinstance(value, str):
        value = float(value) if is_numeric(value) else 0
    if decimals == 0:
        n = int(abs(value) + 0.5) if isinstance(value, float) else abs(int(value))
        s = '{:,}'.format(n)
        return '-' + s if value < 0 and n != 0 else s
    return '{:,.{}f}'.format(value, decimals)


def yen(value):
    """'¥12,345'（マイナスは '-¥12,345'）"""
    v = to_int(value)
    return ('-¥' if v < 0 else '¥') + number_format(abs(v))


def php_float_str(value):
    """PHP が浮動小数点数を echo したときと同じ表記（41.25 → '41.25', 45.0 → '45'）"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return repr(value) if isinstance(value, float) else str(value)


# ---------------------------------------------------------------------------
# 文字列
# ---------------------------------------------------------------------------

def is_empty(value):
    """PHP の empty() と同じ判定（None, '', '0', 0, 空の配列 などは空）"""
    if value is None or value is False:
        return True
    if isinstance(value, str):
        return value == '' or value == '0'
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


_CTRL_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')


def strip_controls(value):
    """NUL と改行・タブ以外の制御文字を取り除く"""
    return _CTRL_RE.sub('', value)


def mb_convert_kana_a(s):
    """PHP の mb_convert_kana($s, 'a')：全角英数字・記号を半角に（＂＇＼～は対象外、−は - に）"""
    out = []
    for ch in s:
        c = ord(ch)
        if 0xFF01 <= c <= 0xFF5E and c not in (0xFF02, 0xFF07, 0xFF3C, 0xFF5E):
            out.append(chr(c - 0xFEE0))
        elif c == 0x2212:
            out.append('-')
        else:
            out.append(ch)
    return ''.join(out)


def mb_convert_kana_n(s):
    """PHP の mb_convert_kana($s, 'n')：全角数字を半角に"""
    return ''.join(chr(ord(ch) - 0xFEE0) if '\uff10' <= ch <= '\uff19' else ch for ch in s)


def char_width(ch):
    return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1


def mb_strwidth(s):
    return sum(char_width(ch) for ch in s)


def mb_strimwidth(s, width, marker='…'):
    """PHP の mb_strimwidth($s, 0, $width, $marker)"""
    if mb_strwidth(s) <= width:
        return s
    limit = width - mb_strwidth(marker)
    out, w = [], 0
    for ch in s:
        cw = char_width(ch)
        if w + cw > limit:
            break
        out.append(ch)
        w += cw
    return ''.join(out) + marker


def html_escape(value):
    """PHP の htmlspecialchars（ENT_QUOTES）と同じ置き換え"""
    s = value if isinstance(value, str) else str(value)
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace("'", '&#039;'))


def like_escape(value):
    """LIKE 検索の % と _ を文字として扱う"""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def rawurlencode(value):
    return quote(str(value), safe='-_.~')


def http_build_query(params):
    """PHP の http_build_query（値が None の項目は出さない。空白は + 。配列は key[0]=… の形）"""
    items = []

    def add(key, v):
        if v is None:
            return
        if isinstance(v, dict):
            for k2, v2 in v.items():
                add('%s[%s]' % (key, k2), v2)
        elif isinstance(v, (list, tuple)):
            for i, v2 in enumerate(v):
                add('%s[%d]' % (key, i), v2)
        else:
            items.append((key, int(v) if isinstance(v, bool) else v))

    for k, v in params.items():
        add(str(k), v)
    return _urlencode_pairs(items)


def json_dumps(value):
    """JSON（日本語はそのまま）"""
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def json_for_script(value):
    """<script> 内に埋め込める JSON（PHP の json_encode(…, JSON_HEX_TAG|JSON_HEX_AMP|JSON_HEX_APOS|JSON_HEX_QUOT|
    JSON_UNESCAPED_UNICODE) と同じ書式。< > & ' " を \\u 形式に、/ を \\/ にする）"""
    s = json.dumps(php_jsonable(value), ensure_ascii=False, separators=(',', ':'))
    # 文字列の中の \" を \u0022 に（\\ などの他の書き方はそのまま）
    s = re.sub(r'\\(.)', lambda m: '\\u0022' if m.group(1) == '"' else m.group(0), s)
    return (s.replace('/', '\\/').replace('<', '\\u003C').replace('>', '\\u003E').replace('&', '\\u0026')
            .replace("'", '\\u0027').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))


def trim(value):
    """PHP の trim()（取り除くのは半角スペース・タブ・改行・NUL・垂直タブだけ。全角スペースは残す）"""
    return value.strip(' \t\n\r\0\x0b')


def _php_key(k):
    """PHP の配列のキー（"10" のような整数の文字列は整数として扱われる）"""
    if isinstance(k, bool):
        return int(k)
    if isinstance(k, int):
        return k
    if isinstance(k, str) and re.fullmatch(r'0|-?[1-9][0-9]*', k) and INT64_MIN <= int(k) <= INT64_MAX:
        return int(k)
    return k


def php_jsonable(value):
    """PHP の json_encode と同じ形にする（空の辞書・0 からの連番キーの辞書は配列 [] として出力される）"""
    if isinstance(value, dict):
        keys = list(value.keys())
        if [_php_key(k) for k in keys] == list(range(len(keys))):
            return [php_jsonable(value[k]) for k in keys]
        return {str(_php_key(k)) if not isinstance(_php_key(k), str) else k: php_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [php_jsonable(v) for v in value]
    return value


def php_json_encode(value):
    """PHP の json_encode(…, JSON_UNESCAPED_UNICODE) と同じ書式（/ は \\/ にする）"""
    return json.dumps(php_jsonable(value), ensure_ascii=False, separators=(',', ':')).replace('/', '\\/')


def strtotime(value):
    """
    PHP の strtotime のうち、この画面で使う形式だけを解釈する（解釈できなければ None）
      'now' / 'YYYY-MM-DD' / 'YYYY-MM-DD HH:MM[:SS]'（区切りは - または /、日付と時刻の間は空白か T）
    """
    if not isinstance(value, str):
        return None
    s = trim(value)
    if s.lower() == 'now':
        return now()
    m = re.fullmatch(r'([0-9]{4})[-/]([0-9]{1,2})[-/]([0-9]{1,2})(?:[ T]([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?)?', s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh = int(m.group(4) or 0)
    mi = int(m.group(5) or 0)
    ss = int(m.group(6) or 0)
    if not (1 <= mo <= 12 and 1 <= d <= 31 and hh <= 24 and mi <= 59 and ss <= 59):
        return None
    try:
        # PHP と同じく、存在しない日付（2月30日など）・24時は翌日以降へ繰り越す
        base = datetime.datetime(y, mo, 1)
        return base + datetime.timedelta(days=d - 1, hours=hh, minutes=mi, seconds=ss)
    except (ValueError, OverflowError):
        return None


def php_round(x):
    """PHP の round()（0.5 は 0 から遠い方へ）"""
    import math
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)


def php_date(fmt, value=None):
    """PHP の date() のうち、画面で使う書式文字だけ（Y y m n d j t H G i s w）"""
    import calendar
    dt = value if value is not None else now()
    if isinstance(dt, str):
        dt = parse_datetime(dt) or now()
    out = []
    for ch in fmt:
        if ch == 'Y':
            out.append('%04d' % dt.year)
        elif ch == 'y':
            out.append('%02d' % (dt.year % 100))
        elif ch == 'm':
            out.append('%02d' % dt.month)
        elif ch == 'n':
            out.append(str(dt.month))
        elif ch == 'd':
            out.append('%02d' % dt.day)
        elif ch == 'j':
            out.append(str(dt.day))
        elif ch == 't':
            out.append(str(calendar.monthrange(dt.year, dt.month)[1]))
        elif ch == 'H':
            out.append('%02d' % getattr(dt, 'hour', 0))
        elif ch == 'G':
            out.append(str(getattr(dt, 'hour', 0)))
        elif ch == 'i':
            out.append('%02d' % getattr(dt, 'minute', 0))
        elif ch == 's':
            out.append('%02d' % getattr(dt, 'second', 0))
        elif ch == 'w':
            out.append(str((dt.weekday() + 1) % 7))
        else:
            out.append(ch)
    return ''.join(out)


def urlencode(value):
    """PHP の urlencode（空白は +）"""
    from urllib.parse import quote_plus
    return quote_plus(str(value), safe='-_.')


def json_loads(value):
    """JSON を読む（読めない場合は None。PHP の json_decode(…, true) と同じ使い方）"""
    try:
        return json.loads(value) if isinstance(value, str) and value != '' else None
    except ValueError:
        return None
