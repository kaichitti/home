"""
入力チェック

ルールは「必須|最大文字数|メール形式」のように | で区切って指定する（PHP版と同じ書き方）。
  required, max:N, min:N, email, numeric, integer, date, in:a,b,c, regex:正規表現
"""
import re

from ..util import is_numeric, parse_date

# PHP の filter_var(FILTER_VALIDATE_EMAIL) と同じ正規表現（PHP 本体から取り出したもの）
_EMAIL_RE = re.compile(
    rb'(?!(?:(?:\x22?\x5C[\x00-\x7E]\x22?)|(?:\x22?[^\x5C\x22]\x22?)){255,})'
    rb'(?!(?:(?:\x22?\x5C[\x00-\x7E]\x22?)|(?:\x22?[^\x5C\x22]\x22?)){65,}@)'
    rb'(?:(?:[\x21\x23-\x27\x2A\x2B\x2D\x2F-\x39\x3D\x3F\x5E-\x7E]+)|(?:\x22(?:[\x01-\x08\x0B\x0C\x0E-\x1F\x21\x23-\x5B\x5D-\x7F]|(?:\x5C[\x00-\x7F]))*\x22))'
    rb'(?:\.(?:(?:[\x21\x23-\x27\x2A\x2B\x2D\x2F-\x39\x3D\x3F\x5E-\x7E]+)|(?:\x22(?:[\x01-\x08\x0B\x0C\x0E-\x1F\x21\x23-\x5B\x5D-\x7F]|(?:\x5C[\x00-\x7F]))*\x22)))*'
    rb'@(?:(?:(?!.*[^.]{64,})(?:(?:(?:xn--)?[a-z0-9]+(?:-+[a-z0-9]+)*\.){1,126}){1,}(?:(?:[a-z][a-z0-9]*)|(?:(?:xn--)[a-z0-9]+))(?:-+[a-z0-9]+)*)'
    rb'|(?:\[(?:(?:IPv6:(?:(?:[a-f0-9]{1,4}(?::[a-f0-9]{1,4}){7})|(?:(?!(?:.*[a-f0-9][:\]]){7,})(?:[a-f0-9]{1,4}(?::[a-f0-9]{1,4}){0,5})?::(?:[a-f0-9]{1,4}(?::[a-f0-9]{1,4}){0,5})?)))'
    rb'|(?:(?:IPv6:(?:(?:[a-f0-9]{1,4}(?::[a-f0-9]{1,4}){5}:)|(?:(?!(?:.*[a-f0-9]:){5,})(?:[a-f0-9]{1,4}(?::[a-f0-9]{1,4}){0,3})?::(?:[a-f0-9]{1,4}(?::[a-f0-9]{1,4}){0,3}:)?)))?'
    rb'(?:(?:25[0-5])|(?:2[0-4][0-9])|(?:1[0-9]{2})|(?:[1-9]?[0-9]))(?:\.(?:(?:25[0-5])|(?:2[0-4][0-9])|(?:1[0-9]{2})|(?:[1-9]?[0-9]))){3}))\]))',
    re.IGNORECASE)


def is_email(value):
    """メールアドレスの形式か（PHP版と同じ判定）"""
    if not isinstance(value, str):
        return False
    b = value.encode('utf-8')
    if len(b) > 320:
        return False
    return _EMAIL_RE.fullmatch(b) is not None


def is_valid_date(value):
    return parse_date(value) is not None if isinstance(value, str) else False


class Validator:
    def __init__(self, data, labels=None):
        self.data = data
        self.labels = labels or {}
        self.errors = {}

    def validate(self, rules):
        self.errors = {}
        for field, rule_string in rules.items():
            value = self.data.get(field)
            if isinstance(value, (dict, list)):
                self._add(field, '%s の形式が正しくありません。' % self.labels.get(field, field))
                continue
            for rule in rule_string.split('|'):
                name, _, param = rule.partition(':')
                self._apply(field, value, name, param)
        return not self.errors

    def first_errors(self):
        return {k: v[0] for k, v in self.errors.items()}

    def _add(self, field, message):
        self.errors.setdefault(field, []).append(message)

    def _apply(self, key, value, rule, param):
        label = self.labels.get(key, key)
        has = value is not None and value != ''
        if rule == 'required':
            if not has:
                self._add(key, '%s は必須項目です。' % label)
        elif rule == 'max':
            if value is not None and len(str(value)) > int(param):
                self._add(key, '%s は %s 文字以内で入力してください。' % (label, param))
        elif rule == 'min':
            if value is not None and len(str(value)) < int(param):
                self._add(key, '%s は %s 文字以上で入力してください。' % (label, param))
        elif rule == 'email':
            if has and not is_email(value):
                self._add(key, '%s は正しいメールアドレス形式で入力してください。' % label)
        elif rule == 'numeric':
            if has and not is_numeric(value):
                self._add(key, '%s は数値で入力してください。' % label)
        elif rule == 'integer':
            if has and not re.fullmatch(r'\s*[+-]?(0|[1-9][0-9]*)\s*', str(value)):
                self._add(key, '%s は整数で入力してください。' % label)
        elif rule == 'date':
            if has and not is_valid_date(value):
                self._add(key, '%s は YYYY-MM-DD 形式の日付で入力してください。' % label)
        elif rule == 'in':
            if has and value not in param.split(','):
                self._add(key, '%s の値が無効です。' % label)
        elif rule == 'regex':
            if has and not re.fullmatch(param, value):
                self._add(key, '%s の形式が正しくありません。' % label)
