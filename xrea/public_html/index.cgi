#!/usr/bin/perl
#
# ぷらチャット - XREA向け Perl CGI版
#
# ・常駐プロセスを使わないCGI方式(XREAはデーモン禁止・30秒/CPU15%で強制終了)
# ・状態はすべてファイルに保存(flockで排他制御)
# ・コアモジュールのみ使用(CGI.pmはPerl 5.22でコアから外れたため不使用)
#
# Perlのパスがサーバーと異なる場合は1行目を書き換えてください。

use strict;
use warnings;
use utf8;

use FindBin ();
use lib $FindBin::Bin;
use Encode ();
use ChatLib;

binmode(STDOUT, ':raw');

# ---- 定数 ---------------------------------------------------------------

my $SITE = ChatLib::cfg('site_name');

# 名前の色プリセット16色(キー, 表示名, 色コード) 明るめの色調
my @COLORS = (
  ['black',     '黒',     '#555555'],
  ['red',       '赤',     '#ff4444'],
  ['blue',      '青',     '#4466ff'],
  ['green',     '緑',     '#33bb33'],
  ['orange',    '橙',     '#ff9922'],
  ['purple',    '紫',     '#cc55dd'],
  ['brown',     '茶',     '#cc8855'],
  ['pink',      '桃',     '#ff77bb'],
  ['teal',      '青緑',   '#22bbbb'],
  ['gray',      '灰',     '#aaaaaa'],
  ['navy',      '紺',     '#5566ee'],
  ['darkgreen', '深緑',   '#55bb77'],
  ['wine',      'えんじ', '#ee5566'],
  ['gold',      '金茶',   '#eebb33'],
  ['sky',       '空',     '#66ccff'],
  ['fuji',      '藤',     '#aa99ff'],
);
my %COLOR_HEX = map { $_->[0] => $_->[2] } @COLORS;

sub color_hex { my $k = shift || ''; return $COLOR_HEX{$k} || $COLORS[0][2]; }
sub valid_color { my $k = shift || ''; return exists $COLOR_HEX{$k} ? $k : $COLORS[0][0]; }

# ---- 出力 ---------------------------------------------------------------

my @HEADERS;
sub add_header { push @HEADERS, $_[0]; }

sub set_cookie {
  my ($name, $value, $maxage) = @_;
  my $v = $value;
  $v =~ s/([^A-Za-z0-9_.\-])/sprintf('%%%02X', ord($1))/ge;
  my $c = "$name=$v; Path=/; Max-Age=$maxage; HttpOnly; SameSite=Lax";
  $c .= '; Secure' if ChatLib::cfg('https_only');
  add_header("Set-Cookie: $c");
}

sub send_html {
  my ($title, $body, $frameset) = @_;
  my $doctype = $frameset
    ? '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Frameset//EN">'
    : '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">';
  my $html = $frameset ? $body : page_wrap($title, $body);
  print "Content-Type: text/html; charset=UTF-8\r\n";
  print "X-Content-Type-Options: nosniff\r\n";
  print "X-Frame-Options: SAMEORIGIN\r\n";
  print "Cache-Control: no-store\r\n";
  print "$_\r\n" for @HEADERS;
  print "\r\n";
  print Encode::encode('UTF-8', "$doctype\n$html");
  exit;
}

sub redirect {
  my ($url) = @_;
  $url =~ s/&amp;/&/g;             # Locationヘッダは生の & を使う
  $url =~ s/[\r\n].*\z//s;         # ヘッダ分割の防止
  print "Status: 302 Found\r\n";
  print "Location: $url\r\n";
  print "$_\r\n" for @HEADERS;
  print "\r\n";
  exit;
}

# ライトブルー基調の旧式デザイン
my $STYLE = join('',
  'body{background-color:#e2eef8;color:#223344;font-family:"MS PGothic",Osaka,"Hiragino Kaku Gothic ProN",Meiryo,sans-serif;font-size:14px;margin:6px;}',
  'h1{font-size:19px;margin:4px 0;color:#225588;}',
  'h2{font-size:15px;margin:8px 0 4px 0;color:#225588;}',
  'hr{border:0;border-top:1px solid #88aacc;height:1px;}',
  'a{color:#0055aa;}',
  'table{border-collapse:collapse;background-color:#ffffff;}',
  'th,td{border:1px solid #88aacc;padding:3px 6px;font-size:13px;text-align:left;}',
  'th{background-color:#c4dcf0;font-weight:bold;}',
  'input,select,textarea{font-size:14px;}',
  '.box{border:1px solid #88aacc;background-color:#ffffff;padding:6px;margin:6px 0;}',
  '.info{border:1px solid #88aacc;background-color:#f4faff;padding:6px;margin:6px 0;}',
  '.sys{color:#7788aa;font-size:12px;}',
  '.dice{color:#775500;}',
  '.small{font-size:11px;color:#667788;}',
  '.err{color:#cc0000;font-weight:bold;}',
  '.ok{color:#007700;font-weight:bold;}',
  '.ua{word-break:break-all;font-size:12px;}',
  '.tabbar{margin:4px 0;}',
  '.tab{border:1px solid #88aacc;background-color:#c4dcf0;padding:2px 8px;margin-right:2px;text-decoration:none;font-size:13px;}',
  '.tabon{border:1px solid #88aacc;background-color:#ffffff;padding:2px 8px;margin-right:2px;font-weight:bold;font-size:13px;}',
  '.tabnew{border:1px solid #cc6666;background-color:#ffe8e8;padding:2px 8px;margin-right:2px;text-decoration:none;font-size:13px;color:#cc0000;font-weight:bold;}',
  '.chatimg{max-width:240px;max-height:240px;}',
  '.palette{background-color:transparent;margin:4px 0;}',
  '.palette td{border:1px solid #446688;padding:4px 6px;}',
);

sub page_wrap {
  my ($title, $body) = @_;
  return '<html><head>'
    . '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">'
    . '<meta name="viewport" content="width=device-width">'
    . '<title>' . ChatLib::esc("$SITE - $title") . '</title>'
    . '<style type="text/css">' . $STYLE . '</style>'
    . '</head><body bgcolor="#e2eef8">' . $body . '</body></html>';
}

# ---- 入力 ---------------------------------------------------------------

my $FORM    = ChatLib::read_form();
my $COOKIES = ChatLib::cookies();
my $IS_POST = ($ENV{REQUEST_METHOD} || 'GET') eq 'POST';

# 設置場所に依らず正しいリンクを作る(/chat/?room=5 の形になる)
my $SELF = $ENV{SCRIPT_NAME} || '';
$SELF =~ s{index\.cgi\z}{};
$SELF = './' if $SELF eq '';

# HTML中に埋め込む前提でURLを作るため & は &amp; にする。
# リダイレクトのLocationヘッダに使うときは redirect() が元に戻す。
sub url {
  my ($q) = @_;
  my $u = $SELF . (defined $q && length $q ? "?$q" : '');
  $u =~ s/&/&amp;/g;
  return $u;
}

# ---- セッション ---------------------------------------------------------

ChatLib::data_dir();
ChatLib::ensure_official_rooms();

my $SESSION;
sub session {
  return $SESSION if $SESSION;
  my $sid = $COOKIES->{sid} || '';
  $SESSION = ChatLib::session_load($sid);
  if (!$SESSION) {
    $SESSION = ChatLib::session_new();
    # 名前と色はブラウザに残っていれば引き継ぐ
    my $n = ChatLib::clean_text($COOKIES->{name}, ChatLib::cfg('max_name'));
    $SESSION->{name}  = $n if length $n;
    $SESSION->{color} = valid_color($COOKIES->{color}) if $COOKIES->{color};
    ChatLib::session_save($SESSION);
    set_cookie('sid', $SESSION->{sid}, 60 * 60 * 24);
  }
  # アクセス情報が変わったときだけ保存する(毎回書かない)
  my $ua = substr($ENV{HTTP_USER_AGENT} || '(不明)', 0, 400);
  my $ip = ChatLib::client_ip();
  my $dirty = 0;
  if ($ua ne ($SESSION->{ua} || '')) { $SESSION->{ua} = $ua; $dirty = 1; }
  if ($ip && $ip ne ($SESSION->{ip} || '')) {
    $SESSION->{ip}   = $ip;
    $SESSION->{host} = ChatLib::reverse_host($ip);
    $dirty = 1;
  }
  ChatLib::session_save($SESSION) if $dirty;
  return $SESSION;
}

# POSTはCSRFトークンを必須にする
sub require_csrf {
  my ($s) = @_;
  return if ChatLib::csrf_ok($s, $FORM);
  send_html('エラー',
    '<h1>送信できませんでした</h1>'
    . '<div class="err">ページの有効期限が切れているか、正しい手順で送信されていません。</div>'
    . '<div class="small">お手数ですが、TOPページからやり直してください。</div>'
    . '<hr>[<a href="' . url('') . '">TOPへ戻る</a>]');
}

sub csrf_field {
  my ($s) = @_;
  return '<input type="hidden" name="csrf" value="' . ChatLib::esc($s->{csrf}) . '">';
}

# ---- 表示部品 -----------------------------------------------------------

sub jst_hm {
  my ($t) = @_;
  return '--:--' unless $t;
  my @g = gmtime($t + 9 * 3600);
  return sprintf('%02d:%02d', $g[2], $g[1]);
}

sub name_html {
  my ($name, $color) = @_;
  return '<font color="' . color_hex($color) . '"><b>' . ChatLib::esc($name) . '</b></font>';
}

# 色そのものを見て選べるパレット(色付きセル+ラジオボタン)
sub palette_html {
  my ($selected) = @_;
  my $h = '<table cellpadding="0" cellspacing="2" class="palette"><tr>';
  for my $i (0 .. $#COLORS) {
    $h .= '</tr><tr>' if $i == 8;
    my ($key, $label, $hex) = @{ $COLORS[$i] };
    my $checked = ($key eq ($selected || '')) ? ' checked' : '';
    $h .= '<td bgcolor="' . $hex . '" style="background-color:' . $hex . ';" title="' . ChatLib::esc($label) . '">'
       . '<input type="radio" name="color" value="' . $key . '"' . $checked . '></td>';
  }
  return $h . '</tr></table>';
}

sub unread_pm_count {
  my ($s) = @_;
  my $n = 0;
  for my $th (ChatLib::pm_list_for($s->{pid})) {
    $n++ if $th->{unread} && $th->{unread}{ $s->{pid} };
  }
  return $n;
}

# TOP・入室中の部屋(最大5)・個人チャットを行き来するタブ
sub tabs_html {
  my ($s, $current, $top_target) = @_;
  my $tg = $top_target ? ' target="_top"' : '';
  my $h = '<div class="tabbar">';
  $h .= ($current || '') eq 'top'
    ? '<span class="tabon">TOP</span>'
    : '<a class="tab" href="' . url('') . '"' . $tg . '>TOP</a>';

  for my $rid (sort { $a <=> $b } keys %{ $s->{rooms} || {} }) {
    my $room = ChatLib::room_load($rid) or next;
    my $label = $room->{name};
    $label = substr($label, 0, 8) . '…' if length($label) > 8;
    my $count = scalar(keys %{ ChatLib::active_members($room) });
    $label = ChatLib::esc($label) . "($count)";
    $h .= ($current || '') eq "room$rid"
      ? '<span class="tabon">' . $label . '</span>'
      : '<a class="tab" href="' . url("room=$rid") . '"' . $tg . '>' . $label . '</a>';
  }

  my $unread = unread_pm_count($s);
  my $label = '個人チャット' . ($unread > 0 ? "(新着$unread)" : '');
  if (($current || '') eq 'pm') {
    $h .= '<span class="tabon">' . $label . '</span>';
  } else {
    $h .= '<a class="' . ($unread > 0 ? 'tabnew' : 'tab') . '" href="' . url('mode=pmlist') . '"' . $tg . '>' . $label . '</a>';
  }
  return $h . '</div>';
}

# ポップアップが開けないブラウザ(ゲーム機など)では通常のリンクとして遷移する
sub popup_link {
  my ($u, $label, $w, $h) = @_;
  return '<a href="' . $u . '" target="_blank"'
    . ' onclick="try{var w=window.open(this.href,\'pcpopup\',\'width=' . $w . ',height=' . $h
    . ',scrollbars=yes,resizable=yes\');if(w){return false;}}catch(e){}return true;">' . $label . '</a>';
}

my $DICE_RE = qr/\A(\d{1,2})[dD](\d{1,4})([+-]\d{1,4})?\z/;
my $IMG_RE  = qr/\Ahttps?:\/\/[^\s"<>]+\.(?:jpe?g|gif|png)\z/i;

sub roll_dice {
  my ($text) = @_;
  return undef unless $text =~ $DICE_RE;
  my ($count, $sides, $mod) = ($1, $2, $3 || 0);
  return undef if $count < 1 || $count > 20 || $sides < 2 || $sides > 1000;
  my @values = map { 1 + int(rand($sides)) } 1 .. $count;
  my $total = $mod;
  $total += $_ for @values;
  my $detail = join(', ', @values) . ($mod ? " ($mod)" : '');
  return "$text → [$detail] = $total";
}

sub message_html {
  my ($msg, $images_allowed) = @_;
  my $time = '<span class="small">(' . jst_hm($msg->{t}) . ')</span>';
  my $kind = $msg->{k} || 'chat';

  if ($kind eq 'sys') {
    return '<div class="sys">--- ' . ChatLib::esc($msg->{x}) . " $time ---</div>";
  }
  if ($kind eq 'dice') {
    return '<div class="dice">★' . name_html($msg->{n}, $msg->{c}) . ' のサイコロ: '
      . ChatLib::esc($msg->{x}) . " $time</div>";
  }
  my $body = ChatLib::esc($msg->{x});
  if ($images_allowed && $msg->{x} =~ $IMG_RE) {
    my $u = ChatLib::esc($msg->{x});
    $body = '<a href="' . $u . '" target="_blank" rel="noreferrer">' . $u . '</a><br>'
      . '<img src="' . $u . '" alt="投稿画像" class="chatimg">';
  }
  return '<div>' . name_html($msg->{n}, $msg->{c}) . '＞ ' . $body . " $time</div>";
}

sub log_html {
  my ($room) = @_;
  my @lines;
  for my $msg (reverse @{ $room->{log} || [] }) {
    push @lines, message_html($msg, $room->{images});
  }
  return join("\n", @lines);
}

sub lock_mark { my ($room) = @_; return $room->{join} ? '◆鍵' : ''; }

sub online_count {
  my %seen;
  for my $id (ChatLib::room_ids()) {
    my $room = ChatLib::room_load($id) or next;
    my $live = ChatLib::active_members($room);
    $seen{$_} = 1 for keys %$live;
  }
  return scalar(keys %seen);
}

# 入室中の部屋の滞在時刻を更新する(書き込み削減のため30秒間隔)
sub touch_room {
  my ($s, $rid) = @_;
  ChatLib::room_update($rid, sub {
    my ($room) = @_;
    return undef unless $room;
    my $m = $room->{members}{ $s->{sid} } or return undef;
    return undef if ChatLib::now() - ($m->{last} || 0) < 30;
    $m->{last} = ChatLib::now();
    return $room;
  });
}

# ---- ページ: TOP --------------------------------------------------------

my %TOP_NOTICE = (
  noroom   => ['err', 'その部屋は見つかりませんでした（削除された可能性があります）'],
  deleted  => ['ok',  '部屋を削除しました'],
  contact  => ['ok',  'メッセージを送信しました。ありがとうございました'],
  profile  => ['ok',  '名前を保存しました'],
  ratelimit=> ['err', '操作が早すぎます。少し時間をおいてからお試しください'],
);

sub page_top {
  my ($s) = @_;

  my $notice = '';
  if (my $n = $TOP_NOTICE{ $FORM->{e} || '' }) {
    $notice = '<div class="' . $n->[0] . '">' . ChatLib::esc($n->[1]) . '</div>';
  }

  my @info = ChatLib::info_lines();
  my $info_html = '';
  if (@info) {
    $info_html = '<div class="info"><b>■インフォメーション</b><br>';
    for my $i (0 .. ($#info < 4 ? $#info : 4)) {
      $info_html .= '<span class="small">' . ChatLib::esc($info[$i]) . '</span><br>';
    }
    $info_html .= '<span class="small">[<a href="' . url('mode=info') . '">過去の更新情報</a>]</span>'
      if @info > 5;
    $info_html .= '</div>';
  }

  my @rooms = grep { defined } map { ChatLib::room_load($_) } ChatLib::room_ids();
  @rooms = sort { ($b->{official} || 0) <=> ($a->{official} || 0) || $a->{id} <=> $b->{id} } @rooms;

  my $rows = '';
  for my $room (@rooms) {
    my $desc = $room->{desc} || '';
    $desc = substr($desc, 0, 40) . '…' if length($desc) > 40;
    my $count = scalar(keys %{ ChatLib::active_members($room) });
    $rows .= '<tr>'
      . '<td>' . $room->{id} . '</td>'
      . '<td><a href="' . url('room=' . $room->{id}) . '">'
      . ($room->{official} ? '★' : '') . ChatLib::esc($room->{name}) . '</a> ' . lock_mark($room) . '</td>'
      . '<td>' . ChatLib::esc($desc) . '</td>'
      . '<td align="right">' . $count . '/' . $room->{capacity} . '人</td>'
      . '</tr>';
  }

  my $body =
      tabs_html($s, 'top')
    . '<h1>' . ChatLib::esc($SITE) . '</h1>'
    . '<div class="small">ヒマな人のためのチャット。登録不要・完全無料。</div>'
    . '<div>現在 <b>' . online_count() . '</b> 人がチャット中 ／ 部屋数 ' . scalar(@rooms)
    . ' ／ <a href="' . url('') . '">再読込</a></div>'
    . $notice
    . $info_html
    . '<h2>■あなたの名前(全部屋共通)</h2>'
    . '<form method="POST" action="' . url('mode=profile') . '">'
    . '<div class="box">'
    . csrf_field($s)
    . '現在: ' . name_html($s->{name}, $s->{color}) . '<br>'
    . '名前: <input type="text" name="name" size="12" maxlength="' . ChatLib::cfg('max_name')
    . '" value="' . ChatLib::esc($s->{name}) . '"><br>'
    . '名前の色(見たままの色を選んでください):<br>'
    . palette_html($s->{color})
    . '<input type="submit" value="保存">'
    . '<div class="small">※名前はここでだけ変更できます。入室中の全部屋・個人チャットに反映されます。</div>'
    . '</div></form>'
    . '<h2>■チャットルーム一覧</h2>'
    . '<div class="small">部屋名を押すと説明を確認してから入室できます。◆鍵 はパスワードが必要な個室です。</div>'
    . '<table width="100%">'
    . '<tr><th>No.</th><th>部屋名</th><th>説明</th><th>人数</th></tr>'
    . $rows
    . '</table>'
    . '<form method="GET" action="' . url('') . '">'
    . '<input type="hidden" name="mode" value="create">'
    . '<div style="margin:6px 0;"><input type="submit" value="部屋を作る"></div>'
    . '</form>'
    . '<hr>'
    . '[<a href="' . url('mode=pmlist') . '">個人チャット</a>] '
    . '[<a href="' . url('mode=info') . '">インフォメーション</a>] '
    . '[<a href="' . url('mode=contact') . '">管理者に連絡</a>]'
    . '<hr>'
    . '<div class="small">※個人情報（本名・住所・連絡先など）は絶対に書き込まないでください。<br>'
    . '※同時に入室できるのは' . ChatLib::cfg('max_joined_rooms') . '部屋までです。一定時間操作がないと自動退室になります。</div>';

  send_html('部屋一覧', $body);
}

# ---- ページ: 入室確認 ---------------------------------------------------

my %ENTRY_ERR = (
  pass  => '入室パスワードが違います',
  full  => '満室のため入室できません',
  ban   => 'この部屋への入室は禁止されています',
  limit => '同時に入室できるのは' . ChatLib::cfg('max_joined_rooms') . '部屋までです。どこかの部屋を退室してください',
);

sub page_entry {
  my ($s, $room) = @_;
  my $err = $ENTRY_ERR{ $FORM->{e} || '' };
  my $err_html = $err ? '<div class="err">' . ChatLib::esc($err) . '</div>' : '';
  my $count = scalar(keys %{ ChatLib::active_members($room) });

  my $pass_field = $room->{join}
    ? '入室パスワード: <input type="password" name="joinpass" size="10" maxlength="'
      . ChatLib::cfg('max_pass') . '"><br>'
    : '';

  my $body =
      tabs_html($s, '')
    . '<h1>' . ($room->{official} ? '★' : '') . ChatLib::esc($room->{name}) . ' ' . lock_mark($room) . '</h1>'
    . $err_html
    . '<table width="100%">'
    . '<tr><th width="90">部屋No.</th><td>' . $room->{id} . '</td></tr>'
    . '<tr><th>説明文</th><td>' . (length($room->{desc} || '') ? ChatLib::esc($room->{desc}) : '(説明はありません)') . '</td></tr>'
    . '<tr><th>人数</th><td>' . $count . '/' . $room->{capacity} . '人</td></tr>'
    . '<tr><th>入室制限</th><td>' . ($room->{join} ? '◆鍵付き個室(入室パスワードが必要です)' : 'なし(誰でも入室できます)') . '</td></tr>'
    . '<tr><th>画像投稿</th><td>' . ($room->{images} ? '可' : '不可') . '</td></tr>'
    . '</table>'
    . '<h2>■この部屋に入りますか？</h2>'
    . '<form method="POST" action="' . url('mode=join') . '">'
    . '<div class="box">'
    . csrf_field($s)
    . '<input type="hidden" name="room" value="' . $room->{id} . '">'
    . 'あなたの名前: ' . name_html($s->{name}, $s->{color})
    . ' <span class="small">(名前は<a href="' . url('') . '">TOPページ</a>で変更できます)</span><br>'
    . $pass_field
    . '<input type="submit" value="入室する"> <a href="' . url('') . '">[やめる(TOPへ戻る)]</a>'
    . '</div></form>';

  send_html('入室確認', $body);
}

# ---- ページ: チャット(フレーム) -----------------------------------------

sub valid_auto {
  my ($v) = @_;
  return undef unless defined $v && $v =~ /\A\d{1,3}\z/;
  return 0 if $v == 0;
  my $min = ChatLib::cfg('min_auto');
  return undef unless $v == 5 || $v == 10 || $v == 30;
  return $v < $min ? $min : $v;
}

sub page_frameset {
  my ($room) = @_;
  my $html = '<html><head>'
    . '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">'
    . '<meta name="viewport" content="width=device-width">'
    . '<title>' . ChatLib::esc("$SITE - " . $room->{name}) . '</title>'
    . '</head>'
    . '<frameset rows="*,120">'
    . '<frame src="' . url('mode=log&room=' . $room->{id}) . '" name="chatlog">'
    . '<frame src="' . url('mode=post&room=' . $room->{id}) . '" name="chatpost">'
    . '<noframes><body>お使いのブラウザはフレームに対応していません。'
    . '<a href="' . url('room=' . $room->{id} . '&amp;noframe=1') . '">フレームなし版はこちら</a></body></noframes>'
    . '</frameset></html>';
  send_html($room->{name}, $html, 1);
}

# ログフレーム(自動更新される側)
sub page_log {
  my ($s, $room) = @_;
  touch_room($s, $room->{id});

  if (defined(my $a = valid_auto($FORM->{auto}))) {
    $s->{auto} = $a;
    ChatLib::session_save($s);
  }
  my $auto = defined $s->{auto} ? $s->{auto} : ChatLib::cfg('default_auto');
  my $self = url('mode=log&room=' . $room->{id});
  my $refresh = $auto ? '<meta http-equiv="refresh" content="' . $auto . ';url=' . $self . '">' : '';

  my $links = join(' ', map {
    my ($v, $label) = @$_;
    $auto == $v ? "<b>[$label]</b>" : '<a href="' . $self . '&amp;auto=' . $v . '">[' . $label . ']</a>';
  } ([5, '5秒'], [10, '10秒'], [30, '30秒'], [0, 'OFF']));

  my $admin_link = $room->{admin}
    ? ' [<a href="' . url('mode=admin&room=' . $room->{id}) . '" target="_top">管理</a>]' : '';
  my $count = scalar(keys %{ ChatLib::active_members($room) });

  my $rate_html = (($FORM->{e} || '') eq 'rate')
    ? '<div class="err">発言が早すぎます。少し時間をおいてからお試しください</div>' : '';

  my $body =
      $refresh
    . tabs_html($s, 'room' . $room->{id}, 1)
    . $rate_html
    . '<b>' . ($room->{official} ? '★' : '') . ChatLib::esc($room->{name}) . '</b>'
    . " ($count/" . $room->{capacity} . '人) ' . lock_mark($room)
    . ' [' . popup_link(url('mode=members&room=' . $room->{id}), '参加者一覧', 480, 420) . ']'
    . $admin_link
    . ' [<a href="' . url('mode=leave&room=' . $room->{id}) . '" target="_top">退室</a>]'
    . ' [<a href="' . $self . '">更新</a>]'
    . '<div class="small">自動更新: ' . $links
    . ' ／ <a href="' . url('room=' . $room->{id} . '&amp;noframe=1') . '" target="_top">フレームなし版</a></div>'
    . '<hr>'
    . log_html($room);

  send_html($room->{name}, $body);
}

# 入力フレーム(自動更新されない側)
sub page_post {
  my ($s, $room) = @_;
  my $body =
      '<form method="POST" action="' . url('mode=say') . '" target="chatlog"'
    . ' onsubmit="var f=this;setTimeout(function(){f.m.value=\'\';},100);">'
    . csrf_field($s)
    . '<input type="hidden" name="room" value="' . $room->{id} . '">'
    . '<input type="hidden" name="fromframe" value="1">'
    . name_html($s->{name}, $s->{color}) . '＞ '
    . '<input type="text" name="m" size="30" maxlength="' . ChatLib::cfg('max_message') . '"> '
    . '<input type="submit" value="送信">'
    . '</form>'
    . '<div class="small">発言すると上のログがすぐ更新されます ／ 「2d6」でサイコロ'
    . ($room->{images} ? ' ／ 画像URL(jpg/gif/png)で画像表示' : '') . '</div>';
  send_html('発言 - ' . $room->{name}, $body);
}

# フレームなし版(フレーム非対応ブラウザ用・手動更新が基本)
sub page_chat_noframe {
  my ($s, $room) = @_;
  touch_room($s, $room->{id});

  my $auto = valid_auto($FORM->{auto});
  $auto = 0 unless defined $auto;
  my $base = url('room=' . $room->{id} . '&amp;noframe=1');
  my $refresh = $auto ? '<meta http-equiv="refresh" content="' . $auto . ';url=' . $base . '&amp;auto=' . $auto . '">' : '';

  my $links = '自動更新: ' . join(' ', map {
    my ($v, $label) = @$_;
    $auto == $v ? "<b>[$label]</b>" : '<a href="' . $base . '&amp;auto=' . $v . '">[' . $label . ']</a>';
  } ([0, 'OFF'], [10, '10秒'], [30, '30秒']))
    . ' <span class="small">(自動更新中は入力中の文字が消えるのでご注意)</span>';

  my $admin_link = $room->{admin} ? ' [<a href="' . url('mode=admin&room=' . $room->{id}) . '">管理</a>]' : '';
  my $count = scalar(keys %{ ChatLib::active_members($room) });

  my $body =
      $refresh
    . tabs_html($s, 'room' . $room->{id})
    . '<b>' . ($room->{official} ? '★' : '') . ChatLib::esc($room->{name}) . '</b>'
    . " ($count/" . $room->{capacity} . '人) ' . lock_mark($room)
    . ' [' . popup_link(url('mode=members&room=' . $room->{id}), '参加者一覧', 480, 420) . ']'
    . $admin_link
    . ' [<a href="' . url('mode=leave&room=' . $room->{id}) . '">退室</a>]'
    . '<div class="small">' . ChatLib::esc($room->{desc} || '') . '</div>'
    . '<hr>'
    . '<form method="POST" action="' . url('mode=say') . '">'
    . csrf_field($s)
    . '<input type="hidden" name="room" value="' . $room->{id} . '">'
    . '<input type="hidden" name="auto" value="' . $auto . '">'
    . '<input type="hidden" name="noframe" value="1">'
    . name_html($s->{name}, $s->{color}) . '＞ '
    . '<input type="text" name="m" size="24" maxlength="' . ChatLib::cfg('max_message') . '"> '
    . '<input type="submit" value="送信"> '
    . '[<a href="' . $base . '&amp;auto=' . $auto . '">更新</a>]'
    . '</form>'
    . '<div class="small">「2d6」でサイコロ'
    . ($room->{images} ? ' ／ 画像URL(jpg/gif/png)を発言すると画像表示' : '')
    . ' ／ ' . $links
    . ' ／ <a href="' . url('room=' . $room->{id}) . '">自動更新(フレーム)版へ</a></div>'
    . '<hr>'
    . log_html($room)
    . '<hr>'
    . '[<a href="' . $base . '&amp;auto=' . $auto . '">更新</a>] '
    . '[<a href="' . url('mode=leave&room=' . $room->{id}) . '">退室</a>] '
    . '[<a href="' . url('') . '">TOPへ</a>]';

  send_html($room->{name}, $body);
}

# ---- 動作: 入室 / 退室 / 発言 -------------------------------------------

sub do_join {
  my ($s) = @_;
  require_csrf($s);
  my $rid = $FORM->{room} || '';
  my $room = ChatLib::room_load($rid) or redirect(url('e=noroom'));
  my $base = url("room=$rid");

  return redirect($base) if $s->{rooms}{$rid};
  return redirect("$base&amp;e=ban")
    if ($room->{ban_pids}{ $s->{pid} } || ($s->{ip} && $room->{ban_ips}{ $s->{ip} }));

  my $live = ChatLib::active_members($room);
  return redirect("$base&amp;e=full") if scalar(keys %$live) >= $room->{capacity};
  return redirect("$base&amp;e=limit")
    if scalar(keys %{ $s->{rooms} }) >= ChatLib::cfg('max_joined_rooms');

  if ($room->{join}) {
    my $given = ChatLib::clean_text($FORM->{joinpass}, ChatLib::cfg('max_pass'));
    return redirect("$base&amp;e=pass") unless ChatLib::verify_pass($given, $room->{join});
  }

  ChatLib::room_update($rid, sub {
    my ($r) = @_;
    return undef unless $r;
    $r->{members}{ $s->{sid} } = {
      pid => $s->{pid}, name => $s->{name}, color => $s->{color},
      joined => ChatLib::now(), last => ChatLib::now(),
    };
    ChatLib::room_log_push($r, { k => 'sys', x => $s->{name} . ' さんが入室しました' });
    return $r;
  });

  $s->{rooms}{$rid} = ChatLib::now();
  ChatLib::session_touch($s);
  redirect($base);
}

sub do_leave {
  my ($s) = @_;
  my $rid = $FORM->{room} || '';
  if ($s->{rooms}{$rid}) {
    delete $s->{rooms}{$rid};
    ChatLib::room_update($rid, sub {
      my ($r) = @_;
      return undef unless $r;
      my $m = delete $r->{members}{ $s->{sid} };
      ChatLib::room_log_push($r, { k => 'sys', x => ($m->{name} || $s->{name}) . ' さんが退室しました' });
      return $r;
    });
    ChatLib::session_touch($s);
  }
  redirect(url(''));
}

sub do_say {
  my ($s) = @_;
  require_csrf($s);
  my $rid = $FORM->{room} || '';
  my $from_frame = ($FORM->{fromframe} || '') eq '1';
  my $back = $from_frame ? url("mode=log&room=$rid")
                         : url("room=$rid&noframe=1&auto=" . (valid_auto($FORM->{auto}) || 0));

  my $room = ChatLib::room_load($rid) or redirect(url(''));
  redirect(url('')) unless $s->{rooms}{$rid};

  # 連投制限
  unless (ChatLib::rate_ok($s, 'posts')) {
    ChatLib::session_save($s);
    redirect($back . '&amp;e=rate');
  }
  ChatLib::session_save($s);

  my $text = ChatLib::clean_text($FORM->{m}, ChatLib::cfg('max_message'));
  if (length $text) {
    ChatLib::room_update($rid, sub {
      my ($r) = @_;
      return undef unless $r;
      $r->{members}{ $s->{sid} }{last} = ChatLib::now() if $r->{members}{ $s->{sid} };
      ChatLib::room_log_push($r, { k => 'chat', n => $s->{name}, c => $s->{color}, x => $text });
      if (defined(my $dice = roll_dice($text))) {
        ChatLib::room_log_push($r, { k => 'dice', n => $s->{name}, c => $s->{color}, x => $dice });
      }
      return $r;
    });
  }
  redirect($back);
}

# ---- ページ: プロフィール保存 -------------------------------------------

sub do_profile {
  my ($s) = @_;
  require_csrf($s);
  my $name = ChatLib::clean_text($FORM->{name}, ChatLib::cfg('max_name'));
  $name = $s->{name} unless length $name;
  my $color = valid_color($FORM->{color});
  $s->{name}  = $name;
  $s->{color} = $color;
  ChatLib::session_touch($s);
  set_cookie('name', $name, 60 * 60 * 24 * 30);
  set_cookie('color', $color, 60 * 60 * 24 * 30);

  # 入室中の全部屋に名前・色を反映する
  for my $rid (keys %{ $s->{rooms} || {} }) {
    ChatLib::room_update($rid, sub {
      my ($r) = @_;
      return undef unless $r && $r->{members}{ $s->{sid} };
      $r->{members}{ $s->{sid} }{name}  = $name;
      $r->{members}{ $s->{sid} }{color} = $color;
      return $r;
    });
  }
  redirect(url('e=profile'));
}

# ---- ページ: 部屋作成 ---------------------------------------------------

my %CREATE_ERR = (
  roomname  => '部屋の名前を入力してください',
  roomsmax  => 'これ以上部屋を作成できません',
  noadmin   => '管理パスワードを入力してください',
  samepass  => '入室パスワードは管理パスワードと同じにできません',
  ratelimit => '部屋の作成が続いています。少し時間をおいてからお試しください',
  limit     => '同時に入室できるのは' . ChatLib::cfg('max_joined_rooms') . '部屋までです。どこかの部屋を退室してください',
);

sub page_create {
  my ($s) = @_;
  my $err = $CREATE_ERR{ $FORM->{e} || '' };
  my $err_html = $err ? '<div class="err">' . ChatLib::esc($err) . '</div>' : '';

  my $opts = '';
  for my $n (ChatLib::cfg('min_capacity') .. ChatLib::cfg('max_capacity')) {
    $opts .= '<option value="' . $n . '"' . ($n == 20 ? ' selected' : '') . '>' . $n . '人</option>';
  }

  my $body =
      tabs_html($s, '')
    . '<h1>部屋を作る</h1>'
    . $err_html
    . '<form method="POST" action="' . url('mode=create') . '">'
    . '<div class="box">'
    . csrf_field($s)
    . '部屋名: <input type="text" name="roomname" size="16" maxlength="' . ChatLib::cfg('max_room_name') . '"> '
    . '定員: <select name="capacity">' . $opts . '</select><br>'
    . '説明文:<br><textarea name="roomdesc" rows="3" cols="40"></textarea><br>'
    . '管理パスワード(必須): <input type="password" name="adminpass" size="10" maxlength="' . ChatLib::cfg('max_pass') . '"><br>'
    . '入室パスワード(任意・鍵付き個室にする場合): <input type="password" name="joinpass" size="10" maxlength="' . ChatLib::cfg('max_pass') . '"><br>'
    . '<input type="checkbox" name="images" value="1">画像投稿(画像URLのインライン表示)を許可する<br>'
    . '<input type="submit" value="作成して入室"> <a href="' . url('') . '">[やめる(TOPへ戻る)]</a>'
    . '<div class="small">※管理パスワードで部屋の削除・アクセス禁止・画像投稿の切替ができます。<br>'
    . '※パスワードは元に戻せない形(ハッシュ)で保存され、忘れると管理できなくなります。<br>'
    . '※名前はTOPページで設定したものが使われます。</div>'
    . '</div></form>';

  send_html('部屋を作る', $body);
}

sub do_create {
  my ($s) = @_;
  require_csrf($s);
  my $name = ChatLib::clean_text($FORM->{roomname}, ChatLib::cfg('max_room_name'));
  redirect(url('mode=create&e=roomname')) unless length $name;
  redirect(url('mode=create&e=roomsmax')) if scalar(ChatLib::room_ids()) >= ChatLib::cfg('max_rooms');

  my $admin_pass = ChatLib::clean_text($FORM->{adminpass}, ChatLib::cfg('max_pass'));
  redirect(url('mode=create&e=noadmin')) unless length $admin_pass;
  my $join_pass = ChatLib::clean_text($FORM->{joinpass}, ChatLib::cfg('max_pass'));
  redirect(url('mode=create&e=samepass')) if length($join_pass) && $join_pass eq $admin_pass;
  redirect(url('mode=create&e=limit'))
    if scalar(keys %{ $s->{rooms} }) >= ChatLib::cfg('max_joined_rooms');

  unless (ChatLib::rate_ok($s, 'creates')) {
    ChatLib::session_save($s);
    redirect(url('mode=create&e=ratelimit'));
  }

  my $capacity = $FORM->{capacity} || 20;
  $capacity = 20 unless $capacity =~ /\A\d{1,3}\z/;
  $capacity = ChatLib::cfg('min_capacity') if $capacity < ChatLib::cfg('min_capacity');
  $capacity = ChatLib::cfg('max_capacity') if $capacity > ChatLib::cfg('max_capacity');

  my $room = ChatLib::room_new(
    name       => $name,
    desc       => ChatLib::clean_text($FORM->{roomdesc}, ChatLib::cfg('max_room_desc')),
    admin_pass => $admin_pass,
    join_pass  => (length($join_pass) ? $join_pass : undef),
    capacity   => $capacity,
    images     => (($FORM->{images} || '') eq '1'),
  );

  ChatLib::room_update($room->{id}, sub {
    my ($r) = @_;
    return undef unless $r;
    $r->{members}{ $s->{sid} } = {
      pid => $s->{pid}, name => $s->{name}, color => $s->{color},
      joined => ChatLib::now(), last => ChatLib::now(),
    };
    ChatLib::room_log_push($r, { k => 'sys', x => $s->{name} . ' さんが入室しました' });
    return $r;
  });

  $s->{rooms}{ $room->{id} } = ChatLib::now();
  ChatLib::session_touch($s);
  redirect(url('room=' . $room->{id}));
}

# ---- ページ: 参加者一覧 / ユーザー詳細 ----------------------------------

sub page_members {
  my ($s, $room) = @_;
  my $live = ChatLib::active_members($room);
  my $rows = '';
  for my $sid (sort { ($live->{$a}{joined} || 0) <=> ($live->{$b}{joined} || 0) } keys %$live) {
    my $m = $live->{$sid};
    my $is_self = $sid eq $s->{sid};
    my $pm = $is_self ? '-'
      : '<a href="' . url('mode=pm&with=' . $m->{pid}) . '" target="_top">個人チャット</a>';
    $rows .= '<tr>'
      . '<td>' . name_html($m->{name}, $m->{color}) . ($is_self ? ' <span class="small">(自分)</span>' : '') . '</td>'
      . '<td>' . jst_hm($m->{joined}) . '</td>'
      . '<td><a href="' . url('mode=user&room=' . $room->{id} . '&id=' . $m->{pid}) . '">詳細</a></td>'
      . '<td>' . $pm . '</td>'
      . '</tr>';
  }

  my $body =
      '<b>' . ChatLib::esc($room->{name}) . '</b> の参加者 ('
    . scalar(keys %$live) . '/' . $room->{capacity} . '人)'
    . '<hr>'
    . '<table width="100%">'
    . '<tr><th>名前</th><th>入室時刻</th><th>詳細</th><th>個人チャット</th></tr>'
    . $rows
    . '</table>'
    . '<hr>'
    . '[<a href="' . url('room=' . $room->{id}) . '" target="_top">チャットに戻る</a>]'
    . '<div class="small">※ポップアップで開いた場合はこのウィンドウを閉じてください'
    . '(ゲーム機など別ウィンドウが開けないブラウザは「チャットに戻る」でどうぞ)</div>';

  send_html('参加者一覧 - ' . $room->{name}, $body);
}

sub page_user {
  my ($s, $room) = @_;
  my $pid = $FORM->{id} || '';
  my $live = ChatLib::active_members($room);
  my ($target_sid) = grep { ($live->{$_}{pid} || '') eq $pid } keys %$live;

  unless ($target_sid) {
    send_html('ユーザー詳細',
      '<div class="err">そのユーザーは見つかりませんでした（退室した可能性があります）</div>'
      . '<hr>[<a href="' . url('mode=members&room=' . $room->{id}) . '">参加者一覧に戻る</a>]');
  }

  my $m = $live->{$target_sid};
  # IP・UAはセッションから取得する
  my $ts = ChatLib::session_load($target_sid) || {};

  my $body =
      '<b>ユーザー詳細</b>'
    . '<hr>'
    . '<table width="100%">'
    . '<tr><th width="110">名前</th><td>' . name_html($m->{name}, $m->{color}) . '</td></tr>'
    . '<tr><th>名前の色</th><td><font color="' . color_hex($m->{color}) . '">■</font> ' . color_hex($m->{color}) . '</td></tr>'
    . '<tr><th>入室時刻</th><td>' . jst_hm($m->{joined}) . '</td></tr>'
    . '<tr><th>最終アクセス</th><td>' . jst_hm($m->{last}) . '</td></tr>'
    . '<tr><th>IPアドレス</th><td>' . ChatLib::esc($ts->{ip} || '(不明)') . '</td></tr>'
    . '<tr><th>プロバイダ<br>(リモートホスト)</th><td class="ua">'
    . ChatLib::esc(length($ts->{host} || '') ? $ts->{host} : '(逆引きできませんでした)') . '</td></tr>'
    . '<tr><th>ユーザーエージェント</th><td class="ua">' . ChatLib::esc($ts->{ua} || '(不明)') . '</td></tr>'
    . '</table>'
    . '<hr>'
    . '[<a href="' . url('mode=members&room=' . $room->{id}) . '">参加者一覧に戻る</a>]'
    . ($target_sid eq $s->{sid} ? ''
       : ' [<a href="' . url('mode=pm&with=' . $m->{pid}) . '" target="_top">個人チャット</a>]');

  send_html('ユーザー詳細', $body);
}

# ---- ページ: 個人チャット -----------------------------------------------

my %PM_ERR = (
  blocked   => '送信できませんでした（相手に無視されています）',
  youblock  => 'この相手を無視中です。解除すると送受信できます',
  gone      => '相手が見つかりませんでした（退室した可能性があります）',
  notshared => '個人チャットは同じトークルームにいる相手とだけできます（同じ部屋に入ってから送信してください）',
  ratelimit => '送信が早すぎます。少し時間をおいてからお試しください',
);

# 相手の表示情報を得る(在室していなければログから拾う)
sub pm_partner_info {
  my ($s, $thread, $pid) = @_;
  if (my $m = ChatLib::find_member_by_pid($s, $pid)) {
    return { name => $m->{name}, color => $m->{color}, online => 1 };
  }
  if ($thread) {
    for my $msg (reverse @{ $thread->{log} || [] }) {
      next unless ($msg->{p} || '') eq $pid;
      return { name => $msg->{n}, color => $msg->{c}, online => 0 };
    }
  }
  return { name => '(不明)', color => 'gray', online => 0 };
}

sub page_pm_list {
  my ($s) = @_;
  my $rows = '';
  for my $th (ChatLib::pm_list_for($s->{pid})) {
    my ($pid) = grep { $_ ne $s->{pid} } @{ $th->{pids} };
    next unless $pid;
    my $info = pm_partner_info($s, $th, $pid);
    my $last = @{ $th->{log} || [] } ? $th->{log}[-1]{t} : 0;
    my $unread = ($th->{unread} && $th->{unread}{ $s->{pid} }) ? ' <span class="err">●新着</span>' : '';
    my $blocked = ($s->{blocks} && $s->{blocks}{$pid}) ? ' <span class="small">(無視中)</span>' : '';
    $rows .= '<tr>'
      . '<td>' . name_html($info->{name}, $info->{color})
      . ($info->{online} ? '' : ' <span class="small">(不在)</span>') . $unread . $blocked . '</td>'
      . '<td>' . ($last ? jst_hm($last) : '-') . '</td>'
      . '<td><a href="' . url('mode=pm&with=' . $pid) . '">開く</a></td>'
      . '</tr>';
  }
  $rows = '<tr><td colspan="3">(個人チャットはまだありません。部屋の参加者一覧から始められます)</td></tr>'
    unless length $rows;

  my $body =
      tabs_html($s, 'pm')
    . '<h1>個人チャット</h1>'
    . '<table width="100%">'
    . '<tr><th>相手</th><th>最終発言</th><th>開く</th></tr>' . $rows . '</table>'
    . '<hr>'
    . '[<a href="' . url('mode=pmlist') . '">更新</a>] [<a href="' . url('') . '">TOPへ</a>]';

  send_html('個人チャット', $body);
}

sub page_pm {
  my ($s) = @_;
  my $pid = $FORM->{with} || '';
  redirect(url('mode=pmlist')) unless $pid =~ /\A[0-9a-f]{8}\z/ && $pid ne $s->{pid};

  my $thread = ChatLib::pm_load($s->{pid}, $pid);

  # 新規は同室者限定。既存のやり取りは相手が退室していても閲覧できる。
  if (!$thread && !ChatLib::shares_room($s, $pid)) {
    send_html('個人チャット',
      tabs_html($s, 'pm')
      . '<h1>個人チャット</h1>'
      . '<div class="err">' . ChatLib::esc($PM_ERR{notshared}) . '</div>'
      . '<hr>[<a href="' . url('mode=pmlist') . '">一覧へ</a>] [<a href="' . url('') . '">TOPへ</a>]');
  }

  # 既読にする
  if ($thread && $thread->{unread} && $thread->{unread}{ $s->{pid} }) {
    $thread->{unread}{ $s->{pid} } = 0;
    ChatLib::pm_save($thread);
  }

  my $info = pm_partner_info($s, $thread, $pid);
  my $err = $PM_ERR{ $FORM->{e} || '' };
  my $err_html = $err ? '<div class="err">' . ChatLib::esc($err) . '</div>' : '';
  my $i_block = ($s->{blocks} && $s->{blocks}{$pid}) ? 1 : 0;

  my $block_form =
      '<form method="POST" action="' . url('mode=pmblock') . '" style="display:inline;">'
    . csrf_field($s)
    . '<input type="hidden" name="with" value="' . ChatLib::esc($pid) . '">'
    . '<input type="hidden" name="onoff" value="' . ($i_block ? 'off' : 'on') . '">'
    . '<input type="submit" value="' . ($i_block ? '無視解除' : '無視する') . '">'
    . '</form>';

  my $send_form = $i_block
    ? '<div class="sys">この相手を無視中のため送信できません。</div>'
    : '<form method="POST" action="' . url('mode=pmsay') . '">'
      . csrf_field($s)
      . '<input type="hidden" name="with" value="' . ChatLib::esc($pid) . '">'
      . name_html($s->{name}, $s->{color}) . '＞ '
      . '<input type="text" name="m" size="24" maxlength="' . ChatLib::cfg('max_message') . '"> '
      . '<input type="submit" value="送信"> '
      . '[<a href="' . url('mode=pm&with=' . $pid) . '">更新</a>]'
      . '</form>';

  my @lines;
  for my $msg (reverse @{ ($thread && $thread->{log}) || [] }) {
    push @lines, '<div>' . name_html($msg->{n}, $msg->{c}) . '＞ ' . ChatLib::esc($msg->{x})
      . ' <span class="small">(' . jst_hm($msg->{t}) . ')</span></div>';
  }

  my $body =
      tabs_html($s, 'pm')
    . '<b>個人チャット: ' . name_html($info->{name}, $info->{color}) . '</b>'
    . ($info->{online} ? '' : ' <span class="small">(不在)</span>')
    . ' ' . $block_form
    . $err_html
    . '<hr>'
    . $send_form
    . '<div class="small">※このやり取りは相手とあなたにしか見えません。個人チャットは同じトークルームにいる相手とだけできます。</div>'
    . '<hr>'
    . (@lines ? join("\n", @lines) : '<div class="sys">(まだ発言はありません)</div>')
    . '<hr>'
    . '[<a href="' . url('mode=pm&with=' . $pid) . '">更新</a>] '
    . '[<a href="' . url('mode=pmlist') . '">一覧へ</a>] [<a href="' . url('') . '">TOPへ</a>]';

  send_html('個人チャット - ' . $info->{name}, $body);
}

sub do_pm_say {
  my ($s) = @_;
  require_csrf($s);
  my $pid = $FORM->{with} || '';
  redirect(url('mode=pmlist')) unless $pid =~ /\A[0-9a-f]{8}\z/ && $pid ne $s->{pid};
  my $back = url('mode=pm&with=' . $pid);

  redirect("$back&amp;e=youblock") if $s->{blocks} && $s->{blocks}{$pid};

  # 同室者限定
  my $member = ChatLib::find_member_by_pid($s, $pid);
  redirect("$back&amp;e=notshared") unless $member;

  my $partner = ChatLib::session_load($member->{sid});
  redirect("$back&amp;e=gone") unless $partner;
  redirect("$back&amp;e=blocked") if $partner->{blocks} && $partner->{blocks}{ $s->{pid} };

  unless (ChatLib::rate_ok($s, 'posts')) {
    ChatLib::session_save($s);
    redirect("$back&amp;e=ratelimit");
  }
  ChatLib::session_save($s);

  my $text = ChatLib::clean_text($FORM->{m}, ChatLib::cfg('max_message'));
  if (length $text) {
    my $thread = ChatLib::pm_load($s->{pid}, $pid)
      || { pids => [ $s->{pid}, $pid ], log => [], unread => {} };
    push @{ $thread->{log} }, {
      p => $s->{pid}, n => $s->{name}, c => $s->{color},
      x => $text, t => ChatLib::now(),
    };
    my $max = ChatLib::cfg('max_log_per_pm');
    splice(@{ $thread->{log} }, 0, scalar(@{ $thread->{log} }) - $max)
      if scalar(@{ $thread->{log} }) > $max;
    $thread->{unread}{$pid} = 1;
    $thread->{unread}{ $s->{pid} } = 0;
    ChatLib::pm_save($thread);
  }
  redirect($back);
}

sub do_pm_block {
  my ($s) = @_;
  require_csrf($s);
  my $pid = $FORM->{with} || '';
  redirect(url('mode=pmlist')) unless $pid =~ /\A[0-9a-f]{8}\z/;
  if (($FORM->{onoff} || '') eq 'on') { $s->{blocks}{$pid} = 1; }
  else                                { delete $s->{blocks}{$pid}; }
  ChatLib::session_touch($s);
  redirect(url('mode=pm&with=' . $pid));
}

# ---- ページ: 部屋の管理 -------------------------------------------------
#
# パスワードは照合後に管理トークンを発行し、以降はトークンで操作する。
# (パスワードをhidden fieldやURLに残さない)

sub admin_login_page {
  my ($s, $room, $error) = @_;
  send_html('部屋の管理',
      '<h1>部屋の管理: ' . ChatLib::esc($room->{name}) . '</h1>'
    . ($error ? '<div class="err">' . ChatLib::esc($error) . '</div>' : '')
    . '<form method="POST" action="' . url('mode=adminpanel') . '">'
    . '<div class="box">'
    . csrf_field($s)
    . '<input type="hidden" name="room" value="' . $room->{id} . '">'
    . '管理パスワード: <input type="password" name="pass" size="12" maxlength="' . ChatLib::cfg('max_pass') . '"> '
    . '<input type="submit" value="ログイン">'
    . '</div></form>'
    . '[<a href="' . url('room=' . $room->{id}) . '">チャットに戻る</a>]');
}

sub admin_authed {
  my ($s, $room) = @_;
  return 0 unless $room->{admin};
  my $tok = $s->{admin} && $s->{admin}{ $room->{id} };
  return 0 unless $tok;
  return (($FORM->{token} || '') eq $tok) ? 1 : 0;
}

sub admin_fields {
  my ($s, $room, $act) = @_;
  return csrf_field($s)
    . '<input type="hidden" name="room" value="' . $room->{id} . '">'
    . '<input type="hidden" name="token" value="' . ChatLib::esc($s->{admin}{ $room->{id} }) . '">'
    . '<input type="hidden" name="act" value="' . $act . '">';
}

sub admin_panel_page {
  my ($s, $room, $notice) = @_;
  my $live = ChatLib::active_members($room);

  my $member_rows = '';
  for my $sid (keys %$live) {
    my $m = $live->{$sid};
    my $ts = ChatLib::session_load($sid) || {};
    $member_rows .= '<tr>'
      . '<td>' . name_html($m->{name}, $m->{color}) . '</td>'
      . '<td class="ua">' . ChatLib::esc($ts->{ip} || '(不明)') . '</td>'
      . '<td><form method="POST" action="' . url('mode=adminact') . '">'
      . admin_fields($s, $room, 'ban')
      . '<input type="hidden" name="target" value="' . ChatLib::esc($m->{pid}) . '">'
      . '<input type="submit" value="アクセス禁止"></form></td>'
      . '</tr>';
  }
  $member_rows = '<tr><td colspan="3">(入室者なし)</td></tr>' unless length $member_rows;

  my $ban_rows = '';
  for my $ip (sort keys %{ $room->{ban_ips} || {} }) {
    $ban_rows .= '<tr><td class="ua">' . ChatLib::esc($ip) . '</td>'
      . '<td><form method="POST" action="' . url('mode=adminact') . '">'
      . admin_fields($s, $room, 'unban')
      . '<input type="hidden" name="target" value="' . ChatLib::esc($ip) . '">'
      . '<input type="submit" value="解除"></form></td></tr>';
  }
  $ban_rows = '<tr><td colspan="2">(アクセス禁止中のユーザーはいません)</td></tr>' unless length $ban_rows;

  my $body =
      '<h1>部屋の管理: ' . ChatLib::esc($room->{name}) . '</h1>'
    . ($notice ? '<div class="ok">' . ChatLib::esc($notice) . '</div>' : '')
    . '<h2>■画像投稿</h2>'
    . '<div class="box">現在: <b>' . ($room->{images} ? '許可' : '禁止') . '</b> '
    . '<form method="POST" action="' . url('mode=adminact') . '">'
    . admin_fields($s, $room, $room->{images} ? 'images_off' : 'images_on')
    . '<input type="submit" value="' . ($room->{images} ? '禁止にする' : '許可にする') . '">'
    . '</form></div>'
    . '<h2>■入室者とアクセス禁止</h2>'
    . '<table width="100%"><tr><th>名前</th><th>IP</th><th>操作</th></tr>' . $member_rows . '</table>'
    . '<div class="small">アクセス禁止にすると強制退室になり、同じIP・ユーザーからは再入室できません。</div>'
    . '<h2>■アクセス禁止リスト(IP)</h2>'
    . '<table width="100%"><tr><th>IP</th><th>操作</th></tr>' . $ban_rows . '</table>'
    . '<h2>■部屋の削除</h2>'
    . '<div class="box">'
    . '<form method="POST" action="' . url('mode=adminact') . '">'
    . admin_fields($s, $room, 'delete')
    . '<input type="submit" value="この部屋を削除する">'
    . '</form>'
    . '<span class="small">※押すと確認画面が表示されます。</span>'
    . '</div>'
    . '<hr>'
    . '[<a href="' . url('room=' . $room->{id}) . '">チャットに戻る</a>] [<a href="' . url('') . '">TOPへ</a>]';

  send_html('部屋の管理', $body);
}

sub admin_delete_confirm_page {
  my ($s, $room) = @_;
  my $count = scalar(keys %{ ChatLib::active_members($room) });
  send_html('部屋の削除確認',
      '<h1>部屋の削除確認</h1>'
    . '<div class="box">'
    . '<div class="err">本当に部屋「' . ChatLib::esc($room->{name}) . '」(No.' . $room->{id} . ')を削除しますか？</div>'
    . '<div class="small">※入室中の' . $count . '人は全員退室になり、ログも消えます。この操作は取り消せません。</div>'
    . '<form method="POST" action="' . url('mode=adminact') . '" style="display:inline;">'
    . admin_fields($s, $room, 'delete_confirm')
    . '<input type="submit" value="削除する"></form> '
    . '<form method="POST" action="' . url('mode=adminpanel') . '" style="display:inline;">'
    . csrf_field($s)
    . '<input type="hidden" name="room" value="' . $room->{id} . '">'
    . '<input type="hidden" name="token" value="' . ChatLib::esc($s->{admin}{ $room->{id} }) . '">'
    . '<input type="submit" value="やめる(管理画面へ戻る)"></form>'
    . '</div>');
}

sub do_admin_login {
  my ($s) = @_;
  require_csrf($s);
  my $room = ChatLib::room_load($FORM->{room} || '') or redirect(url('e=noroom'));
  my $pass = ChatLib::clean_text($FORM->{pass}, ChatLib::cfg('max_pass'));

  # 総当たり対策として試行にもレート制限をかける(発言とは別枠)
  unless (ChatLib::rate_ok($s, 'auth')) {
    ChatLib::session_save($s);
    return admin_login_page($s, $room, '試行が続いています。少し時間をおいてからお試しください');
  }
  ChatLib::session_save($s);

  unless (ChatLib::verify_pass($pass, $room->{admin})) {
    return admin_login_page($s, $room, '管理パスワードが違います');
  }
  $s->{admin}{ $room->{id} } = ChatLib::random_token(16);
  ChatLib::session_touch($s);
  admin_panel_page($s, $room, '');
}

sub do_admin_action {
  my ($s) = @_;
  require_csrf($s);
  my $room = ChatLib::room_load($FORM->{room} || '') or redirect(url('e=noroom'));
  return admin_login_page($s, $room, 'もう一度ログインしてください') unless admin_authed($s, $room);

  my $act = $FORM->{act} || '';
  my $notice = '';

  if ($act eq 'delete') {
    return admin_delete_confirm_page($s, $room);
  }
  if ($act eq 'delete_confirm') {
    # 入室者のセッションからも部屋を外す
    for my $sid (keys %{ $room->{members} || {} }) {
      my $ms = ChatLib::session_load($sid) or next;
      delete $ms->{rooms}{ $room->{id} };
      ChatLib::session_save($ms);
    }
    ChatLib::room_delete($room->{id});
    delete $s->{admin}{ $room->{id} };
    ChatLib::session_touch($s);
    redirect(url('e=deleted'));
  }

  if ($act eq 'images_on' || $act eq 'images_off') {
    my $on = $act eq 'images_on' ? 1 : 0;
    ChatLib::room_update($room->{id}, sub {
      my ($r) = @_; return undef unless $r; $r->{images} = $on; return $r;
    });
    $notice = $on ? '画像投稿を許可しました' : '画像投稿を禁止しました';
  }
  elsif ($act eq 'ban') {
    my $pid = $FORM->{target} || '';
    my $live = ChatLib::active_members($room);
    my ($sid) = grep { ($live->{$_}{pid} || '') eq $pid } keys %$live;
    if ($sid) {
      my $name = $live->{$sid}{name};
      my $ts = ChatLib::session_load($sid);
      my $ip = $ts ? ($ts->{ip} || '') : '';
      ChatLib::room_update($room->{id}, sub {
        my ($r) = @_;
        return undef unless $r;
        $r->{ban_pids}{$pid} = 1;
        $r->{ban_ips}{$ip} = 1 if length $ip;
        delete $r->{members}{$sid};
        ChatLib::room_log_push($r, { k => 'sys', x => $name . ' さんが退室しました（管理者によるアクセス禁止）' });
        return $r;
      });
      if ($ts) { delete $ts->{rooms}{ $room->{id} }; ChatLib::session_save($ts); }
      $notice = $name . ' さんをアクセス禁止にしました';
    } else {
      $notice = '対象のユーザーが見つかりませんでした';
    }
  }
  elsif ($act eq 'unban') {
    my $ip = $FORM->{target} || '';
    ChatLib::room_update($room->{id}, sub {
      my ($r) = @_; return undef unless $r; delete $r->{ban_ips}{$ip}; return $r;
    });
    $notice = 'アクセス禁止を解除しました';
  }

  admin_panel_page($s, ChatLib::room_load($room->{id}), $notice);
}

# ---- ページ: インフォメーション / 連絡 ----------------------------------

sub page_info {
  my ($s) = @_;
  my @lines = ChatLib::info_lines();
  my $list = @lines
    ? join('', map { '<div>' . ChatLib::esc($_) . '</div>' } @lines)
    : '<div>(更新情報はまだありません)</div>';
  send_html('インフォメーション',
      tabs_html($s, '')
    . '<h1>インフォメーション</h1>'
    . '<div class="info">' . $list . '</div>'
    . '[<a href="' . url('') . '">TOPへ戻る</a>] [<a href="' . url('mode=contact') . '">管理者に連絡</a>]');
}

sub page_contact {
  my ($s) = @_;
  send_html('管理者に連絡',
      tabs_html($s, '')
    . '<h1>管理者に連絡</h1>'
    . '<div class="small">不具合の報告・要望・削除依頼などはこちらからどうぞ。</div>'
    . '<form method="POST" action="' . url('mode=contact') . '">'
    . '<div class="box">'
    . csrf_field($s)
    . 'お名前(任意): <input type="text" name="name" size="16" maxlength="' . ChatLib::cfg('max_name') . '"><br>'
    . '連絡先(任意): <input type="text" name="addr" size="30" maxlength="100"><br>'
    . '内容:<br><textarea name="body" rows="6" cols="40"></textarea><br>'
    . '<input type="submit" value="送信する"> <a href="' . url('') . '">[やめる]</a>'
    . '</div></form>');
}

sub do_contact {
  my ($s) = @_;
  require_csrf($s);
  my $text = ChatLib::clean_text($FORM->{body}, 1000);
  redirect(url('mode=contact')) unless length $text;
  unless (ChatLib::rate_ok($s, 'creates')) {
    ChatLib::session_save($s);
    redirect(url('e=ratelimit'));
  }
  ChatLib::session_save($s);
  ChatLib::contact_append({
    ip   => $s->{ip},
    name => ChatLib::clean_text($FORM->{name}, ChatLib::cfg('max_name')),
    addr => ChatLib::clean_text($FORM->{addr}, 100),
    body => $text,
  });
  redirect(url('e=contact'));
}

# ---- ディスパッチ -------------------------------------------------------

sub room_or_die {
  my ($s, $require_member) = @_;
  my $room = ChatLib::room_load($FORM->{room} || '');
  redirect(url('e=noroom')) unless $room;
  if ($require_member && !$s->{rooms}{ $room->{id} }) {
    send_html('チャット',
      '<div class="err">この部屋には入室していません</div>'
      . '[<a href="' . url('') . '" target="_top">TOPへ</a>]');
  }
  return $room;
}

sub main {
  my $s = session();
  my $mode = $FORM->{mode} || '';

  # cronが無い環境向けの確率的GC
  my $p = ChatLib::cfg('gc_probability');
  ChatLib::gc_run() if $p > 0 && int(rand($p)) == 0;

  # POSTでしか受け付けない操作
  # ※create と contact は GET=フォーム表示 / POST=送信 なので含めない
  my %post_only = map { $_ => 1 }
    qw(join say profile pmsay pmblock adminpanel adminact);
  if ($post_only{$mode} && !$IS_POST) {
    send_html('エラー',
      '<div class="err">不正な操作です。</div>[<a href="' . url('') . '">TOPへ戻る</a>]');
  }

  if    ($mode eq 'log')        { page_log($s, room_or_die($s, 1)); }
  elsif ($mode eq 'post')       { page_post($s, room_or_die($s, 1)); }
  elsif ($mode eq 'say')        { do_say($s); }
  elsif ($mode eq 'join')       { do_join($s); }
  elsif ($mode eq 'leave')      { do_leave($s); }
  elsif ($mode eq 'members')    { page_members($s, room_or_die($s, 1)); }
  elsif ($mode eq 'user')       { page_user($s, room_or_die($s, 1)); }
  elsif ($mode eq 'profile')    { do_profile($s); }
  elsif ($mode eq 'create')     { $IS_POST ? do_create($s) : page_create($s); }
  elsif ($mode eq 'pmlist')     { page_pm_list($s); }
  elsif ($mode eq 'pm')         { page_pm($s); }
  elsif ($mode eq 'pmsay')      { do_pm_say($s); }
  elsif ($mode eq 'pmblock')    { do_pm_block($s); }
  elsif ($mode eq 'admin')      { admin_login_page($s, room_or_die($s, 0), ''); }
  elsif ($mode eq 'adminpanel') { do_admin_login($s); }
  elsif ($mode eq 'adminact')   { do_admin_action($s); }
  elsif ($mode eq 'info')       { page_info($s); }
  elsif ($mode eq 'contact')    { $IS_POST ? do_contact($s) : page_contact($s); }
  elsif (defined $FORM->{room} && length $FORM->{room}) {
    my $room = ChatLib::room_load($FORM->{room}) or redirect(url('e=noroom'));
    if ($s->{rooms}{ $room->{id} }) {
      ($FORM->{noframe} || '') eq '1'
        ? page_chat_noframe($s, $room)
        : page_frameset($room);
    } else {
      page_entry($s, $room);
    }
  }
  else { page_top($s); }
}

main();
