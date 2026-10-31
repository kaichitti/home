"""
利用者のIPアドレス（ログイン試行制限・監査ログに使う）

既定（TRUST_PROXY 未設定）では REMOTE_ADDR だけを使う（偽装できない値）。
自前のリバースプロキシ配下で TRUST_PROXY=true を設定した場合だけ X-Forwarded-For を見る。
その場合も、利用者が自由に書ける左端は使わず、自前のプロキシが追記した右端から順に見る。
TRUSTED_PROXIES（IP・CIDRのカンマ区切り）を設定した場合は、そのプロキシ経由の通信だけ信頼する。
"""
import ipaddress
import re
import sys

from .. import config

_warned = set()


def _clean_env(key):
    """行末の注釈（空白の後の # …）や囲み引用符を取り除いた設定値"""
    v = config.env(key, '') or ''
    v = re.sub(r'(?:^|[\s　]+)#.*$', '', v, flags=re.S)
    v = v.strip(' \t\n\r\0\x0b').strip('　')
    if len(v) >= 2 and v[0] in ('"', "'") and v[-1] == v[0]:
        v = v[1:-1]
    return v.strip()


def _flag(key):
    return _clean_env(key).lower() in ('true', '1')


def _to_ip(value):
    """IPアドレスとして解釈（IPv4射影アドレス ::ffff:a.b.c.d は IPv4 として扱う）"""
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _parse_entry(entry):
    entry = entry.strip()
    if '/' not in entry:
        ip = _to_ip(entry)
        return ipaddress.ip_network(ip) if ip is not None else None
    net, bits = entry.split('/', 1)
    bits = bits.strip()
    if not re.fullmatch(r'[0-9]+', bits):
        return None
    try:
        raw = ipaddress.ip_address(net.strip())
    except ValueError:
        return None
    b = int(bits)
    if b > raw.max_prefixlen:
        return None
    if isinstance(raw, ipaddress.IPv6Address) and raw.ipv4_mapped is not None and b >= 96:
        raw, b = raw.ipv4_mapped, b - 96
    try:
        return ipaddress.ip_network('%s/%d' % (raw, b), strict=False)
    except ValueError:
        return None


def trusted_proxies():
    out = []
    for entry in _clean_env('TRUSTED_PROXIES').split(','):
        entry = entry.strip()
        if entry == '':
            continue
        net = _parse_entry(entry)
        if net is None:
            if entry not in _warned:
                _warned.add(entry)
                sys.stderr.write('[furyo-dacho] TRUSTED_PROXIES の値を解釈できないため無視しました: %s\n' % entry)
            continue
        out.append(net)
    return out


def in_list(ip_str, networks):
    ip = _to_ip(ip_str)
    if ip is None:
        return False
    for net in networks:
        if ip.version == net.version and ip in net:
            return True
    return False


def resolve(environ):
    remote = environ.get('REMOTE_ADDR', '')
    if _to_ip(remote) is None:
        remote = '0.0.0.0'
    if not _flag('TRUST_PROXY'):
        return remote
    trusted = trusted_proxies()
    if not trusted and _clean_env('TRUSTED_PROXIES') != '':
        return remote  # 一覧を設定したのに解釈できない → 転送ヘッダは信頼しない（安全側）
    if trusted and not in_list(remote, trusted):
        return remote
    xff = environ.get('HTTP_X_FORWARDED_FOR', '')
    if xff == '':
        return remote
    chain = [c.strip() for c in xff.split(',')]
    for ip in reversed(chain):
        if _to_ip(ip) is None:
            break
        if trusted and in_list(ip, trusted):
            continue
        return ip
    return remote


def bucket(ip_str):
    """ログイン試行制限の単位（IPv4 はそのまま、IPv6 は /64 ごと）"""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return ip_str
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        net = ipaddress.ip_network('%s/64' % ip, strict=False)
        return '%s/64' % net.network_address
    return str(ip)
