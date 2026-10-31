<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Models\Ledger;
use FuryoDacho\Models\Branch;
use FuryoDacho\Models\User;
use FuryoDacho\Models\AuditLog;

/**
 * エクスポートコントローラー（テナント管理者専用）
 * CSV / PDF（mPDF または HTMLフォールバック）の出力を担当する。
 */
class ExportController extends BaseController
{
    /** CSV ヘッダー行の定義 */
    private const CSV_HEADERS = [
        '取引年月日',
        '取引種別',
        '古物の種類',
        '品目',
        'シリアル番号',
        '特徴・説明',
        '数量',
        '取引金額',
        '会員番号',
        '相手方区分',
        '相手方氏名・名称',
        '担当者名',
        '住所・所在地',
        '職業',
        '年齢',
        '電話番号',
        '取引アカウント',
        '本人確認書類',
        '書類番号',
        '備考',
        '登録者',
        '所属拠点',
        '登録日時',
        '年度',
    ];

    /** 古物区分の日本語マッピング */
    private const ITEM_CATEGORY_LABELS = [
        'art'               => '美術品類',
        'clothing'          => '衣類',
        'watch_jewelry'     => '時計・宝飾品類',
        'automobile'        => '自動車',
        'motorcycle'        => '自動二輪車及び原動機付自転車',
        'bicycle'           => '自転車類',
        'camera'            => '写真機類',
        'office_equipment'  => '事務機器類',
        'machinery'         => '機械工具類',
        'tools'             => '道具類',
        'leather_rubber'    => '皮革・ゴム製品類',
        'books'             => '書籍',
        'gift_certificates' => '金券類',
    ];

    /** 取引種別の日本語マッピング */
    private const TRANSACTION_TYPE_LABELS = [
        'buy'         => '買取',
        'exchange'    => '交換',
        'consignment' => '委託販売受け',
        'other'       => 'その他',
    ];

    /** 本人確認書類種別の日本語マッピング */
    private const ID_DOCUMENT_LABELS = [
        'driver_license'    => '運転免許証',
        'my_number'         => 'マイナンバーカード',
        'passport'          => 'パスポート',
        'health_insurance'  => '健康保険証',
        'residence_card'    => '住民基本台帳カード',
        'residence_status'  => '在留カード',
        'special_permanent' => '特別永住者証明書',
        'other'             => 'その他',
    ];

    /**
     * 過去に入力時HTMLエンコードで保存されてしまったデータを
     * エクスポート時に平文へ戻す（新規データには影響しない）
     */
    private function decodeLegacy(?string $value): string
    {
        if ($value === null || $value === '') {
            return (string)$value;
        }
        return html_entity_decode($value, ENT_QUOTES | ENT_HTML5, 'UTF-8');
    }

    /**
     * エクスポート設定フォーム表示
     */
    public function index(): void
    {
        $this->auth->requireAdmin();

        $tenantId  = $this->auth->getTenantId();
        $branches  = (new Branch($this->pdo))->findAllByTenant($tenantId);
        $users     = $this->getUsersByTenant($tenantId);
        $ledger    = new Ledger($this->pdo);
        $fiscalYears = $ledger->getYears($tenantId);

        $csrf_token = $this->generateCsrfToken();
        $itemTypes  = (new \FuryoDacho\Models\ItemCategory($this->pdo))->buildOptions($tenantId);

        $this->render('export/index', compact('branches', 'users', 'fiscalYears', 'csrf_token', 'itemTypes'));
    }

    /**
     * エクスポート実行（POST）
     * format=csv → exportCsv()
     * format=pdf → exportPdf()
     */
    public function export(): void
    {
        $this->auth->requireAdmin();

        if (!$this->request->isPost()) {
            $this->response->redirect('/index.php?page=export');
            return;
        }

        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $userId   = $this->auth->getUserId();

        // format は $_POST から直接取得（sanitize 済みの $this->request->post() を使用）
        $format = $this->request->post('format', 'csv');
        $format = is_string($format) ? $format : 'csv';

        // 絞り込み条件を取得（文字列以外＝配列などが送られた項目は条件なしとして扱う）
        $p = function (string $key): ?string {
            $v = $this->request->post($key);
            return is_string($v) && $v !== '' && $v !== '0' ? $v : null;
        };
        $filters = [
            'date_from'          => $p('date_from'),
            'date_to'            => $p('date_to'),
            'fiscal_year'        => $p('fiscal_year'),
            'item_category'      => $p('item_type'),
            'transaction_type'   => $p('transaction_type'),
            'item_name'          => $p('item_name'),
            'counterpart_name'   => $p('counterpart_name'),
            'registered_by_id'   => $p('registered_by'),
            'branch_id'          => $p('branch_id'),
        ];

        // ページネーションなしで全件取得（perPage を十分大きな値に設定）
        $ledgerModel = new Ledger($this->pdo);
        $result      = $ledgerModel->findAll($tenantId, $filters, 1, 99999);
        $records     = $result['records'];

        // 監査ログ記録
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $userId,
            $this->auth->user()['display_name'],
            null,
            'export',
            null,
            null,
            [
                'format'  => $format,
                'count'   => count($records),
                'filters' => $filters,
            ],
            $this->request->ip()
        );

        if ($format === 'pdf') {
            $this->exportPdf($records, $tenantId);
        } else {
            $this->exportCsv($records);
        }
    }

    // ----------------------------------------------------------------
    // CSV 出力
    // ----------------------------------------------------------------

    /**
     * CSV ダウンロード出力
     *
     * @param array $records
     */
    private function exportCsv(array $records): void
    {
        // 日本語ファイル名は RFC 5987 (filename*) で渡し、ASCIIフォールバックも付ける
        $filename      = '古物台帳_' . date('Ymd') . '.csv';
        $asciiFilename = 'kobutsu_daicho_' . date('Ymd') . '.csv';

        header('Content-Type: text/csv; charset=UTF-8');
        header('Content-Disposition: attachment; filename="' . $asciiFilename . '"; filename*=UTF-8\'\'' . rawurlencode($filename));
        header('Cache-Control: no-cache, no-store, must-revalidate');
        header('Pragma: no-cache');
        header('Expires: 0');

        $fp = fopen('php://output', 'w');

        // UTF-8 BOM（Excel での文字化け防止）
        fwrite($fp, "\xEF\xBB\xBF");

        // ヘッダー行
        fputcsv($fp, self::CSV_HEADERS);

        // データ行（各セルを数式インジェクション対策で無害化してから出力）
        foreach ($records as $row) {
            fputcsv($fp, array_map([$this, 'csvSafe'], $this->buildCsvRow($row)));
        }

        fclose($fp);
        exit;
    }

    /**
     * CSV セルを数式（formula）インジェクションから無害化する。
     *
     * Excel / LibreOffice 等は先頭が = + - @ （およびタブ・改行）で始まる
     * セルを数式として評価してしまう。品名・相手方氏名・備考などに
     * 「=HYPERLINK(...)」や「=cmd|'...'」を仕込まれると、管理者が
     * CSVを開いた時に情報送信やコマンド起動につながるため、
     * 危険な先頭文字の場合はシングルクオートを前置して文字列扱いにする。
     *
     * @param mixed $value セル値
     * @return string
     */
    private function csvSafe($value): string
    {
        $str = (string)$value;
        if ($str === '') {
            return $str;
        }
        $first = $str[0];
        if (in_array($first, ['=', '+', '-', '@', "\t", "\r"], true)) {
            return "'" . $str;
        }
        return $str;
    }

    /**
     * 台帳レコード 1 行を CSV 行配列に変換
     *
     * @param array $row
     * @return array
     */
    private function buildCsvRow(array $row): array
    {
        $transType = self::TRANSACTION_TYPE_LABELS[$row['transaction_type'] ?? ''] ?? ($row['transaction_type'] ?? '');
        if (($row['transaction_type'] ?? '') === 'other' && !empty($row['transaction_type_note'])) {
            $transType .= '(' . $row['transaction_type_note'] . ')';
        }

        $docType = $row['id_document_type'] ?? '';
        $docCell = $docType !== '' && $docType !== null ? (self::ID_DOCUMENT_LABELS[$docType] ?? $docType) : '未登録';
        // 「その他」の場合は書類の内容も出力する（列は増やさず同じセルに併記）
        if ($docType === 'other' && !empty($row['id_document_type_note'])) {
            $docCell .= '（' . $this->decodeLegacy((string)$row['id_document_type_note']) . '）';
        }
        return [
            $row['transaction_date']       ?? '',
            $this->decodeLegacy($transType),
            $this->decodeLegacy(\FuryoDacho\Models\ItemCategory::label($row['item_category'] ?? '', $row['item_category_note'] ?? null)),
            $this->decodeLegacy($row['item_name']              ?? ''),
            $row['serial_number']          ?? '',
            $this->decodeLegacy($row['item_description']       ?? ''),
            $row['quantity']               ?? '',
            $row['transaction_amount']     ?? '',
            $row['member_code']            ?? '',
            ($row['counterpart_type'] ?? 'individual') === 'corporate' ? '法人' : '個人',
            $this->decodeLegacy($row['counterpart_name']       ?? ''),
            $this->decodeLegacy($row['counterpart_contact_name'] ?? ''),
            $this->decodeLegacy($row['counterpart_address']    ?? ''),
            $this->decodeLegacy($row['counterpart_occupation'] ?? ''),
            $row['counterpart_age']        ?? '',
            $this->decodeLegacy($row['counterpart_phone']      ?? ''),
            $this->decodeLegacy($row['counterpart_account']    ?? ''),
            // 未登録の場合は空欄。以前は 'driver_license' 等の英語enum値がそのまま出力されていた
            $docCell,
            $this->decodeLegacy($row['id_document_number']     ?? ''),
            $this->decodeLegacy($row['counterpart_note']       ?? ''),
            $this->decodeLegacy($row['registered_by_name']     ?? ''),
            $this->decodeLegacy($row['branch_name']            ?? ''),
            $row['created_at']             ?? '',
            $row['fiscal_year']            ?? '',
        ];
    }

    // ----------------------------------------------------------------
    // PDF 出力（mPDF / HTMLフォールバック）
    // ----------------------------------------------------------------

    /**
     * PDF ダウンロード出力
     * mPDF が vendor/ に存在する場合は mPDF で、なければ印刷用 HTML で出力する。
     *
     * @param array $records
     * @param int   $tenantId
     */
    private function exportPdf(array $records, int $tenantId): void
    {
        $mpdfPath = __DIR__ . '/../../vendor/mpdf/mpdf/src/Mpdf.php';

        if (file_exists($mpdfPath)) {
            $this->exportPdfWithMpdf($records);
        } else {
            $this->exportPdfFallback($records);
        }
    }

    /**
     * mPDF を使った PDF 出力
     *
     * @param array $records
     */
    private function exportPdfWithMpdf(array $records): void
    {
        require_once __DIR__ . '/../../vendor/autoload.php';

        $mpdf = new \Mpdf\Mpdf([
            'mode'        => 'utf-8',
            'format'      => 'A4',
            'orientation' => 'L',  // 横向き（カラム数が多いため）
            'margin_top'  => 15,
            'margin_right'  => 10,
            'margin_bottom' => 15,
            'margin_left'   => 10,
        ]);

        $html = $this->buildPdfHtml($records, false);
        $mpdf->WriteHTML($html);

        $filename = '古物台帳_' . date('Ymd') . '.pdf';
        $mpdf->Output($filename, 'D');
        exit;
    }

    /**
     * mPDF がない場合のフォールバック: 印刷用 HTML を出力
     * Content-Disposition: attachment で .html ファイルとしてダウンロードさせる。
     *
     * @param array $records
     */
    private function exportPdfFallback(array $records): void
    {
        $filename      = '古物台帳_' . date('Ymd') . '.html';
        $asciiFilename = 'kobutsu_daicho_' . date('Ymd') . '.html';

        header('Content-Type: text/html; charset=UTF-8');
        header('Content-Disposition: attachment; filename="' . $asciiFilename . '"; filename*=UTF-8\'\'' . rawurlencode($filename));
        header('Cache-Control: no-cache, no-store, must-revalidate');
        header('Pragma: no-cache');
        header('Expires: 0');

        echo $this->buildPdfHtml($records, true);
        exit;
    }

    /**
     * PDF / 印刷用 HTML を生成する
     *
     * @param array $records
     * @param bool  $standalone 単体 HTML として出力する場合は true（CSS を完全に埋め込む）
     * @return string
     */
    private function buildPdfHtml(array $records, bool $standalone): string
    {
        $dateStr  = date('Y年m月d日');
        $total    = count($records);
        $title    = '古物台帳';

        // ヘッダー（CSV_HEADERS）と行の列を常に一致させるため、
        // CSVと同じ行ビルダーを再利用する（以前は別実装で列ズレの温床だった）
        $rowsHtml = '';
        foreach ($records as $row) {
            $rowsHtml .= '<tr>';
            foreach ($this->buildCsvRow($row) as $idx => $cell) {
                // 数量(6)・取引金額(7)・年齢(14) は右寄せ、金額はカンマ区切り
                $style = in_array($idx, [6, 7, 14], true) ? ' style="text-align:right;"' : '';
                $text  = (string)$cell;
                if ($idx === 7 && $text !== '' && is_numeric($text)) {
                    $text = number_format((float)$text);
                }
                $rowsHtml .= '<td' . $style . '>' . htmlspecialchars($text) . '</td>';
            }
            $rowsHtml .= '</tr>' . "\n";
        }

        $css = '
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
';

        $html  = '<!DOCTYPE html>' . "\n";
        $html .= '<html lang="ja"><head><meta charset="UTF-8">';
        if ($standalone) {
            $html .= '<title>古物台帳</title>';
        }
        $html .= '<style>' . $css . '</style></head><body>';
        $html .= '<div class="cover">';
        $html .= '<h1>' . htmlspecialchars($title) . '</h1>';
        $html .= '<div class="cover-meta">';
        $html .= '出力日: ' . $dateStr . '&nbsp;&nbsp;';
        $html .= '総件数: ' . $total . '件';
        $html .= '</div>';
        $html .= '</div>';
        $html .= '<div class="table-wrap">';
        $html .= '<table class="ledger">';
        $html .= '<thead><tr>';
        foreach (self::CSV_HEADERS as $h) {
            $html .= '<th>' . htmlspecialchars($h) . '</th>';
        }
        $html .= '</tr></thead>';
        $html .= '<tbody>' . $rowsHtml . '</tbody>';
        $html .= '</table>';
        $html .= '</div>';

        if ($standalone) {
            $html .= '<div class="footer-note">';
            $html .= '※ このファイルをブラウザで開き、印刷（Ctrl+P / Cmd+P）→ A4横でPDF保存してください。';
            $html .= '</div>';
        }

        $html .= '</body></html>';

        return $html;
    }

    // ----------------------------------------------------------------
    // 内部ユーティリティ
    // ----------------------------------------------------------------

    /**
     * テナントのユーザー一覧を取得（登録者プルダウン用）
     *
     * @param int $tenantId
     * @return array
     */
    private function getUsersByTenant(int $tenantId): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT `id`, `display_name`
             FROM `users`
             WHERE `tenant_id` = ? AND `is_active` = 1
             ORDER BY `display_name` ASC"
        );
        $stmt->execute([$tenantId]);
        return $stmt->fetchAll();
    }
}
