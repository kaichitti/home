#!/usr/bin/perl
#
# ぷらチャット - 掃除(GC)スクリプト
#
# 期限切れセッション・放置ユーザーの退室・無人部屋・古い個人チャットを削除する。
# XREA Plus の cron から5分おき程度で実行してください。
#
#   例) */5 * * * * /usr/bin/perl /virtual/<ユーザ名>/public_html/chat-cron/gc.pl
#
# ※cronを使わない場合でも、index.cgi が確率的にGCを実行するため動作します。

use strict;
use warnings;

use FindBin ();
# public_html 配下の ChatLib.pm を読み込む(設置場所に合わせて変更可)
use lib "$FindBin::Bin/../public_html";
use ChatLib;

ChatLib::data_dir();
ChatLib::gc_run();

print "gc done\n" if -t STDOUT;
