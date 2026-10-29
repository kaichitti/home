"""
台帳のエクスポート（テナント管理者のみ）: CSV / 印刷用 HTML（ブラウザで開いて「PDFとして保存」）
"""
import html as _html
import re

from ..core.controller import BaseController
from ..core.response import Response, ResponseDone
from ..helpers import csv_writer
from ..models import item_category
from ..models.audit_log import AuditLog
from ..models.branch import Branch
from ..models.item_category import ItemCategory
from ..models.ledger import Ledger
from ..util import html_escape, is_empty, is_numeric, now, number_format, rawurlencode

CSV_HEADERS = [
    '取引年月日', '取引種別', '古物の種類', '品目', 'シリアル番号', '特徴・説明', '数量', '取引金額', '会員番号',
    '相手方区分', '相手方氏名・名称', '担当者名', '住所・所在地', '職業', '年齢', '電話番号', '取引アカウント',
    '本人確認書類', '書類番号', '備考', '登録者', '所属拠点', '登録日時', '年度',
]

TRANSACTION_TYPE_LABELS = {'buy': '買取', 'exchange': '交換', 'consignment': '委託販売受け', 'other': 'その他'}

ID_DOCUMENT_LABELS = {
    'driver_license': '運転免許証', 'my_number': 'マイナンバーカード', 'passport': 'パスポート',
    'health_insurance': '健康保険証', 'residence_card': '住民基本台帳カード', 'residence_status': '在留カード',
    'special_permanent': '特別永住者証明書', 'other': 'その他',
}

_ENTITY_RE = re.compile(r'&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);')


def decode_legacy(value):
    """過去に入力時 HTML エンコードして保存されたデータを平文へ戻す（新しいデータには影響しない）"""
    if value is None or value == '':
        return '' if value is None else value
    return _ENTITY_RE.sub(lambda m: _html.unescape(m.group(0)), str(value))


def _s(v):
    return '' if v is None else str(v)


def build_csv_row(row):
    """台帳1件を CSV の1行（列のリスト）にする"""
    ttype = _s(row.get('transaction_type'))
    trans = TRANSACTION_TYPE_LABELS.get(ttype, ttype)
    if ttype == 'other' and not is_empty(row.get('transaction_type_note')):
        trans += '(' + _s(row['transaction_type_note']) + ')'
    doc = row.get('id_document_type') or ''
    doc_cell = ID_DOCUMENT_LABELS.get(doc, doc) if doc != '' else '未登録'
    # 「その他」の場合は書類の内容も同じセルに併記する
    if doc == 'other' and not is_empty(row.get('id_document_type_note')):
        doc_cell += '（' + decode_legacy(row['id_document_type_note']) + '）'
    return [
        _s(row.get('transaction_date')),
        decode_legacy(trans),
        decode_legacy(item_category.label(row.get('item_category') or '', row.get('item_category_note'))),
        decode_legacy(row.get('item_name')),
        _s(row.get('serial_number')),
        decode_legacy(row.get('item_description')),
        _s(row.get('quantity')),
        _s(row.get('transaction_amount')),
        _s(row.get('member_code')),
        '法人' if (row.get('counterpart_type') or 'individual') == 'corporate' else '個人',
        decode_legacy(row.get('counterpart_name')),
        decode_legacy(row.get('counterpart_contact_name')),
        decode_legacy(row.get('counterpart_address')),
        decode_legacy(row.get('counterpart_occupation')),
        _s(row.get('counterpart_age')),
        decode_legacy(row.get('counterpart_phone')),
        decode_legacy(row.get('counterpart_account')),
        doc_cell,
        decode_legacy(row.get('id_document_number')),
        decode_legacy(row.get('counterpart_note')),
        decode_legacy(row.get('registered_by_name')),
        decode_legacy(row.get('branch_name')),
        _s(row.get('created_at')),
        _s(row.get('fiscal_year')),
    ]


def _download_headers(ascii_name, name):
    return [
        ('Content-Disposition', 'attachment; filename="%s"; filename*=UTF-8\'\'%s' % (ascii_name, rawurlencode(name))),
        ('Cache-Control', 'no-cache, no-store, must-revalidate'),
        ('Pragma', 'no-cache'),
        ('Expires', '0'),
    ]


PDF_CSS = '''
body {
    font-family: "Noto Sans JP", "Hiragino Kaku Gothic ProN", "Hiragino Sans", "Yu Gothic", "Meiryo", sans-serif;
    font-size: 9pt;
    color: #000;
    margin: 0;
    padding: 0;
}
.cover {
    margin: 10mm 15mm 8mm;
}
.cover h1 {
    font-size: 16pt;
    font-weight: bold;
    text-align: center;
    margin-bottom: 6pt;
    border-bottom: 2pt solid #000;
    padding-bottom: 4pt;
}
.cover-meta {
    font-size: 8pt;
    color: #333;
    text-align: right;
    margin-bottom: 4pt;
}
.table-wrap {
    margin: 0 5mm;
    overflow-x: visible;
}
table.ledger {
    border-collapse: collapse;
    width: 100%;
    font-size: 7.5pt;
}
table.ledger th {
    background: #1e3a5f;
    color: #fff;
    font-weight: bold;
    padding: 4pt 3pt;
    border: 0.5pt solid #999;
    text-align: center;
    white-space: nowrap;
}
table.ledger td {
    padding: 3pt 3pt;
    border: 0.5pt solid #ccc;
    vertical-align: top;
    word-break: break-all;
}
table.ledger tbody tr:nth-child(even) td {
    background: #f5f5f5;
}
.footer-note {
    margin: 6pt 5mm 0;
    font-size: 7pt;
    color: #555;
    text-align: right;
}
@media print {
    @page {
        size: A4 landscape;
        margin: 10mm;
    }
    body { margin: 0; }
    .cover { margin: 0 0 6pt; }
    table.ledger { page-break-inside: auto; }
    table.ledger tr { page-break-inside: avoid; }
    table.ledger thead { display: table-header-group; }
}
'''


def build_pdf_html(records, standalone=True):
    """印刷用 HTML（列は CSV と同じ）"""
    d = now()
    rows = []
    for row in records:
        cells = []
        for idx, cell in enumerate(build_csv_row(row)):
            # 数量(6)・取引金額(7)・年齢(14) は右寄せ、金額はカンマ区切り
            style = ' style="text-align:right;"' if idx in (6, 7, 14) else ''
            text = str(cell)
            if idx == 7 and text != '' and is_numeric(text):
                text = number_format(float(text))
            cells.append('<td' + style + '>' + html_escape(text) + '</td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>\n')
    out = ['<!DOCTYPE html>\n', '<html lang="ja"><head><meta charset="UTF-8">']
    if standalone:
        out.append('<title>古物台帳</title>')
    out.append('<style>' + PDF_CSS + '</style></head><body>')
    out.append('<div class="cover"><h1>古物台帳</h1><div class="cover-meta">')
    out.append('出力日: %04d年%02d月%02d日&nbsp;&nbsp;総件数: %d件' % (d.year, d.month, d.day, len(records)))
    out.append('</div></div><div class="table-wrap"><table class="ledger"><thead><tr>')
    out.extend('<th>' + html_escape(h) + '</th>' for h in CSV_HEADERS)
    out.append('</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')
    if standalone:
        out.append('<div class="footer-note">※ このファイルをブラウザで開き、印刷（Ctrl+P / Cmd+P）→ A4横でPDF保存してください。</div>')
    out.append('</body></html>')
    return ''.join(out)


class ExportController(BaseController):
    def index(self):
        self.auth.require_admin_role()
        tenant_id = self.auth.tenant_id()
        self.render('export/index', {
            'branches': Branch(self.db).find_all_by_tenant(tenant_id),
            'users': self.db.query(
                """SELECT `id`, `display_name` FROM `users`
                 WHERE `tenant_id` = ? AND `is_active` = 1 ORDER BY `display_name` ASC""", (tenant_id,)),
            'fiscalYears': Ledger(self.db).get_years(tenant_id),
            'itemTypes': ItemCategory(self.db).build_options(tenant_id),
        })

    def export(self):
        """出力（POST）。format=csv → CSV / format=pdf → 印刷用 HTML"""
        self.auth.require_admin_role()
        if not self.request.is_post():
            self.redirect('/index.cgi?page=export')
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        fmt = self.request.post('format', 'csv')

        def p(key):
            v = self.request.post(key)
            return v if isinstance(v, str) and not is_empty(v) else None

        filters = {
            'date_from': p('date_from'), 'date_to': p('date_to'), 'fiscal_year': p('fiscal_year'),
            'item_category': p('item_type'), 'transaction_type': p('transaction_type'),
            'item_name': p('item_name'), 'counterpart_name': p('counterpart_name'),
            'registered_by_id': p('registered_by'), 'branch_id': p('branch_id'),
        }
        records = Ledger(self.db).find_all(tenant_id, filters, 1, 99999)['records']
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'export', None, None,
                              {'format': fmt, 'count': len(records), 'filters': filters}, self.request.ip())
        stamp = now().strftime('%Y%m%d')
        if fmt == 'pdf':
            body = build_pdf_html(records, True).encode('utf-8')
            raise ResponseDone(Response(body, 200, 'text/html; charset=UTF-8',
                                        _download_headers('kobutsu_daicho_%s.html' % stamp, '古物台帳_%s.html' % stamp)))
        lines = ['﻿', csv_writer.row(CSV_HEADERS)]  # BOM（Excel での文字化け防止）
        for row in records:
            lines.append(csv_writer.row([csv_writer.safe(c) for c in build_csv_row(row)]))
        raise ResponseDone(Response(''.join(lines).encode('utf-8'), 200, 'text/csv; charset=UTF-8',
                                    _download_headers('kobutsu_daicho_%s.csv' % stamp, '古物台帳_%s.csv' % stamp)))
