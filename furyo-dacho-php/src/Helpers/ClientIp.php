<?php

namespace FuryoDacho\Helpers;

/**
 * クライアントIPアドレスの解決（Request::ip と Auth の共通実装）
 *
 * 既定（TRUST_PROXY 未設定）では REMOTE_ADDR のみを使う。
 *
 * リバースプロキシ配下で TRUST_PROXY=true を設定した場合のみ X-Forwarded-For を参照する。
 * その際、X-Forwarded-For の「左端」はクライアントが自由に書き込めるため使わず、
 * 自前のプロキシが末尾に追記した「右端」から順に見て、最初の非プロキシIPを採用する。
 * TRUSTED_PROXIES（カンマ区切りのIP/CIDR）を設定した場合は、REMOTE_ADDR が
 * その一覧に含まれるとき（＝自前プロキシ経由の通信）だけ X-Forwarded-For を信頼し、
 * 多段プロキシの場合は一覧に含まれるIPを右から読み飛ばす。
 * 偽装が容易な Client-IP ヘッダは参照しない。
 *
 * IPアドレスはログイン試行制限・信頼済みIP判定のセキュリティ上の入力になるため、
 * 偽装できない値だけを使うことが重要。
 */
class ClientIp
{
    /** @var array<string,bool> 警告済みの TRUSTED_PROXIES の値（同一リクエスト内での重複記録を防ぐ） */
    private static array $warned = [];

    public static function resolve(): string
    {
        $remote = (string)($_SERVER['REMOTE_ADDR'] ?? '');
        if (filter_var($remote, FILTER_VALIDATE_IP) === false) {
            $remote = '0.0.0.0';
        }

        if (!self::envFlag('TRUST_PROXY')) {
            return $remote;
        }

        $trusted = self::trustedProxies();
        if ($trusted === [] && trim(self::rawEnv('TRUSTED_PROXIES')) !== '') {
            // 一覧を設定したのに1件も解釈できない（記入ミス・「# 10.0.0.1」のように値を
            // 注釈にした場合を含む）ときは、未設定扱いで全面的に信頼するのではなく、
            // 転送ヘッダを一切信頼しない（安全側）
            return $remote;
        }
        if ($trusted !== [] && !self::inList($remote, $trusted)) {
            // 自前プロキシを経由していない通信の転送ヘッダは信頼しない
            return $remote;
        }

        $xff = (string)($_SERVER['HTTP_X_FORWARDED_FOR'] ?? '');
        if ($xff === '') {
            return $remote;
        }

        $chain = array_map('trim', explode(',', $xff));
        for ($i = count($chain) - 1; $i >= 0; $i--) {
            $ip = $chain[$i];
            if (filter_var($ip, FILTER_VALIDATE_IP) === false) {
                break; // 不正な値に当たったらそれ以上遡らない
            }
            if ($trusted !== [] && self::inList($ip, $trusted)) {
                continue; // 多段の自前プロキシは読み飛ばす
            }
            return $ip;
        }

        return $remote;
    }

    /**
     * 環境変数の値（.env の行末コメント「 # ...」は取り除く）
     *
     * .env ローダーは行頭の # しか注釈として扱わないため、
     * 「TRUSTED_PROXIES=10.0.0.1  # 自前のプロキシ」のように書くと注釈まで値に含まれ、
     * 設定が黙って効かなくなる。この2項目はIPと真偽値しか取らないので、ここで取り除く。
     */
    private static function envValue(string $key, string $default = ''): string
    {
        $v = self::rawEnv($key, $default);
        // 行末の注釈（半角・全角スペースの後の #）と、値だけの注釈（# から始まる）を取り除く
        $v = preg_replace('/(?:^|[\s\x{3000}]+)#.*$/su', '', $v) ?? $v;
        $v = trim($v, " \t\n\r\0\x0B");
        $v = preg_replace('/^\x{3000}+|\x{3000}+$/u', '', $v) ?? $v;
        // 注釈の除去後に残った囲み引用符（"10.0.0.1" # LB 等）を外す
        $q = $v[0] ?? '';
        if (($q === '"' || $q === "'") && strlen($v) >= 2 && substr($v, -1) === $q) {
            $v = substr($v, 1, -1);
        }
        return trim($v);
    }

    /**
     * 環境変数の値（加工前）
     */
    private static function rawEnv(string $key, string $default = ''): string
    {
        $v = getenv($key);
        if ($v === false || $v === '') {
            $v = $_ENV[$key] ?? ($_SERVER[$key] ?? $default);
        }
        return (string)$v;
    }

    /**
     * 環境変数の真偽値（true / 1 のみ真）
     */
    private static function envFlag(string $key): bool
    {
        $v = strtolower(self::envValue($key, 'false'));
        return $v === 'true' || $v === '1';
    }

    /**
     * @return string[] TRUSTED_PROXIES に列挙されたIP/CIDR（解釈できない値は除外して記録）
     */
    private static function trustedProxies(): array
    {
        $list = [];
        foreach (explode(',', self::envValue('TRUSTED_PROXIES')) as $entry) {
            $entry = trim($entry);
            if ($entry === '') {
                continue;
            }
            if (self::parseEntry($entry) === null) {
                if (!isset(self::$warned[$entry])) { // 同じ値の警告は1リクエストにつき1回だけ
                    self::$warned[$entry] = true;
                    error_log('[furyo-dacho] TRUSTED_PROXIES の値を解釈できないため無視しました: ' . $entry);
                }
                continue;
            }
            $list[] = $entry;
        }
        return $list;
    }

    /**
     * IPアドレスを比較用のバイナリにする（IPv4射影アドレス ::ffff:a.b.c.d は IPv4 として扱う）
     */
    private static function toBinary(string $ip): ?string
    {
        $bin = @inet_pton(trim($ip));
        if ($bin === false) {
            return null;
        }
        if (strlen($bin) === 16 && strncmp($bin, str_repeat("\0", 10) . "\xff\xff", 12) === 0) {
            $bin = substr($bin, 12);
        }
        return $bin;
    }

    /**
     * 一覧の1要素（単一IP または IP/プレフィックス長）を [ネットワーク, ビット数] にする。
     * プレフィックス長が空・数字以外・範囲外の場合は null（全アドレス一致として扱わない）。
     *
     * @return array{0:string,1:int}|null
     */
    private static function parseEntry(string $entry): ?array
    {
        $entry = trim($entry);
        if (strpos($entry, '/') === false) {
            $bin = self::toBinary($entry);
            return $bin === null ? null : [$bin, strlen($bin) * 8];
        }

        [$net, $bits] = explode('/', $entry, 2);
        $bits = trim($bits);
        $raw  = @inet_pton(trim($net));
        if ($raw === false || $bits === '' || !ctype_digit($bits)) {
            return null;
        }
        $bits = (int)$bits;
        if ($bits > strlen($raw) * 8) {
            return null;
        }
        // IPv4射影の範囲指定（::ffff:a.b.c.d/96 以上）は IPv4 の範囲に換算する
        $bin = self::toBinary(trim($net));
        if (strlen($raw) === 16 && strlen((string)$bin) === 4) {
            if ($bits < 96) {
                $bin = $raw; // 射影範囲より広い指定は IPv6 のまま比較する
            } else {
                $bits -= 96;
            }
        }
        return [$bin, $bits];
    }

    /**
     * IPが一覧（単一IPまたはCIDR）のいずれかに含まれるか（IPv4/IPv6対応）
     *
     * @param string[] $list
     */
    public static function inList(string $ip, array $list): bool
    {
        $ipBin = self::toBinary($ip);
        if ($ipBin === null) {
            return false;
        }
        foreach ($list as $entry) {
            $parsed = self::parseEntry((string)$entry);
            if ($parsed === null) {
                continue;
            }
            [$netBin, $bits] = $parsed;
            if (strlen($netBin) !== strlen($ipBin)) {
                continue;
            }
            $bytes = intdiv($bits, 8);
            $rem   = $bits % 8;
            if (substr($ipBin, 0, $bytes) !== substr($netBin, 0, $bytes)) {
                continue;
            }
            if ($rem === 0) {
                return true;
            }
            $mask = chr((0xFF << (8 - $rem)) & 0xFF);
            if ((($ipBin[$bytes] ^ $netBin[$bytes]) & $mask) === "\0") {
                return true;
            }
        }
        return false;
    }
}
