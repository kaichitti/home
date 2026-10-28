<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Models\Sale;

/**
 * 集計レポートコントローラー（管理者専用）
 * 仕入（台帳）と売上（販売記録）の推移を日/週/月/年/指定期間で表示する。
 */
class ReportController extends BaseController
{
    private const GRANULARITIES = ['day' => '日', 'week' => '週', 'month' => '月', 'year' => '年'];

    public function index(): void
    {
        $this->auth->requireAdmin();

        $tenantId    = $this->auth->getTenantId();
        $granularity = $this->request->get('granularity', 'day');
        if (!is_string($granularity) || !isset(self::GRANULARITIES[$granularity])) {
            $granularity = 'day';
        }

        // 期間: 指定がなければ粒度に応じた既定期間
        // （YYYY-MM-DD 以外の値は無視する。以前は strtotime が解釈できる任意の文字列
        //   ―「+1 day」「now」等―がそのままSQLと画面の日付欄に渡り、実質「全期間」で集計されていた）
        $to   = $this->request->get('to', '');
        $from = $this->request->get('from', '');
        $to   = is_string($to) ? $this->normalizeDate($to) : '';
        $from = is_string($from) ? $this->normalizeDate($from) : '';
        if ($to === '') {
            $to = date('Y-m-d');
        }
        if ($from === '') {
            $defaults = ['day' => '-30 days', 'week' => '-12 weeks', 'month' => '-12 months', 'year' => '-5 years'];
            $from = date('Y-m-d', strtotime($defaults[$granularity], strtotime($to)));
        }
        if (strtotime($from) > strtotime($to)) {
            [$from, $to] = [$to, $from];
        }

        $saleModel = new Sale($this->pdo);
        $sales     = $saleModel->aggregate($tenantId, $from, $to, $granularity);
        $purchases = $saleModel->aggregatePurchases($tenantId, $from, $to, $granularity);

        // 期間ラベルをマージして1つの表にする
        $periods = [];
        foreach ($purchases as $r) {
            $periods[$r['period']]['purchase'] = $r;
        }
        foreach ($sales as $r) {
            $periods[$r['period']]['sale'] = $r;
        }
        ksort($periods);

        // 合計と粗利
        $totalPurchase = 0;
        $totalSale     = 0;
        foreach ($periods as $row) {
            $totalPurchase += (int)($row['purchase']['total'] ?? 0);
            $totalSale     += (int)($row['sale']['total'] ?? 0);
        }

        $this->render('report/index', [
            'periods'       => $periods,
            'granularity'   => $granularity,
            'granularities' => self::GRANULARITIES,
            'from'          => $from,
            'to'            => $to,
            'totalPurchase' => $totalPurchase,
            'totalSale'     => $totalSale,
        ]);
    }

    /**
     * YYYY-MM-DD 形式の実在する日付ならそのまま、それ以外は空文字
     */
    private function normalizeDate(string $value): string
    {
        $value = trim($value);
        if (preg_match('/^(\d{4})-(\d{2})-(\d{2})$/', $value, $m) && checkdate((int)$m[2], (int)$m[3], (int)$m[1])) {
            return $value;
        }
        return '';
    }
}
