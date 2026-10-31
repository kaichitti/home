#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古物台帳管理システム 操作マニュアル PDF生成スクリプト
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
import os

# フォント登録
pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
FONT = 'HeiseiKakuGo-W5'

# カラーパレット
NAVY    = HexColor('#1e3a5f')
ACCENT  = HexColor('#3a7bd5')
GRAY    = HexColor('#6c757d')
LGRAY   = HexColor('#f4f6f9')
BORDER  = HexColor('#dee2e6')
MGRAY   = HexColor('#adb5bd')

PAGE_W, PAGE_H = A4  # 595.27 x 841.89 pt
MARGIN_L = 20 * mm
MARGIN_R = 20 * mm
MARGIN_T = 28 * mm
MARGIN_B = 20 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R


# ============================================================
# ユーティリティ
# ============================================================

def draw_header_footer(c: canvas.Canvas, page_num: int) -> None:
    """全ページ共通ヘッダー・フッター"""
    # ヘッダー右上テキスト
    c.saveState()
    c.setFont(FONT, 8)
    c.setFillColor(GRAY)
    txt = '古物台帳管理システム 操作マニュアル'
    c.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 12 * mm, txt)
    # 区切り線
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(MARGIN_L, PAGE_H - 14 * mm, PAGE_W - MARGIN_R, PAGE_H - 14 * mm)
    # フッターページ番号
    c.line(MARGIN_L, MARGIN_B + 6 * mm, PAGE_W - MARGIN_R, MARGIN_B + 6 * mm)
    c.drawRightString(PAGE_W - MARGIN_R, MARGIN_B + 1 * mm, str(page_num))
    c.restoreState()


def draw_section_title(c: canvas.Canvas, y: float, text: str, size: int = 13) -> float:
    """章タイトル（ネイビー帯付き）を描画して新しいY座標を返す"""
    c.saveState()
    c.setFillColor(NAVY)
    c.rect(MARGIN_L, y - 4, CONTENT_W, 18, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont(FONT, size)
    c.drawString(MARGIN_L + 6, y + 1, text)
    c.restoreState()
    return y - 4 - 10


def draw_sub_title(c: canvas.Canvas, y: float, text: str) -> float:
    """小見出しを描画して新しいY座標を返す"""
    c.saveState()
    c.setFont(FONT, 10)
    c.setFillColor(ACCENT)
    c.drawString(MARGIN_L, y, text)
    c.setStrokeColor(ACCENT)
    c.setLineWidth(0.8)
    c.line(MARGIN_L, y - 2, MARGIN_L + CONTENT_W, y - 2)
    c.restoreState()
    return y - 16


def draw_body(c: canvas.Canvas, y: float, text: str, size: int = 9,
              indent: float = 0, color=None) -> float:
    """本文1行を描画して新しいY座標を返す"""
    c.saveState()
    c.setFont(FONT, size)
    c.setFillColor(color if color else black)
    c.drawString(MARGIN_L + indent, y, text)
    c.restoreState()
    return y - (size + 3)


def draw_bullet(c: canvas.Canvas, y: float, text: str, size: int = 9,
                indent: float = 8) -> float:
    """箇条書き行を描画"""
    c.saveState()
    c.setFillColor(ACCENT)
    c.circle(MARGIN_L + indent + 3, y + 3, 2, fill=1, stroke=0)
    c.setFont(FONT, size)
    c.setFillColor(black)
    c.drawString(MARGIN_L + indent + 10, y, text)
    c.restoreState()
    return y - (size + 4)


def draw_table_row(c: canvas.Canvas, y: float, cols: list, col_widths: list,
                   is_header: bool = False, bg=None) -> float:
    """テーブル行を描画"""
    x = MARGIN_L
    row_h = 16
    c.saveState()
    for i, (text, w) in enumerate(zip(cols, col_widths)):
        fill_color = NAVY if is_header else (bg if bg else white)
        c.setFillColor(fill_color)
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.5)
        c.rect(x, y - row_h + 4, w, row_h, fill=1, stroke=1)
        c.setFont(FONT, 8 if not is_header else 8)
        c.setFillColor(white if is_header else black)
        c.drawString(x + 4, y - row_h + 8, str(text))
        x += w
    c.restoreState()
    return y - row_h


def draw_login_mockup(c: canvas.Canvas, x: float, y: float, w: float = 200, h: float = 140) -> None:
    """ログイン画面モックアップ"""
    c.saveState()
    # 外枠
    c.setStrokeColor(BORDER)
    c.setFillColor(LGRAY)
    c.rect(x, y - h, w, h, fill=1, stroke=1)
    # ヘッダー帯
    c.setFillColor(NAVY)
    c.rect(x, y - 22, w, 22, fill=1, stroke=0)
    c.setFont(FONT, 9)
    c.setFillColor(white)
    c.drawCentredString(x + w / 2, y - 15, '古物台帳管理システム')
    # フォームフィールド
    labels = ['テナントコード', 'メールアドレス', 'パスワード']
    field_y = y - 40
    for label in labels:
        c.setFont(FONT, 7)
        c.setFillColor(black)
        c.drawString(x + 10, field_y, label)
        c.setFillColor(white)
        c.setStrokeColor(BORDER)
        c.rect(x + 75, field_y - 2, w - 85, 13, fill=1, stroke=1)
        field_y -= 22
    # ログインボタン
    btn_y = field_y + 2
    c.setFillColor(ACCENT)
    c.rect(x + w / 2 - 30, btn_y, 60, 14, fill=1, stroke=0)
    c.setFont(FONT, 8)
    c.setFillColor(white)
    c.drawCentredString(x + w / 2, btn_y + 4, 'ログイン')
    c.restoreState()


def draw_dashboard_mockup(c: canvas.Canvas, x: float, y: float, w: float = 320, h: float = 150) -> None:
    """ダッシュボード画面モックアップ"""
    c.saveState()
    # 外枠
    c.setFillColor(LGRAY)
    c.setStrokeColor(BORDER)
    c.rect(x, y - h, w, h, fill=1, stroke=1)
    # ヘッダー帯
    c.setFillColor(NAVY)
    c.rect(x, y - 20, w, 20, fill=1, stroke=0)
    c.setFont(FONT, 8)
    c.setFillColor(white)
    c.drawString(x + 8, y - 14, '古物台帳管理システム')
    # サイドバー
    sb_w = 65
    c.setFillColor(HexColor('#2c4f7c'))
    c.rect(x, y - h, sb_w, h - 20, fill=1, stroke=0)
    sidebar_items = ['ダッシュボード', '台帳登録', '台帳一覧', 'ユーザー管理', '拠点管理', 'アラート']
    item_y = y - 35
    for item in sidebar_items:
        c.setFont(FONT, 6)
        c.setFillColor(HexColor('#a8c4e0'))
        c.drawString(x + 5, item_y, item)
        item_y -= 14
    # メインエリア カード
    card_x = x + sb_w + 8
    card_y = y - 30
    card_w = (w - sb_w - 24) / 2
    # カード1
    c.setFillColor(white)
    c.setStrokeColor(BORDER)
    c.rect(card_x, card_y - 35, card_w, 35, fill=1, stroke=1)
    c.setFillColor(ACCENT)
    c.setFont(FONT, 6)
    c.drawString(card_x + 4, card_y - 12, '今月登録件数')
    c.setFont(FONT, 14)
    c.setFillColor(NAVY)
    c.drawString(card_x + 4, card_y - 28, '42')
    # カード2
    card_x2 = card_x + card_w + 8
    c.setFillColor(white)
    c.setStrokeColor(BORDER)
    c.rect(card_x2, card_y - 35, card_w, 35, fill=1, stroke=1)
    c.setFillColor(HexColor('#dc3545'))
    c.setFont(FONT, 6)
    c.drawString(card_x2 + 4, card_y - 12, '未確認アラート')
    c.setFont(FONT, 14)
    c.setFillColor(HexColor('#dc3545'))
    c.drawString(card_x2 + 4, card_y - 28, '3')
    # 最近の登録リスト
    list_y = card_y - 50
    c.setFillColor(NAVY)
    c.setFont(FONT, 6)
    c.drawString(card_x, list_y, '最近の登録')
    list_y -= 10
    items = ['2026/05/22  山田商店 / カメラ / ¥15,000',
             '2026/05/21  鈴木質屋 / 時計 / ¥32,000',
             '2026/05/20  田中商事 / バッグ / ¥8,500']
    for item in items:
        c.setFillColor(black)
        c.setFont(FONT, 5.5)
        c.drawString(card_x, list_y, item)
        list_y -= 10
    c.restoreState()


def draw_form_mockup(c: canvas.Canvas, x: float, y: float, w: float = 300, h: float = 190) -> None:
    """台帳登録フォームモックアップ"""
    c.saveState()
    c.setFillColor(white)
    c.setStrokeColor(BORDER)
    c.rect(x, y - h, w, h, fill=1, stroke=1)
    # ヘッダー
    c.setFillColor(NAVY)
    c.rect(x, y - 20, w, 20, fill=1, stroke=0)
    c.setFont(FONT, 8)
    c.setFillColor(white)
    c.drawString(x + 8, y - 14, '台帳登録')
    # セクション: 取引情報
    sec_y = y - 32
    c.setFillColor(LGRAY)
    c.rect(x + 4, sec_y - 10, w - 8, 12, fill=1, stroke=0)
    c.setFont(FONT, 7)
    c.setFillColor(NAVY)
    c.drawString(x + 8, sec_y - 7, '取引情報')
    fields_t = [('取引日', True), ('品目名', True), ('取引金額', True), ('取引区分', True)]
    fy = sec_y - 22
    for label, required in fields_t:
        c.setFont(FONT, 6.5)
        c.setFillColor(black)
        c.drawString(x + 8, fy, label)
        if required:
            c.setFillColor(HexColor('#dc3545'))
            c.drawString(x + 8 + 40, fy, '*')
        c.setFillColor(white)
        c.setStrokeColor(BORDER)
        c.rect(x + 55, fy - 2, w - 65, 11, fill=1, stroke=1)
        fy -= 16
    # セクション: 相手方情報
    c.setFillColor(LGRAY)
    c.rect(x + 4, fy - 8, w - 8, 12, fill=1, stroke=0)
    c.setFont(FONT, 7)
    c.setFillColor(NAVY)
    c.drawString(x + 8, fy - 5, '相手方情報')
    fy -= 22
    fields_p = [('氏名', True), ('住所', True), ('電話番号', False)]
    for label, required in fields_p:
        c.setFont(FONT, 6.5)
        c.setFillColor(black)
        c.drawString(x + 8, fy, label)
        if required:
            c.setFillColor(HexColor('#dc3545'))
            c.drawString(x + 8 + 40, fy, '*')
        c.setFillColor(white)
        c.setStrokeColor(BORDER)
        c.rect(x + 55, fy - 2, w - 65, 11, fill=1, stroke=1)
        fy -= 16
    # 登録ボタン
    btn_y = y - h + 10
    c.setFillColor(ACCENT)
    c.rect(x + w / 2 - 35, btn_y, 70, 14, fill=1, stroke=0)
    c.setFont(FONT, 8)
    c.setFillColor(white)
    c.drawCentredString(x + w / 2, btn_y + 4, '登録する')
    c.restoreState()


def draw_list_mockup(c: canvas.Canvas, x: float, y: float, w: float = 320, h: float = 130) -> None:
    """台帳一覧モックアップ"""
    c.saveState()
    c.setFillColor(white)
    c.setStrokeColor(BORDER)
    c.rect(x, y - h, w, h, fill=1, stroke=1)
    # ヘッダー
    c.setFillColor(NAVY)
    c.rect(x, y - 18, w, 18, fill=1, stroke=0)
    c.setFont(FONT, 8)
    c.setFillColor(white)
    c.drawString(x + 8, y - 12, '台帳一覧')
    # 検索バー
    c.setFillColor(LGRAY)
    c.rect(x + 4, y - 36, w - 70, 14, fill=1, stroke=1)
    c.setFont(FONT, 6.5)
    c.setFillColor(GRAY)
    c.drawString(x + 8, y - 30, 'キーワード・日付・品目で絞り込み...')
    c.setFillColor(ACCENT)
    c.rect(x + w - 62, y - 36, 58, 14, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont(FONT, 7)
    c.drawCentredString(x + w - 33, y - 29, '検索')
    # テーブルヘッダー
    cols = ['取引日', '品目名', '相手方', '金額', '登録者']
    col_ws = [50, 80, 70, 50, 60]
    th_y = y - 50
    cx = x + 4
    for col, cw in zip(cols, col_ws):
        c.setFillColor(NAVY)
        c.setStrokeColor(BORDER)
        c.rect(cx, th_y - 12, cw, 12, fill=1, stroke=1)
        c.setFont(FONT, 6)
        c.setFillColor(white)
        c.drawString(cx + 3, th_y - 9, col)
        cx += cw
    # テーブル行
    rows = [
        ['2026/05/22', 'デジタルカメラ', '山田 太郎', '¥15,000', '田中'],
        ['2026/05/21', '腕時計', '鈴木 一郎', '¥32,000', '田中'],
        ['2026/05/20', 'ブランドバッグ', '佐藤 花子', '¥8,500', '山本'],
        ['2026/05/19', 'スマートフォン', '高橋 次郎', '¥25,000', '田中'],
    ]
    row_y = th_y - 12
    for ri, row in enumerate(rows):
        bg = LGRAY if ri % 2 == 0 else white
        cx = x + 4
        for val, cw in zip(row, col_ws):
            c.setFillColor(bg)
            c.setStrokeColor(BORDER)
            c.rect(cx, row_y - 11, cw, 11, fill=1, stroke=1)
            c.setFont(FONT, 5.5)
            c.setFillColor(black)
            c.drawString(cx + 3, row_y - 8, val)
            cx += cw
        row_y -= 11
    # ページネーション
    c.setFont(FONT, 6)
    c.setFillColor(GRAY)
    c.drawString(x + 4, y - h + 6, '全 42 件   1 / 5 ページ')
    c.restoreState()


def draw_user_list_mockup(c: canvas.Canvas, x: float, y: float, w: float = 300, h: float = 110) -> None:
    """ユーザー一覧モックアップ"""
    c.saveState()
    c.setFillColor(white)
    c.setStrokeColor(BORDER)
    c.rect(x, y - h, w, h, fill=1, stroke=1)
    c.setFillColor(NAVY)
    c.rect(x, y - 18, w, 18, fill=1, stroke=0)
    c.setFont(FONT, 8)
    c.setFillColor(white)
    c.drawString(x + 8, y - 12, 'ユーザー管理')
    # 追加ボタン
    c.setFillColor(ACCENT)
    c.rect(x + w - 65, y - 16, 60, 12, fill=1, stroke=0)
    c.setFont(FONT, 6.5)
    c.drawString(x + w - 60, y - 11, '+ ユーザー追加')
    # テーブルヘッダー
    cols = ['氏名', 'メールアドレス', '権限', '拠点', '状態']
    col_ws = [55, 85, 45, 55, 55]
    th_y = y - 32
    cx = x + 4
    for col, cw in zip(cols, col_ws):
        c.setFillColor(NAVY)
        c.setStrokeColor(BORDER)
        c.rect(cx, th_y - 12, cw, 12, fill=1, stroke=1)
        c.setFont(FONT, 6)
        c.setFillColor(white)
        c.drawString(cx + 3, th_y - 9, col)
        cx += cw
    # テーブル行
    rows = [
        ['田中 一郎', 'tanaka@example.com', '管理者', '本店', '有効'],
        ['山本 花子', 'yamamoto@example.com', '一般', '本店', '有効'],
        ['鈴木 次郎', 'suzuki@example.com', '一般', '支店A', '無効'],
    ]
    row_y = th_y - 12
    for ri, row in enumerate(rows):
        bg = LGRAY if ri % 2 == 0 else white
        cx = x + 4
        for val, cw in zip(row, col_ws):
            c.setFillColor(bg)
            c.setStrokeColor(BORDER)
            c.rect(cx, row_y - 11, cw, 11, fill=1, stroke=1)
            c.setFont(FONT, 5.5)
            c.setFillColor(HexColor('#dc3545') if val == '無効' else black)
            c.drawString(cx + 3, row_y - 8, val)
            cx += cw
        row_y -= 11
    c.restoreState()


# ============================================================
# 各ページ描画
# ============================================================

def draw_cover(c: canvas.Canvas) -> None:
    """表紙"""
    # 背景
    c.setFillColor(LGRAY)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # 上部ネイビー帯
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 180, PAGE_W, 180, fill=1, stroke=0)
    # アクセントライン
    c.setFillColor(ACCENT)
    c.rect(0, PAGE_H - 185, PAGE_W, 5, fill=1, stroke=0)
    # タイトル
    c.setFillColor(white)
    c.setFont(FONT, 28)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 100, '古物台帳管理システム')
    c.setFont(FONT, 14)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 130, '操作マニュアル  v1.0')
    # 下部デザイン帯
    c.setFillColor(NAVY)
    c.rect(0, 0, PAGE_W, 80, fill=1, stroke=0)
    c.setFillColor(ACCENT)
    c.rect(0, 80, PAGE_W, 4, fill=1, stroke=0)
    # 日付
    c.setFillColor(white)
    c.setFont(FONT, 11)
    c.drawCentredString(PAGE_W / 2, 40, '2026年5月')
    # 中央ロゴ風テキスト
    c.setFillColor(NAVY)
    c.setFont(FONT, 13)
    c.drawCentredString(PAGE_W / 2, PAGE_H / 2 + 30, '古物営業法に基づく')
    c.setFont(FONT, 11)
    c.setFillColor(GRAY)
    c.drawCentredString(PAGE_W / 2, PAGE_H / 2, 'デジタル台帳管理・監査ログ・アラート検知を統合した')
    c.drawCentredString(PAGE_W / 2, PAGE_H / 2 - 20, 'マルチテナント対応クラウド管理システム')
    # 区切り線
    c.setStrokeColor(ACCENT)
    c.setLineWidth(1.5)
    c.line(MARGIN_L * 2, PAGE_H / 2 + 50, PAGE_W - MARGIN_L * 2, PAGE_H / 2 + 50)
    c.line(MARGIN_L * 2, PAGE_H / 2 - 40, PAGE_W - MARGIN_L * 2, PAGE_H / 2 - 40)


def draw_toc(c: canvas.Canvas, page_num: int) -> None:
    """目次"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '目次', 14)
    y -= 12
    chapters = [
        ('第1章', 'システム概要', 3),
        ('第2章', 'ログイン・初期設定', 4),
        ('第3章', 'ダッシュボード', 6),
        ('第4章', '台帳登録', 7),
        ('第5章', '台帳一覧・検索', 9),
        ('第6章', '台帳詳細・編集・削除', 10),
        ('第7章', 'ユーザー管理【管理者向け】', 11),
        ('第8章', '拠点管理【管理者向け】', 12),
        ('第9章', 'アラート管理【管理者向け】', 13),
        ('第10章', '監査ログ【管理者向け】', 14),
        ('第11章', 'CSV・PDF出力', 15),
        ('第12章', '年度別データ管理', 16),
        ('第13章', 'セキュリティ・注意事項', 17),
        ('第14章', 'システム管理者機能【システム管理者専用】', 18),
        ('第15章', 'FAQ・トラブルシューティング', 19),
    ]
    for i, (num, title, pg) in enumerate(chapters):
        row_y = y
        bg = LGRAY if i % 2 == 0 else white
        c.setFillColor(bg)
        c.rect(MARGIN_L, row_y - 14, CONTENT_W, 16, fill=1, stroke=0)
        c.setFont(FONT, 9)
        c.setFillColor(NAVY)
        c.drawString(MARGIN_L + 6, row_y - 8, num)
        c.setFillColor(black)
        c.drawString(MARGIN_L + 55, row_y - 8, title)
        c.setFillColor(GRAY)
        c.drawRightString(MARGIN_L + CONTENT_W - 6, row_y - 8, f'P.{pg}')
        # ドット
        c.setStrokeColor(MGRAY)
        c.setLineWidth(0.3)
        c.setDash(1, 4)
        c.line(MARGIN_L + 55 + c.stringWidth(title, FONT, 9) + 5,
               row_y - 6,
               MARGIN_L + CONTENT_W - 30,
               row_y - 6)
        c.setDash()
        y -= 17
    y -= 10
    c.setFont(FONT, 8)
    c.setFillColor(GRAY)
    c.drawString(MARGIN_L, y, '※ ページ番号はPDF内のページ番号です。')


def draw_ch1(c: canvas.Canvas, page_num: int) -> None:
    """第1章: システム概要"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第1章   システム概要')
    y -= 10

    y = draw_sub_title(c, y, 'システムの目的')
    y -= 4
    desc = [
        '本システムは、古物営業法に基づく古物台帳の記録・管理をデジタル化するクラウド型管理システムです。',
        '紙台帳に代わるデジタル記録により、検索・閲覧・監査対応を効率化し、法令遵守をサポートします。',
    ]
    for d in desc:
        y = draw_body(c, y, d, size=9)
    y -= 8

    y = draw_sub_title(c, y, '対象ユーザー')
    y -= 4
    bullets = [
        '古物商許可を受けた事業者（質屋・リサイクルショップ・中古品販売業者 等）',
        '複数拠点を持つ事業者（マルチテナント対応）',
        '管理者・一般スタッフが分担して台帳を入力・管理する組織',
    ]
    for b in bullets:
        y = draw_bullet(c, y, b)
    y -= 12

    y = draw_sub_title(c, y, '権限レベル')
    y -= 6
    # 権限テーブル
    headers = ['権限', '対象', '主な操作範囲']
    col_ws = [90, 120, CONTENT_W - 210]
    y = draw_table_row(c, y, headers, col_ws, is_header=True)
    rows = [
        ['システム管理者', 'サービス運営者', 'テナント管理・全テナント横断ログ閲覧'],
        ['テナント管理者', '事業者の管理担当者', 'ユーザー管理・拠点管理・全台帳閲覧・アラート処理'],
        ['一般ユーザー', '店舗スタッフ等', '台帳登録・自分の入力データ編集・閲覧'],
    ]
    for i, row in enumerate(rows):
        bg = LGRAY if i % 2 == 0 else white
        y = draw_table_row(c, y, row, col_ws, bg=bg)
    y -= 14

    y = draw_sub_title(c, y, 'アクセスURL')
    y -= 6
    c.setFont(FONT, 9)
    c.setFillColor(black)
    c.drawString(MARGIN_L, y, 'テナント向け（一般・管理者）:')
    c.setFillColor(ACCENT)
    c.drawString(MARGIN_L + 145, y, 'https://kottai-dacho.example.com/login')
    y -= 16
    c.setFillColor(black)
    c.drawString(MARGIN_L, y, 'システム管理者向け:')
    c.setFillColor(ACCENT)
    c.drawString(MARGIN_L + 145, y, 'https://kottai-dacho.example.com/admin/login')
    y -= 20

    # 注意ボックス
    c.setFillColor(HexColor('#fff3cd'))
    c.setStrokeColor(HexColor('#ffc107'))
    c.setLineWidth(1)
    c.rect(MARGIN_L, y - 30, CONTENT_W, 34, fill=1, stroke=1)
    c.setFont(FONT, 8.5)
    c.setFillColor(HexColor('#856404'))
    c.drawString(MARGIN_L + 8, y - 10, '注意: URLはご契約時にお知らせしたものをご利用ください。')
    c.drawString(MARGIN_L + 8, y - 24, 'ブックマーク登録を推奨します。')


def draw_ch2(c: canvas.Canvas, page_num: int) -> None:
    """第2章: ログイン・初期設定"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第2章   ログイン・初期設定')
    y -= 10

    y = draw_sub_title(c, y, 'ログイン画面')
    y -= 8

    # モックアップ（左）
    mock_x = MARGIN_L + 10
    mock_y = y - 5
    draw_login_mockup(c, mock_x, mock_y, w=210, h=145)

    # 右側説明
    desc_x = MARGIN_L + 235
    dy = mock_y - 10
    c.setFont(FONT, 9)
    c.setFillColor(NAVY)
    c.drawString(desc_x, dy, 'ログイン手順')
    dy -= 14
    steps = [
        '1. テナントコードを入力',
        '2. 登録メールアドレスを入力',
        '3. パスワードを入力',
        '4. 「ログイン」ボタンをクリック',
    ]
    for step in steps:
        c.setFont(FONT, 8.5)
        c.setFillColor(black)
        c.drawString(desc_x, dy, step)
        dy -= 13

    y = mock_y - 145 - 14

    y = draw_sub_title(c, y, 'ログイン手順の詳細説明')
    y -= 6
    items = [
        ('テナントコード', '契約時に発行される識別コードです。半角英数字で入力してください。'),
        ('メールアドレス', '管理者から付与されたメールアドレスを入力します。'),
        ('パスワード', '初回は管理者から伝えられた初期パスワードでログインし、すぐに変更します。'),
    ]
    for label, desc in items:
        c.setFillColor(ACCENT)
        c.setFont(FONT, 9)
        c.drawString(MARGIN_L + 4, y, f'- {label}:')
        c.setFillColor(black)
        c.setFont(FONT, 8.5)
        c.drawString(MARGIN_L + 80, y, desc)
        y -= 14
    y -= 8

    y = draw_sub_title(c, y, '初回ログイン時のパスワード変更')
    y -= 6
    flow = [
        '初期（仮）パスワードでログイン',
        'パスワード変更画面に自動遷移',
        '新パスワードを2回入力して確定',
        'ダッシュボードへ遷移',
    ]
    fx = MARGIN_L + 10
    for i, step in enumerate(flow):
        # 丸番号
        c.setFillColor(ACCENT)
        c.circle(fx, y + 4, 8, fill=1, stroke=0)
        c.setFont(FONT, 7)
        c.setFillColor(white)
        c.drawCentredString(fx, y + 1, str(i + 1))
        c.setFont(FONT, 9)
        c.setFillColor(black)
        c.drawString(fx + 14, y, step)
        if i < len(flow) - 1:
            c.setStrokeColor(ACCENT)
            c.setLineWidth(1)
            c.line(fx, y - 2, fx, y - 10)
        y -= 18
    y -= 8

    y = draw_sub_title(c, y, 'パスワードポリシー')
    y -= 6
    policy = [
        '英字と数字をそれぞれ1文字以上含めること',
        '8文字以上であること',
        '現在と同じパスワード・初期パスワード（Admin7777）は使用不可',
        'ログイン失敗5回でアカウントが30分ロックされます',
    ]
    for p in policy:
        y = draw_bullet(c, y, p, size=8.5)


def draw_ch3(c: canvas.Canvas, page_num: int) -> None:
    """第3章: ダッシュボード"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第3章   ダッシュボード')
    y -= 10

    y = draw_sub_title(c, y, 'ダッシュボード画面')
    y -= 8

    draw_dashboard_mockup(c, MARGIN_L + 10, y - 5, w=340, h=155)
    y -= 165

    y = draw_sub_title(c, y, '各エリアの説明')
    y -= 6
    items = [
        ('左サイドバー', 'メインメニューを表示します。クリックして各機能へ移動します。'),
        ('今月登録件数', '当月（毎月1日リセット）の台帳登録件数を表示します。'),
        ('未確認アラート', '重複検知等のアラートのうち未処理件数を表示します（赤色）。'),
        ('最近の登録', '自分が登録した直近5件の台帳データを表示します。'),
    ]
    for label, desc in items:
        c.setFillColor(ACCENT)
        c.setFont(FONT, 9)
        c.drawString(MARGIN_L + 4, y, f'- {label}:')
        c.setFillColor(black)
        c.setFont(FONT, 8.5)
        c.drawString(MARGIN_L + 80, y, desc)
        y -= 14
    y -= 8

    y = draw_sub_title(c, y, 'ナビゲーション')
    y -= 6
    nav_items = [
        'ダッシュボード: トップページ',
        '台帳登録: 新規台帳の入力フォームへ',
        '台帳一覧: 登録済み台帳の検索・閲覧',
        'ユーザー管理: アカウント管理（管理者のみ表示）',
        '拠点管理: 拠点の追加・編集（管理者のみ表示）',
        'アラート管理: 重複検知アラートの処理（管理者のみ表示）',
        '監査ログ: 操作履歴の閲覧（管理者のみ表示）',
    ]
    for item in nav_items:
        y = draw_bullet(c, y, item, size=8.5)


def draw_ch4(c: canvas.Canvas, page_num: int) -> None:
    """第4章: 台帳登録 (ページ1)"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第4章   台帳登録')
    y -= 10

    y = draw_sub_title(c, y, '登録フォーム画面')
    y -= 8

    draw_form_mockup(c, MARGIN_L + 10, y - 5, w=310, h=195)
    y -= 205

    y = draw_sub_title(c, y, '入力項目一覧（取引情報・相手方情報）')
    y -= 6
    headers = ['項目名', '必須/任意', '形式・備考']
    col_ws = [100, 60, CONTENT_W - 160]
    y = draw_table_row(c, y, headers, col_ws, is_header=True)
    rows = [
        ['取引日', '必須', 'YYYY/MM/DD形式、カレンダーから選択可'],
        ['品目名', '必須', '最大100文字'],
        ['取引区分', '必須', '買取・売却・交換から選択'],
        ['取引金額', '必須', '半角数字（税込）'],
        ['品目説明', '任意', '最大500文字、商品の状態・特徴を記入'],
        ['氏名（相手方）', '必須', '最大50文字'],
        ['住所（相手方）', '必須', '最大200文字'],
        ['電話番号', '任意', 'ハイフンなし11桁'],
    ]
    for i, row in enumerate(rows):
        bg = LGRAY if i % 2 == 0 else white
        y = draw_table_row(c, y, row, col_ws, bg=bg)


def draw_ch4_p2(c: canvas.Canvas, page_num: int) -> None:
    """第4章: 台帳登録 (ページ2)"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第4章   台帳登録（続き）')
    y -= 10

    y = draw_sub_title(c, y, '入力項目一覧（本人確認・ファイル）')
    y -= 6
    headers = ['項目名', '必須/任意', '形式・備考']
    col_ws = [100, 60, CONTENT_W - 160]
    y = draw_table_row(c, y, headers, col_ws, is_header=True)
    rows = [
        ['本人確認書類種別', '必須', '運転免許証・マイナンバーカード等から選択'],
        ['証明書番号', '任意', '最大30文字'],
        ['発行機関', '任意', '最大50文字'],
        ['有効期限', '任意', 'YYYY/MM/DD形式'],
        ['添付ファイル', '任意', '本人確認書類・写真等をアップロード'],
        ['備考', '任意', '社内メモ用（最大500文字）'],
    ]
    for i, row in enumerate(rows):
        bg = LGRAY if i % 2 == 0 else white
        y = draw_table_row(c, y, row, col_ws, bg=bg)
    y -= 14

    y = draw_sub_title(c, y, 'ファイルアップロードについて')
    y -= 6
    file_items = [
        '1レコードにつき複数ファイルをアップロード可能',
        '対応形式: JPEG / PNG / PDF / HEIC',
        '1ファイルの上限サイズ: 50MB',
        'アップロード後はサムネイル表示で確認可能',
        'ファイルは削除ボタンで個別削除できます（管理者権限）',
    ]
    for item in file_items:
        y = draw_bullet(c, y, item, size=8.5)
    y -= 10

    y = draw_sub_title(c, y, '登録後の動作')
    y -= 6
    steps = [
        '「登録する」ボタンクリック後、確認ダイアログが表示されます。',
        '「確定」をクリックすると台帳データが保存されます。',
        '重複検知システムが自動で同一条件のデータを確認し、一致する場合はアラートを発生させます。',
        '登録完了後、台帳一覧画面に遷移します。',
    ]
    for step in steps:
        y = draw_body(c, y, step, size=8.5, indent=4)
    y -= 12

    # 注意ボックス
    c.setFillColor(HexColor('#d4edda'))
    c.setStrokeColor(HexColor('#28a745'))
    c.rect(MARGIN_L, y - 38, CONTENT_W, 42, fill=1, stroke=1)
    c.setFont(FONT, 8.5)
    c.setFillColor(HexColor('#155724'))
    c.drawString(MARGIN_L + 8, y - 12, 'ポイント: 必須項目（*マーク）を全て入力しないと登録できません。')
    c.drawString(MARGIN_L + 8, y - 26, '入力エラーは項目直下に赤文字で表示されます。内容を確認して修正してください。')


def draw_ch5(c: canvas.Canvas, page_num: int) -> None:
    """第5章: 台帳一覧・検索"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第5章   台帳一覧・検索')
    y -= 10

    y = draw_sub_title(c, y, '台帳一覧画面')
    y -= 8

    draw_list_mockup(c, MARGIN_L + 10, y - 5, w=340, h=135)
    y -= 150

    y = draw_sub_title(c, y, '検索条件（8種類の絞り込み）')
    y -= 6
    headers = ['検索条件', '説明']
    col_ws = [120, CONTENT_W - 120]
    y = draw_table_row(c, y, headers, col_ws, is_header=True)
    rows = [
        ['キーワード', '品目名・相手方氏名・備考を横断検索'],
        ['取引日（開始）', '指定日以降の台帳を絞り込み'],
        ['取引日（終了）', '指定日以前の台帳を絞り込み'],
        ['品目区分', 'プルダウンから選択（カメラ・時計・貴金属 等）'],
        ['取引区分', '買取・売却・交換から選択'],
        ['登録者', '特定ユーザーが登録したデータを絞り込み（管理者のみ）'],
        ['拠点', '特定拠点のデータを絞り込み（管理者のみ）'],
        ['年度', '対象年度（4月始まり）を選択'],
    ]
    for i, row in enumerate(rows):
        bg = LGRAY if i % 2 == 0 else white
        y = draw_table_row(c, y, row, col_ws, bg=bg)
    y -= 12

    y = draw_sub_title(c, y, 'ページネーションと件数表示')
    y -= 6
    items = [
        '1ページあたり20件表示（デフォルト）',
        '画面下部に「全X件 / Yページ中 Zページ目」を表示',
        '「前へ」「次へ」ボタン、またはページ番号直接入力で移動可能',
        '検索条件はURLパラメータに保持されるためブックマーク・共有が可能',
    ]
    for item in items:
        y = draw_bullet(c, y, item, size=8.5)


def draw_ch6(c: canvas.Canvas, page_num: int) -> None:
    """第6章: 台帳詳細・編集・削除"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第6章   台帳詳細・編集・削除')
    y -= 10

    y = draw_sub_title(c, y, '詳細画面の見方')
    y -= 6
    items = [
        '台帳一覧の各行をクリックすると詳細画面に遷移します。',
        '登録されたすべての項目と添付ファイルのサムネイルが表示されます。',
        '「編集」「削除」ボタンは権限に応じて表示・非表示が切り替わります。',
    ]
    for item in items:
        y = draw_body(c, y, item, size=8.5, indent=4)
    y -= 10

    y = draw_sub_title(c, y, '編集権限')
    y -= 6
    headers = ['権限', '編集可能な台帳']
    col_ws = [110, CONTENT_W - 110]
    y = draw_table_row(c, y, headers, col_ws, is_header=True)
    rows = [
        ['一般ユーザー', '自分が登録した当年度データのみ'],
        ['テナント管理者', '自テナントの当年度データ全件'],
        ['システム管理者', '全テナントの全データ（原則操作しない）'],
    ]
    for i, row in enumerate(rows):
        bg = LGRAY if i % 2 == 0 else white
        y = draw_table_row(c, y, row, col_ws, bg=bg)
    y -= 14

    y = draw_sub_title(c, y, '過去年度データの制限')
    y -= 6
    c.setFillColor(HexColor('#fff3cd'))
    c.setStrokeColor(HexColor('#ffc107'))
    c.rect(MARGIN_L, y - 42, CONTENT_W, 46, fill=1, stroke=1)
    c.setFont(FONT, 8.5)
    c.setFillColor(HexColor('#856404'))
    c.drawString(MARGIN_L + 8, y - 12, '過去年度（当年度より前）のデータは閲覧・CSV/PDF出力のみ可能です。')
    c.drawString(MARGIN_L + 8, y - 26, '編集・削除ボタンは表示されません。')
    c.drawString(MARGIN_L + 8, y - 40, '法令遵守のため、このルールは変更できません。')
    y -= 58

    y = draw_sub_title(c, y, '削除操作（管理者のみ）')
    y -= 6
    del_steps = [
        '詳細画面の「削除」ボタン（赤色）をクリック',
        '確認ダイアログでパスワードを再入力',
        '「削除する」をクリックすると台帳が削除されます（削除前の内容は監査ログに残ります）',
        '削除操作は監査ログに記録されます',
        '削除後の復元はできません。十分に確認してから操作してください。',
    ]
    for i, step in enumerate(del_steps):
        c.setFont(FONT, 8.5)
        c.setFillColor(black)
        c.drawString(MARGIN_L + 4, y, f'{i + 1}. {step}')
        y -= 13


def draw_ch7(c: canvas.Canvas, page_num: int) -> None:
    """第7章: ユーザー管理"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第7章   ユーザー管理【テナント管理者向け】')
    y -= 10

    y = draw_sub_title(c, y, 'ユーザー一覧画面')
    y -= 8

    draw_user_list_mockup(c, MARGIN_L + 10, y - 5, w=320, h=115)
    y -= 128

    y = draw_sub_title(c, y, 'ユーザーの追加')
    y -= 6
    add_steps = [
        '「+ ユーザー追加」ボタンをクリック',
        '氏名・メールアドレス・権限・所属拠点を入力',
        '初期パスワードを入力して「登録」をクリックし、そのパスワードを本人に伝えます',
        '新規ユーザーは初回ログイン時にパスワード変更が必要です',
    ]
    for i, step in enumerate(add_steps):
        y = draw_body(c, y, f'{i + 1}. {step}', size=8.5, indent=4)
    y -= 10

    y = draw_sub_title(c, y, 'ユーザーの編集')
    y -= 6
    edit_items = [
        '一覧の「編集」ボタンをクリックして氏名・権限・拠点を変更可能',
        'メールアドレスはログインIDです。変更すると次回から新しいアドレスでログインします',
        'パスワード再設定: 編集画面の「パスワードの再設定」で仮パスワードを設定（ロックも解除）',
    ]
    for item in edit_items:
        y = draw_bullet(c, y, item, size=8.5)
    y -= 10

    y = draw_sub_title(c, y, 'ユーザーの無効化')
    y -= 6
    disable_items = [
        '退職・異動時は「無効化」ボタンをクリックしてアクセスを停止します',
        '無効化したユーザーはログインできなくなります（データは保持）',
        '再度「有効化」することで復活させることができます',
        '台帳の登録記録があるユーザーは削除できません（登録者情報を保全するため。無効化を使用）',
    ]
    for item in disable_items:
        y = draw_bullet(c, y, item, size=8.5)
    y -= 10

    y = draw_sub_title(c, y, '権限・拠点の設定')
    y -= 6
    auth_items = [
        '権限: 「テナント管理者」または「一般ユーザー」から選択',
        '拠点: 登録済みの拠点から1つ選択（拠点管理で事前登録が必要）',
        '管理者は全拠点のデータを閲覧・操作できます',
        '一般ユーザーは自分の所属拠点のデータのみ閲覧できます',
    ]
    for item in auth_items:
        y = draw_bullet(c, y, item, size=8.5)


def draw_ch8(c: canvas.Canvas, page_num: int) -> None:
    """第8章: 拠点管理"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第8章   拠点管理【テナント管理者向け】')
    y -= 10

    y = draw_sub_title(c, y, '拠点管理の概要')
    y -= 6
    overview = [
        '拠点（店舗・営業所）を登録し、ユーザーと台帳データを拠点単位で管理します。',
        '拠点管理画面はサイドバーの「拠点管理」からアクセスします。',
    ]
    for item in overview:
        y = draw_body(c, y, item, size=8.5, indent=4)
    y -= 10

    y = draw_sub_title(c, y, '拠点の追加')
    y -= 6
    headers = ['項目', '必須/任意', '説明']
    col_ws = [80, 60, CONTENT_W - 140]
    y = draw_table_row(c, y, headers, col_ws, is_header=True)
    rows = [
        ['拠点名', '必須', '最大50文字（例: 本店、渋谷支店）'],
        ['住所', '任意', '拠点の所在地'],
        ['電話番号', '任意', '拠点の代表番号'],
        ['備考', '任意', '内部メモ（最大200文字）'],
    ]
    for i, row in enumerate(rows):
        bg = LGRAY if i % 2 == 0 else white
        y = draw_table_row(c, y, row, col_ws, bg=bg)
    y -= 14

    y = draw_sub_title(c, y, '拠点の編集・削除')
    y -= 6
    edit_items = [
        '一覧の「編集」ボタンから拠点名・住所・電話番号を変更できます',
        '「削除」ボタンは所属ユーザーがいない拠点のみ表示されます',
        '所属ユーザーがいる場合は先にユーザーを別拠点へ移動してください',
        '台帳データが存在する拠点は削除できません（データの整合性を保持）',
    ]
    for item in edit_items:
        y = draw_bullet(c, y, item, size=8.5)
    y -= 12

    # 注意ボックス
    c.setFillColor(HexColor('#f8d7da'))
    c.setStrokeColor(HexColor('#dc3545'))
    c.rect(MARGIN_L, y - 42, CONTENT_W, 46, fill=1, stroke=1)
    c.setFont(FONT, 8.5)
    c.setFillColor(HexColor('#721c24'))
    c.drawString(MARGIN_L + 8, y - 12, '注意: 拠点を削除するとその拠点に紐づく設定が全て失われます。')
    c.drawString(MARGIN_L + 8, y - 26, '削除前に所属ユーザーを別拠点へ移動し、台帳データがないことを確認してください。')


def draw_ch9(c: canvas.Canvas, page_num: int) -> None:
    """第9章: アラート管理"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第9章   アラート管理【テナント管理者向け】')
    y -= 10

    y = draw_sub_title(c, y, '重複検知の仕組み')
    y -= 6
    desc = [
        '台帳登録時、システムが自動で以下の条件を照合し、完全一致するデータが存在する場合にアラートを発生させます。',
    ]
    for d in desc:
        y = draw_body(c, y, d, size=8.5, indent=4)
    y -= 8

    # 検知条件ボックス
    c.setFillColor(LGRAY)
    c.setStrokeColor(BORDER)
    c.rect(MARGIN_L + 20, y - 50, CONTENT_W - 40, 54, fill=1, stroke=1)
    c.setFont(FONT, 9)
    c.setFillColor(NAVY)
    c.drawCentredString(PAGE_W / 2, y - 12, '重複検知条件（以下の3項目が全て一致）')
    cond_items = ['品目名', '取引金額（税込）', 'ファイル保存日時（撮影日時）']
    cy = y - 26
    for item in cond_items:
        c.setFillColor(ACCENT)
        c.circle(MARGIN_L + 35, cy + 4, 3, fill=1, stroke=0)
        c.setFillColor(black)
        c.setFont(FONT, 9)
        c.drawString(MARGIN_L + 44, cy, item)
        cy -= 14
    y -= 62

    y = draw_sub_title(c, y, 'アラートの確認手順')
    y -= 6
    steps = [
        'ダッシュボードの「未確認アラート」件数をクリック、またはサイドバーの「アラート管理」へ',
        'アラート一覧が表示されます。各行をクリックして詳細を確認します',
        '重複が本物か（誤入力・重複登録）、問題ないか（別人の同一取引）を判断します',
        '判断後「確認済み」または「誤登録として削除」ボタンをクリックして処理します',
        '処理したアラートは「処理済み」タブに移動し、監査ログに記録されます',
    ]
    for i, step in enumerate(steps):
        y = draw_body(c, y, f'{i + 1}. {step}', size=8.5, indent=4)
    y -= 10

    y = draw_sub_title(c, y, 'アラートの処理結果')
    y -= 6
    headers = ['処理', '説明']
    col_ws = [90, CONTENT_W - 90]
    y = draw_table_row(c, y, headers, col_ws, is_header=True)
    rows = [
        ['確認済み', '重複でないと判断。アラートを閉じて台帳データは保持'],
        ['誤登録として削除', '重複と判断。後から登録された台帳データを削除'],
    ]
    for i, row in enumerate(rows):
        bg = LGRAY if i % 2 == 0 else white
        y = draw_table_row(c, y, row, col_ws, bg=bg)


def draw_ch10(c: canvas.Canvas, page_num: int) -> None:
    """第10章: 監査ログ"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第10章   監査ログ【テナント管理者向け】')
    y -= 10

    y = draw_sub_title(c, y, '監査ログとは')
    y -= 6
    desc = '監査ログは、システム上で行われた全操作を自動記録したものです。法令対応・不正防止・トラブル調査に活用します。'
    y = draw_body(c, y, desc, size=8.5, indent=4)
    y -= 10

    y = draw_sub_title(c, y, '記録される操作種別')
    y -= 6
    headers = ['操作種別', '記録内容']
    col_ws = [100, CONTENT_W - 100]
    y = draw_table_row(c, y, headers, col_ws, is_header=True)
    rows = [
        ['ログイン・ログアウト', '日時・ユーザー・IPアドレス'],
        ['台帳登録', '登録日時・ユーザー・台帳ID・データ概要'],
        ['台帳編集', '編集日時・ユーザー・台帳ID・変更前後の値'],
        ['台帳削除', '削除日時・ユーザー・台帳ID（復元不可の警告付き）'],
        ['ユーザー追加・編集・無効化', '操作日時・実行者・対象ユーザー'],
        ['アラート処理', '処理日時・処理者・処理結果'],
        ['CSV/PDF出力', '出力日時・ユーザー・絞り込み条件'],
    ]
    for i, row in enumerate(rows):
        bg = LGRAY if i % 2 == 0 else white
        y = draw_table_row(c, y, row, col_ws, bg=bg)
    y -= 14

    y = draw_sub_title(c, y, '監査ログの特性')
    y -= 6
    log_items = [
        '監査ログは編集・削除ができません（改ざん防止）',
        'テナント管理者は自テナントのログのみ閲覧できます',
        'システム管理者は全テナントのログを横断閲覧できます',
        'ログはCSV形式でエクスポート可能です',
        '保存期間: 最低5年間（法令要件に準拠）',
    ]
    for item in log_items:
        y = draw_bullet(c, y, item, size=8.5)
    y -= 10

    y = draw_sub_title(c, y, '監査ログの閲覧方法')
    y -= 6
    view_steps = [
        'サイドバーの「監査ログ」をクリック',
        '日付範囲・操作種別・ユーザーで絞り込み可能',
        '各行をクリックして詳細情報を確認',
        'CSVエクスポートボタンで全件ダウンロード可能',
    ]
    for i, step in enumerate(view_steps):
        y = draw_body(c, y, f'{i + 1}. {step}', size=8.5, indent=4)


def draw_ch11(c: canvas.Canvas, page_num: int) -> None:
    """第11章: CSV・PDF出力"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第11章   CSV・PDF出力')
    y -= 10

    y = draw_sub_title(c, y, '出力機能の概要')
    y -= 6
    desc = '台帳一覧画面の検索結果をCSVまたはPDFとして出力できます。帳票作成・外部提出・バックアップに活用してください。'
    y = draw_body(c, y, desc, size=8.5, indent=4)
    y -= 10

    y = draw_sub_title(c, y, '絞り込み条件の指定')
    y -= 6
    filter_steps = [
        '台帳一覧画面で検索条件を設定して「検索」をクリック',
        '検索結果に対して画面上部の「CSV出力」または「PDF出力」ボタンをクリック',
        '絞り込みなしの場合は全件が出力対象になります（権限範囲内）',
    ]
    for i, step in enumerate(filter_steps):
        y = draw_body(c, y, f'{i + 1}. {step}', size=8.5, indent=4)
    y -= 10

    y = draw_sub_title(c, y, 'CSV出力')
    y -= 6
    csv_items = [
        '文字コード: UTF-8 BOM付き（Excelで直接開いても文字化けしません）',
        'ファイル名: kottai_台帳_YYYYMMDD.csv',
        'Excelで開く場合: ダウンロード後にダブルクリックで自動認識されます',
        '含まれる項目: 台帳IDの全入力項目（ファイル添付を除く）',
    ]
    for item in csv_items:
        y = draw_bullet(c, y, item, size=8.5)
    y -= 10

    y = draw_sub_title(c, y, 'PDF出力')
    y -= 6
    pdf_items = [
        '形式: A4縦、古物台帳フォーマット（法令準拠レイアウト）',
        'ファイル名: kottai_台帳_YYYYMMDD.pdf',
        '内容: 1件1ページで詳細情報・添付ファイルサムネイルを含む',
        'ヘッダーにテナント名・拠点名・出力日時が印字されます',
        '大量データ（100件超）は処理に時間がかかる場合があります',
    ]
    for item in pdf_items:
        y = draw_bullet(c, y, item, size=8.5)
    y -= 12

    c.setFillColor(HexColor('#d1ecf1'))
    c.setStrokeColor(HexColor('#17a2b8'))
    c.rect(MARGIN_L, y - 38, CONTENT_W, 42, fill=1, stroke=1)
    c.setFont(FONT, 8.5)
    c.setFillColor(HexColor('#0c5460'))
    c.drawString(MARGIN_L + 8, y - 12, 'ヒント: 年度末の監査対応では、年度を絞り込んでPDF出力することを推奨します。')
    c.drawString(MARGIN_L + 8, y - 26, '出力操作は監査ログに記録されます。')


def draw_ch12(c: canvas.Canvas, page_num: int) -> None:
    """第12章: 年度別データ管理"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第12章   年度別データ管理')
    y -= 10

    y = draw_sub_title(c, y, '年度の定義')
    y -= 6
    yr_items = [
        '本システムでは「年度」を4月1日始まり・翌年3月31日終わりと定義します',
        '例: 2026年度 = 2026年4月1日 〜 2027年3月31日',
        '取引日の日付に基づいて自動的に年度が割り当てられます',
    ]
    for item in yr_items:
        y = draw_bullet(c, y, item, size=8.5)
    y -= 10

    y = draw_sub_title(c, y, '当年度と過去年度の違い')
    y -= 6
    headers = ['操作', '当年度', '過去年度']
    col_ws = [100, 90, CONTENT_W - 190]
    y = draw_table_row(c, y, headers, col_ws, is_header=True)
    rows = [
        ['台帳の閲覧', '可能', '可能'],
        ['台帳の編集', '可能（権限に応じて）', '不可'],
        ['台帳の削除', '可能（管理者のみ）', '不可'],
        ['CSV/PDF出力', '可能', '可能'],
        ['新規登録', '可能', '不可（取引日は当年度のみ）'],
    ]
    for i, row in enumerate(rows):
        bg = LGRAY if i % 2 == 0 else white
        y = draw_table_row(c, y, row, col_ws, bg=bg)
    y -= 14

    y = draw_sub_title(c, y, '年度フィルタの使い方')
    y -= 6
    filter_items = [
        '台帳一覧画面の「年度」プルダウンから対象年度を選択します',
        'デフォルトは「当年度」が選択されています',
        '複数年度をまたいだ検索はCSV出力で対応してください',
    ]
    for item in filter_items:
        y = draw_bullet(c, y, item, size=8.5)
    y -= 12

    # 補足ボックス
    c.setFillColor(LGRAY)
    c.setStrokeColor(BORDER)
    c.rect(MARGIN_L, y - 50, CONTENT_W, 54, fill=1, stroke=1)
    c.setFont(FONT, 9)
    c.setFillColor(NAVY)
    c.drawString(MARGIN_L + 8, y - 14, 'よくある疑問: 取引日を過去年度の日付で誤入力した場合')
    c.setFont(FONT, 8.5)
    c.setFillColor(black)
    c.drawString(MARGIN_L + 8, y - 28, '当年度登録後に気づいた場合は、管理者に削除依頼の上、正しい取引日で再登録してください。')
    c.drawString(MARGIN_L + 8, y - 42, '過去年度のデータは一切編集できないため、削除・再登録が唯一の対応方法です。')


def draw_ch13(c: canvas.Canvas, page_num: int) -> None:
    """第13章: セキュリティ・注意事項"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第13章   セキュリティ・注意事項')
    y -= 10

    y = draw_sub_title(c, y, 'セッションタイムアウト')
    y -= 6
    session_items = [
        '最終操作から15分間無操作の状態が続くと自動ログアウトされます',
        'ログアウト後はログイン画面に戻ります（入力中のデータは失われます）',
        '長時間の入力作業は、こまめに「一時保存」機能を活用してください',
        '共有PCを使用している場合は、作業終了後に必ずログアウトしてください',
    ]
    for item in session_items:
        y = draw_bullet(c, y, item, size=8.5)
    y -= 10

    y = draw_sub_title(c, y, 'パスワード管理のルール')
    y -= 6
    pass_items = [
        '他者にパスワードを教えないでください',
        '定期的なパスワード変更を推奨します（90日ごとが目安）',
        'ブラウザのパスワード自動保存機能は使用しないことを推奨します',
        '退職・異動時は管理者に連絡してアカウントを無効化してもらってください',
        '共有アカウントは使用禁止です（監査ログの追跡性が失われます）',
    ]
    for item in pass_items:
        y = draw_bullet(c, y, item, size=8.5)
    y -= 10

    y = draw_sub_title(c, y, 'アカウントロック')
    y -= 6
    # ロック説明ボックス
    c.setFillColor(HexColor('#f8d7da'))
    c.setStrokeColor(HexColor('#dc3545'))
    c.rect(MARGIN_L, y - 42, CONTENT_W, 46, fill=1, stroke=1)
    c.setFont(FONT, 8.5)
    c.setFillColor(HexColor('#721c24'))
    c.drawString(MARGIN_L + 8, y - 12, 'パスワードを5回連続で誤入力するとアカウントが30分間ロックされます。')
    c.drawString(MARGIN_L + 8, y - 26, '30分経過後に自動解除されます。緊急の場合は管理者に手動解除を依頼してください。')
    c.drawString(MARGIN_L + 8, y - 40, 'ロック発生は監査ログに記録され、管理者にメール通知されます。')
    y -= 58

    y = draw_sub_title(c, y, '不正アクセス・情報漏洩への対応')
    y -= 6
    security_items = [
        '不審なログインに気づいた場合は即座にパスワードを変更してください',
        'ブラウザの「戻る」操作でログアウト後のページが表示された場合はキャッシュを削除',
        '情報漏洩の疑いがある場合は管理者へ報告し、必要に応じてアカウントを無効化',
        'システムの脆弱性を発見した場合は、運営会社のサポート窓口に報告してください',
    ]
    for item in security_items:
        y = draw_bullet(c, y, item, size=8.5)


def draw_ch14(c: canvas.Canvas, page_num: int) -> None:
    """第14章: システム管理者機能"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第14章   システム管理者機能【システム管理者専用】')
    y -= 10

    # 警告ボックス
    c.setFillColor(HexColor('#fff3cd'))
    c.setStrokeColor(HexColor('#ffc107'))
    c.rect(MARGIN_L, y - 34, CONTENT_W, 38, fill=1, stroke=1)
    c.setFont(FONT, 8.5)
    c.setFillColor(HexColor('#856404'))
    c.drawString(MARGIN_L + 8, y - 12, 'この章はシステム管理者（サービス運営者）専用の機能説明です。')
    c.drawString(MARGIN_L + 8, y - 26, '一般テナントのユーザー・管理者はこの機能にアクセスできません。')
    y -= 50

    y = draw_sub_title(c, y, 'システム管理者ログイン')
    y -= 6
    login_items = [
        'アクセスURL: https://kottai-dacho.example.com/admin/login',
        'テナント側のログイン画面とは別のURLを使用します',
        'システム管理者アカウントは運営会社が管理します',
    ]
    for item in login_items:
        y = draw_bullet(c, y, item, size=8.5)
    y -= 10

    y = draw_sub_title(c, y, 'テナント管理')
    y -= 6
    headers = ['操作', '説明']
    col_ws = [100, CONTENT_W - 100]
    y = draw_table_row(c, y, headers, col_ws, is_header=True)
    rows = [
        ['テナント作成', '新規契約者のテナントを作成。初期管理者アカウントも同時作成'],
        ['テナント情報編集', 'テナント名・プラン・契約情報の変更'],
        ['テナント停止', 'テナントのアクセスを一時停止（データは保持）'],
        ['テナント削除', '全利用者を無効化（データはDBに保持）。契約終了時のみ実施'],
    ]
    for i, row in enumerate(rows):
        bg = LGRAY if i % 2 == 0 else white
        y = draw_table_row(c, y, row, col_ws, bg=bg)
    y -= 14

    y = draw_sub_title(c, y, '全テナント横断ログの閲覧')
    y -= 6
    log_items = [
        '全テナントの操作ログを横断的に閲覧・検索できます',
        'テナントID・日付範囲・操作種別で絞り込みが可能',
        '不正利用・障害調査時のトレーサビリティ確保に使用します',
        '閲覧操作自体もシステムログに記録されます',
    ]
    for item in log_items:
        y = draw_bullet(c, y, item, size=8.5)
    y -= 10

    y = draw_sub_title(c, y, 'システム管理者操作の注意事項')
    y -= 6
    caution_items = [
        'テナントデータへの直接操作は原則禁止です（法的リスクあり）',
        'テナント削除は不可逆操作です。必ず事前にデータバックアップを実施してください',
        'システム管理者アカウントのパスワードは定期的に変更し、厳重に管理してください',
    ]
    for item in caution_items:
        y = draw_bullet(c, y, item, size=8.5)


def draw_ch15(c: canvas.Canvas, page_num: int) -> None:
    """第15章: FAQ・トラブルシューティング"""
    draw_header_footer(c, page_num)
    y = PAGE_H - MARGIN_T
    y = draw_section_title(c, y, '第15章   FAQ・トラブルシューティング')
    y -= 10

    y = draw_sub_title(c, y, 'よくある質問と解決方法')
    y -= 8

    faqs = [
        ('ログインできない',
         ['テナントコード・メールアドレス・パスワードを再確認してください',
          'Caps Lockがオフになっているか確認してください',
          'アカウントがロックされている場合は30分後に再試行するか管理者に連絡']),
        ('パスワードを忘れた',
         ['管理者にパスワードリセットを依頼してください',
          '管理者不在の場合はシステム管理者（運営会社）のサポートに連絡']),
        ('ファイルがアップロードできない',
         ['ファイルサイズが50MB以内か確認してください',
          '対応形式（JPEG / PNG / PDF / HEIC）か確認してください',
          'ブラウザを最新版に更新して再試行してください']),
        ('台帳を編集できない',
         ['過去年度のデータは編集不可です（仕様）',
          '他のユーザーが登録したデータは一般ユーザーには編集権限がありません',
          '管理者に編集・修正を依頼してください']),
        ('アラートが出た',
         ['サイドバーの「アラート管理」をクリック',
          '重複の内容を確認し、「確認済み」または「誤登録として削除」を選択',
          '判断が難しい場合は管理者に相談してください']),
        ('CSVをExcelで開くと文字化けする',
         ['ファイルを右クリック →「プログラムから開く」→「Excel」を選択',
          'Excelの「データ」タブ →「テキストファイル」からUTF-8で開く',
          'または、ダウンロード後に「メモ帳」で開いてUTF-8確認']),
        ('検索しても結果が出ない',
         ['年度フィルタが正しい年度になっているか確認',
          '絞り込み条件が厳しすぎる可能性があります。条件を緩めて再検索',
          'キーワードの漢字・スペルを確認してください']),
        ('ページが表示されない / エラーが出る',
         ['ブラウザのキャッシュをクリアして再読み込み（Ctrl+Shift+R）',
          'ブラウザを対応版に更新してください（Chrome / Edge / Safari 最新版）',
          '問題が続く場合はシステム管理者（運営会社）に連絡']),
    ]

    for qa in faqs:
        question, answers = qa
        # 質問行
        c.setFillColor(NAVY)
        c.rect(MARGIN_L, y - 14, CONTENT_W, 15, fill=1, stroke=0)
        c.setFont(FONT, 8.5)
        c.setFillColor(white)
        c.drawString(MARGIN_L + 6, y - 10, f'Q. {question}')
        y -= 14
        # 回答行
        c.setFillColor(LGRAY)
        ans_h = len(answers) * 12 + 6
        c.rect(MARGIN_L, y - ans_h, CONTENT_W, ans_h, fill=1, stroke=0)
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.5)
        c.rect(MARGIN_L, y - ans_h, CONTENT_W, ans_h, fill=0, stroke=1)
        ay = y - 10
        for ans in answers:
            c.setFont(FONT, 8)
            c.setFillColor(black)
            c.drawString(MARGIN_L + 12, ay, f'A. {ans}')
            ay -= 12
        y -= ans_h + 6

    y -= 10
    # サポート窓口
    c.setFillColor(LGRAY)
    c.setStrokeColor(BORDER)
    c.rect(MARGIN_L, y - 38, CONTENT_W, 42, fill=1, stroke=1)
    c.setFont(FONT, 9)
    c.setFillColor(NAVY)
    c.drawString(MARGIN_L + 8, y - 12, 'サポート窓口')
    c.setFont(FONT, 8.5)
    c.setFillColor(black)
    c.drawString(MARGIN_L + 8, y - 26, 'メール: support@kottai-dacho.example.com')
    c.drawString(MARGIN_L + 8, y - 38, '対応時間: 平日 9:00 〜 18:00（土日祝除く）')


# ============================================================
# メイン生成処理
# ============================================================

def generate_manual(output_path: str) -> int:
    """PDFを生成してページ数を返す"""
    c = canvas.Canvas(output_path, pagesize=A4)
    c.setTitle('古物台帳管理システム 操作マニュアル v1.0')
    c.setAuthor('古物台帳管理システム')
    c.setSubject('操作マニュアル')

    page_count = 0

    # 表紙（ページ番号なし）
    draw_cover(c)
    c.showPage()
    page_count += 1

    # 目次
    draw_toc(c, 2)
    c.showPage()
    page_count += 1

    # 各章
    chapters = [
        draw_ch1,
        draw_ch2,
        draw_ch3,
        draw_ch4,
        draw_ch4_p2,
        draw_ch5,
        draw_ch6,
        draw_ch7,
        draw_ch8,
        draw_ch9,
        draw_ch10,
        draw_ch11,
        draw_ch12,
        draw_ch13,
        draw_ch14,
        draw_ch15,
    ]
    for i, draw_fn in enumerate(chapters):
        draw_fn(c, i + 3)
        c.showPage()
        page_count += 1

    c.save()
    return page_count


if __name__ == '__main__':
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'manual.pdf')
    print(f'PDFを生成しています: {output_path}')
    pages = generate_manual(output_path)
    size = os.path.getsize(output_path)
    print(f'完了: {output_path}')
    print(f'ページ数: {pages}ページ')
    print(f'ファイルサイズ: {size:,} bytes ({size / 1024:.1f} KB)')
