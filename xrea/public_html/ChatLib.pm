package ChatLib;

# ぷらチャット - データ層 / 共通処理 (XREA向け Perl CGI版)
#
# Perlのコアモジュールのみを使用する。
# ※CGI.pm は Perl 5.22 でコアから外れたため使用しない。
#   フォーム解析は自前で行う。

use strict;
use warnings;
use utf8;

use Fcntl qw(:flock O_RDWR O_CREAT);
use JSON::PP ();
use Encode ();
use Digest::SHA qw(sha256_hex);
use File::Path qw(make_path);
use Socket ();

use Exporter 'import';
our @EXPORT_OK = qw(
  cfg esc now
  read_form cookies client_ip
  session_load session_save session_touch csrf_ok
  room_load room_save room_list room_new room_delete room_ids
  pm_load pm_save pm_key pm_list_for
  hash_pass verify_pass
  rate_ok
  gc_run
  info_lines contact_append
);

# ---- 設定 ---------------------------------------------------------------
#
# データ保存先はWebから見えない場所を指定すること。
# XREAでは public_html の外(例: /virtual/<ユーザ名>/purachat-data)を推奨。
# 環境変数 PURACHAT_DATA が設定されていればそちらを優先する。

my %CFG = (
  site_name        => 'ぷらチャット',

  # データディレクトリ(絶対パス推奨)。既定はCGIの1つ上の階層。
  data_dir         => $ENV{PURACHAT_DATA} || '',

  # HTTPSで運用する場合は1にする(CookieにSecure属性が付く)
  https_only       => ($ENV{PURACHAT_HTTPS} // 1),

  max_name         => 20,
  max_message      => 500,
  max_room_name    => 30,
  max_room_desc    => 200,
  max_pass         => 30,
  max_log_per_room => 100,
  max_log_per_pm   => 100,
  max_rooms        => 200,
  max_joined_rooms => 5,
  min_capacity     => 2,
  max_capacity     => 50,

  # 放置で自動退室するまでの秒数
  idle_timeout     => 10 * 60,
  # 退室後にセッションを保持する秒数
  session_ttl      => 60 * 60,
  # 個人チャットを保持する秒数
  pm_ttl           => 24 * 60 * 60,

  # 連投制限: post_window 秒間に post_limit 回まで
  post_window      => 10,
  post_limit       => 5,
  # 部屋作成・問い合わせ制限
  create_window    => 300,
  create_limit     => 3,
  # 管理パスワードの試行制限(総当たり対策・発言とは別枠)
  auth_window      => 60,
  auth_limit       => 5,

  # 自動更新の最短間隔(秒)。共用サーバーの負荷対策で下限を設ける。
  min_auto         => 5,
  default_auto     => 10,

  # POSTの最大サイズ(バイト)
  max_post_bytes   => 16 * 1024,

  # 逆引きのタイムアウト(秒)。0で逆引きしない。
  rdns_timeout     => 2,

  # リクエスト時に確率的にGCを走らせる分母(cronがあれば0でよい)
  gc_probability   => 100,
);

sub cfg { return $CFG{ $_[0] }; }

my $JSON = JSON::PP->new->utf8->canonical;

sub now { return time; }

# ---- パス解決 -----------------------------------------------------------

my $DATA;

sub data_dir {
  return $DATA if defined $DATA;
  my $d = $CFG{data_dir};
  if (!$d) {
    # 既定: このモジュールのある階層の1つ上 / purachat-data
    my $base = __FILE__;
    $base =~ s{[^/]+$}{};
    $base = './' if $base eq '';
    $d = $base . '../purachat-data';
  }
  $DATA = $d;
  for my $sub ('', '/rooms', '/sessions', '/pm') {
    my $p = $DATA . $sub;
    make_path($p) unless -d $p;
  }
  # 万一データディレクトリが公開領域に置かれていても読まれないようにする
  # (本来は public_html の外に置くこと。下記は保険。)
  my $guard = $DATA . '/.htaccess';
  unless (-e $guard) {
    if (open(my $fh, '>', $guard)) {
      print $fh "Require all denied\n";
      print $fh "<IfModule !mod_authz_core.c>\n  Order allow,deny\n  Deny from all\n</IfModule>\n";
      close($fh);
    }
  }
  return $DATA;
}

# IDの正当性検査(ディレクトリトラバーサル防止)
sub _safe_id {
  my ($id) = @_;
  return undef unless defined $id;
  return undef unless $id =~ /\A[0-9a-zA-Z_-]{1,64}\z/;
  return $id;
}

# ---- ファイル入出力(ロック付き) -----------------------------------------

sub _read_json {
  my ($path) = @_;
  open(my $fh, '<', $path) or return undef;
  flock($fh, LOCK_SH);
  local $/;
  my $raw = <$fh>;
  close($fh);
  return undef unless defined $raw && length $raw;
  my $data = eval { $JSON->decode($raw) };
  return $data;
}

sub _write_json {
  my ($path, $data) = @_;
  my $tmp = $path . '.tmp' . $$;
  open(my $fh, '>', $tmp) or return 0;
  flock($fh, LOCK_EX);
  print $fh $JSON->encode($data);
  close($fh);
  rename($tmp, $path) or do { unlink $tmp; return 0; };
  return 1;
}

# 読み込み→更新→書き込みを排他的に行う
sub _update_json {
  my ($path, $code) = @_;
  my $lock = $path . '.lock';
  open(my $lf, '>>', $lock) or return undef;
  flock($lf, LOCK_EX);
  my $data = _read_json($path);
  my $result = $code->($data);
  _write_json($path, $result) if defined $result;
  close($lf);
  return $result;
}

# ---- HTMLエスケープ -----------------------------------------------------

sub esc {
  my ($s) = @_;
  return '' unless defined $s;
  $s =~ s/&/&amp;/g;
  $s =~ s/</&lt;/g;
  $s =~ s/>/&gt;/g;
  $s =~ s/"/&quot;/g;
  $s =~ s/'/&#39;/g;
  return $s;
}

# 制御文字を除去して文字数で切り詰める
sub clean_text {
  my ($s, $max) = @_;
  return '' unless defined $s;
  $s =~ s/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]//g;
  $s =~ s/\A\s+//;
  $s =~ s/\s+\z//;
  $s = substr($s, 0, $max) if defined $max && length($s) > $max;
  return $s;
}

# ---- フォーム/クッキー --------------------------------------------------

sub _urldecode {
  my ($s) = @_;
  return '' unless defined $s;
  $s =~ tr/+/ /;
  $s =~ s/%([0-9A-Fa-f]{2})/chr(hex($1))/ge;
  return Encode::decode('UTF-8', $s, Encode::FB_DEFAULT());
}

# GET/POST両方を読み、ハッシュリファレンスで返す
sub read_form {
  my %form;
  my $qs = $ENV{QUERY_STRING} || '';
  my $method = $ENV{REQUEST_METHOD} || 'GET';

  if ($method eq 'POST') {
    my $len = $ENV{CONTENT_LENGTH} || 0;
    $len = $CFG{max_post_bytes} if $len > $CFG{max_post_bytes};
    my $body = '';
    read(STDIN, $body, $len) if $len > 0;
    $qs = length($qs) ? ($qs . '&' . $body) : $body;
  }

  for my $pair (split(/[&;]/, $qs)) {
    next unless length $pair;
    my ($k, $v) = split(/=/, $pair, 2);
    next unless defined $k;
    $k = _urldecode($k);
    $v = defined $v ? _urldecode($v) : '';
    # 同名パラメータは最初のものを採用(パラメータ汚染対策)
    $form{$k} = $v unless exists $form{$k};
  }
  return \%form;
}

sub cookies {
  my %c;
  my $raw = $ENV{HTTP_COOKIE} || '';
  for my $pair (split(/;\s*/, $raw)) {
    my ($k, $v) = split(/=/, $pair, 2);
    next unless defined $k && defined $v;
    $k =~ s/\A\s+//; $k =~ s/\s+\z//;
    $c{$k} = _urldecode($v);
  }
  return \%c;
}

# 接続元IP。
# X-Forwarded-For は詐称できるため信用せず、REMOTE_ADDR のみを使う。
sub client_ip {
  my $ip = $ENV{REMOTE_ADDR} || '';
  $ip = '' unless $ip =~ /\A[0-9a-fA-F:.]{3,45}\z/;
  return $ip;
}

# 逆引き(タイムアウト付き)。失敗時は空文字。
sub reverse_host {
  my ($ip) = @_;
  return '' unless $ip && $CFG{rdns_timeout} > 0;
  return '' unless $ip =~ /\A\d+\.\d+\.\d+\.\d+\z/;
  my $host = '';
  eval {
    local $SIG{ALRM} = sub { die "timeout\n" };
    alarm($CFG{rdns_timeout});
    my $packed = Socket::inet_aton($ip);
    $host = $packed ? (gethostbyaddr($packed, Socket::AF_INET()) || '') : '';
    alarm(0);
    1;
  } or do { alarm(0); $host = ''; };
  $host = '' if $host =~ /[^\w.\-]/;
  return $host;
}

# ---- パスワード ---------------------------------------------------------

sub _salt { return unpack('H*', join('', map { chr(int(rand(256))) } 1 .. 8)); }

# ソルト付きSHA-256。平文は保存しない。
sub hash_pass {
  my ($plain) = @_;
  my $salt = _salt();
  return { salt => $salt, hash => sha256_hex($salt . Encode::encode('UTF-8', $plain)) };
}

sub verify_pass {
  my ($plain, $rec) = @_;
  return 0 unless $rec && $rec->{salt} && $rec->{hash};
  return 0 unless defined $plain && length $plain;
  my $calc = sha256_hex($rec->{salt} . Encode::encode('UTF-8', $plain));
  # タイミング差を避けるため全桁を比較する
  return 0 unless length($calc) == length($rec->{hash});
  my $diff = 0;
  $diff |= ord(substr($calc, $_, 1)) ^ ord(substr($rec->{hash}, $_, 1))
    for 0 .. length($calc) - 1;
  return $diff == 0 ? 1 : 0;
}

sub random_token {
  my ($bytes) = @_;
  $bytes ||= 16;
  return unpack('H*', join('', map { chr(int(rand(256))) } 1 .. $bytes));
}

# ---- セッション ---------------------------------------------------------

sub _session_path { my ($sid) = @_; return data_dir() . '/sessions/' . $sid . '.json'; }

sub session_load {
  my ($sid) = @_;
  $sid = _safe_id($sid) or return undef;
  my $s = _read_json(_session_path($sid));
  return undef unless $s && $s->{sid} && $s->{sid} eq $sid;
  return $s;
}

sub session_new {
  my $sid = random_token(16);
  my $s = {
    sid    => $sid,
    pid    => random_token(4),        # 公開ID(他ユーザーに見える識別子)
    name   => 'ゲスト' . (1 + int(rand(9999))),
    color  => 'black',
    rooms  => {},                      # roomId => 入室時刻
    blocks => {},                      # 無視している相手のpid => 1
    admin  => {},                      # roomId => 管理トークン
    ua     => '',
    ip     => '',
    host   => '',
    auto   => $CFG{default_auto},
    csrf   => random_token(16),
    posts  => [],
    creates=> [],
    auth   => [],
    last   => now(),
  };
  session_save($s);
  return $s;
}

sub session_save {
  my ($s) = @_;
  return 0 unless $s && _safe_id($s->{sid});
  return _write_json(_session_path($s->{sid}), $s);
}

sub session_touch {
  my ($s) = @_;
  $s->{last} = now();
  return session_save($s);
}

sub session_delete {
  my ($sid) = @_;
  $sid = _safe_id($sid) or return;
  unlink(_session_path($sid));
}

# CSRFトークン照合
sub csrf_ok {
  my ($s, $form) = @_;
  return 0 unless $s && $s->{csrf};
  my $given = $form->{csrf} || '';
  return 0 unless length($given) == length($s->{csrf});
  return $given eq $s->{csrf} ? 1 : 0;
}

# ---- レート制限 ---------------------------------------------------------

# $kind: 'posts'(発言・個人チャット) / 'creates'(部屋作成・問い合わせ) / 'auth'(管理ログイン)
sub rate_ok {
  my ($s, $kind) = @_;
  my ($window, $limit) =
      $kind eq 'creates' ? ($CFG{create_window}, $CFG{create_limit})
    : $kind eq 'auth'    ? ($CFG{auth_window},   $CFG{auth_limit})
    :                      ($CFG{post_window},   $CFG{post_limit});
  my $t = now();
  my @recent = grep { $_ > $t - $window } @{ $s->{$kind} || [] };
  if (scalar(@recent) >= $limit) {
    $s->{$kind} = \@recent;
    return 0;
  }
  push @recent, $t;
  $s->{$kind} = \@recent;
  return 1;
}

# ---- 部屋 ---------------------------------------------------------------

sub _room_path { my ($id) = @_; return data_dir() . '/rooms/' . $id . '.json'; }

sub room_ids {
  my $dir = data_dir() . '/rooms';
  opendir(my $dh, $dir) or return ();
  my @ids = sort { $a <=> $b }
            map  { /\A(\d+)\.json\z/ ? $1 : () }
            readdir($dh);
  closedir($dh);
  return @ids;
}

sub room_load {
  my ($id) = @_;
  return undef unless defined $id && $id =~ /\A\d{1,9}\z/;
  return _read_json(_room_path($id));
}

sub room_save {
  my ($room) = @_;
  return 0 unless $room && $room->{id} =~ /\A\d{1,9}\z/;
  return _write_json(_room_path($room->{id}), $room);
}

sub room_update {
  my ($id, $code) = @_;
  return undef unless defined $id && $id =~ /\A\d{1,9}\z/;
  return _update_json(_room_path($id), $code);
}

# 連番の部屋番号を発行する
sub _next_room_id {
  my $path = data_dir() . '/counter.json';
  my $id;
  _update_json($path, sub {
    my ($cur) = @_;
    my $n = ($cur && $cur->{next}) ? $cur->{next} : 1;
    $id = $n;
    return { next => $n + 1 };
  });
  return $id;
}

sub room_new {
  my (%opt) = @_;
  my $id = _next_room_id();
  my $room = {
    id       => $id,
    name     => $opt{name},
    desc     => $opt{desc} || '',
    official => $opt{official} ? 1 : 0,
    admin    => $opt{admin_pass} ? hash_pass($opt{admin_pass}) : undef,
    join     => $opt{join_pass}  ? hash_pass($opt{join_pass})  : undef,
    capacity => $opt{capacity} || $CFG{max_capacity},
    images   => $opt{images} ? 1 : 0,
    ban_ips  => {},
    ban_pids => {},
    created  => now(),
    members  => {},   # sid => { pid, name, color, joined, last }
    log      => [],
  };
  room_save($room);
  return $room;
}

sub room_delete {
  my ($id) = @_;
  return unless defined $id && $id =~ /\A\d{1,9}\z/;
  unlink(_room_path($id));
  unlink(_room_path($id) . '.lock');
}

# 放置メンバーを除いた有効な入室者を返す
sub active_members {
  my ($room) = @_;
  my $limit = now() - $CFG{idle_timeout};
  my %live;
  for my $sid (keys %{ $room->{members} || {} }) {
    my $m = $room->{members}{$sid};
    next unless $m && ($m->{last} || 0) > $limit;
    $live{$sid} = $m;
  }
  return \%live;
}

sub room_log_push {
  my ($room, $entry) = @_;
  $entry->{t} = now();
  push @{ $room->{log} }, $entry;
  my $max = $CFG{max_log_per_room};
  if (scalar(@{ $room->{log} }) > $max) {
    splice(@{ $room->{log} }, 0, scalar(@{ $room->{log} }) - $max);
  }
  return $entry;
}

# ---- 個人チャット -------------------------------------------------------

sub pm_key {
  my ($a, $b) = @_;
  return ($a lt $b) ? "$a-$b" : "$b-$a";
}

sub _pm_path {
  my ($key) = @_;
  return undef unless $key =~ /\A[0-9a-f]{8}-[0-9a-f]{8}\z/;
  return data_dir() . '/pm/' . $key . '.json';
}

sub pm_load {
  my ($a, $b) = @_;
  my $path = _pm_path(pm_key($a, $b)) or return undef;
  return _read_json($path);
}

sub pm_save {
  my ($thread) = @_;
  my $path = _pm_path(pm_key(@{ $thread->{pids} })) or return 0;
  return _write_json($path, $thread);
}

# 自分が関係する個人チャットを新しい順に返す
sub pm_list_for {
  my ($pid) = @_;
  my $dir = data_dir() . '/pm';
  opendir(my $dh, $dir) or return ();
  my @files = grep { /\A[0-9a-f]{8}-[0-9a-f]{8}\.json\z/ && /\Q$pid\E/ } readdir($dh);
  closedir($dh);
  my @threads;
  for my $f (@files) {
    my $t = _read_json("$dir/$f") or next;
    next unless grep { $_ eq $pid } @{ $t->{pids} || [] };
    push @threads, $t;
  }
  @threads = sort {
    my $at = @{ $a->{log} } ? $a->{log}[-1]{t} : 0;
    my $bt = @{ $b->{log} } ? $b->{log}[-1]{t} : 0;
    $bt <=> $at;
  } @threads;
  return @threads;
}

# 自分が入室中の部屋から、指定pidの相手を探す。
# 個人チャットは同室者限定なので、全セッションを走査せずに済む。
# 返り値: { sid, pid, name, color } または undef
sub find_member_by_pid {
  my ($me, $pid) = @_;
  return undef unless $me && $pid && $pid =~ /\A[0-9a-f]{8}\z/;
  for my $rid (keys %{ $me->{rooms} || {} }) {
    my $room = room_load($rid) or next;
    my $live = active_members($room);
    for my $sid (keys %$live) {
      next unless ($live->{$sid}{pid} || '') eq $pid;
      return { sid => $sid, %{ $live->{$sid} } };
    }
  }
  return undef;
}

# 同じ部屋にいるか(個人チャットは同室者限定)
sub shares_room {
  my ($me, $other_pid) = @_;
  return find_member_by_pid($me, $other_pid) ? 1 : 0;
}

# ---- インフォメーション / 連絡 -----------------------------------------

sub info_lines {
  my $path = __FILE__;
  $path =~ s{[^/]+$}{};
  $path .= 'information.txt';
  open(my $fh, '<', $path) or return ();
  my @lines;
  while (my $l = <$fh>) {
    $l = Encode::decode('UTF-8', $l, Encode::FB_DEFAULT());
    $l =~ s/\s+\z//;
    push @lines, $l if length $l;
  }
  close($fh);
  return @lines;
}

sub contact_append {
  my ($rec) = @_;
  my $path = data_dir() . '/contact.log';
  open(my $fh, '>>', $path) or return 0;
  flock($fh, LOCK_EX);
  my @t = localtime(now());
  my $stamp = sprintf('%04d-%02d-%02d %02d:%02d:%02d',
    $t[5] + 1900, $t[4] + 1, $t[3], $t[2], $t[1], $t[0]);
  my $line = join("\t", $stamp,
    'ip=' . ($rec->{ip} || ''),
    'name=' . ($rec->{name} || ''),
    'addr=' . ($rec->{addr} || ''),
    'body=' . ($rec->{body} || '')) . "\n";
  print $fh Encode::encode('UTF-8', $line);
  close($fh);
  return 1;
}

# ---- 掃除(GC) -----------------------------------------------------------
#
# cron(XREA Plus)から gc.pl 経由で定期実行する。
# cronが無い環境でも、リクエスト時に確率的に呼ばれる。

sub gc_run {
  my $t = now();
  my $dir = data_dir();

  # 期限切れセッションの削除
  if (opendir(my $dh, "$dir/sessions")) {
    for my $f (grep { /\A[0-9a-f]{32}\.json\z/ } readdir($dh)) {
      my $s = _read_json("$dir/sessions/$f") or next;
      my $idle = $t - ($s->{last} || 0);
      next if $idle < $CFG{session_ttl};
      unlink("$dir/sessions/$f");
    }
    closedir($dh);
  }

  # 放置メンバーの退室処理と、無人の非公式部屋の削除
  for my $id (room_ids()) {
    room_update($id, sub {
      my ($room) = @_;
      return undef unless $room;
      my $limit = $t - $CFG{idle_timeout};
      my $changed = 0;
      for my $sid (keys %{ $room->{members} || {} }) {
        my $m = $room->{members}{$sid} || {};
        next if ($m->{last} || 0) > $limit;
        delete $room->{members}{$sid};
        room_log_push($room, {
          k => 'sys',
          x => ($m->{name} || '誰か') . ' さんが退室しました（一定時間操作がなかったため）',
        });
        $changed = 1;
      }
      return $changed ? $room : undef;
    });

    my $room = room_load($id) or next;
    next if $room->{official};
    next if scalar(keys %{ $room->{members} || {} }) > 0;
    # 無人かつ最終発言から一定時間経過した部屋を削除
    my $last = @{ $room->{log} } ? $room->{log}[-1]{t} : $room->{created};
    room_delete($id) if $t - $last > $CFG{idle_timeout};
  }

  # 古い個人チャットの削除
  if (opendir(my $dh, "$dir/pm")) {
    for my $f (grep { /\A[0-9a-f]{8}-[0-9a-f]{8}\.json\z/ } readdir($dh)) {
      my $th = _read_json("$dir/pm/$f") or next;
      my $last = @{ $th->{log} || [] } ? $th->{log}[-1]{t} : 0;
      unlink("$dir/pm/$f") if $t - $last > $CFG{pm_ttl};
    }
    closedir($dh);
  }

  return 1;
}

# 起動時に公式部屋が無ければ作る
sub ensure_official_rooms {
  return if scalar(room_ids()) > 0;
  room_new(name => 'ヒマ人の雑談部屋', desc => 'とにかくヒマな人はここへ。話題はなんでもOK！', official => 1);
  room_new(name => '学生の部屋',       desc => '学校のこと、勉強のこと、ゆるく話そう',       official => 1);
  room_new(name => '深夜のまったり部屋', desc => '眠れない夜におしゃべりでもどうぞ',        official => 1);
  room_new(name => 'ゲーム好き集まれ', desc => 'ゲームの話専用。サイコロは「2d6」と発言！', official => 1);
}

1;
