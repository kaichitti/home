<?php

namespace FuryoDacho\Models;

/**
 * POS 会計（取引）モデル
 *
 * 会計1回 = pos_transactions 1行 + 明細（pos_transaction_items）+ 販売記録（sales）。
 * 在庫は従来どおり sales の数量合計で減る。取消時は販売記録を削除して在庫を戻し、
 * 会計と明細はレシート再発行・監査のためにそのまま残す（status = voided）。
 */
class PosTransaction extends BaseModel
{
    protected string $table = 'pos_transactions';

    public function findById(int $id, int $tenantId): ?array
    {
        $stmt = $this->pdo->prepare(
            "SELECT t.*, b.name AS branch_name, vu.display_name AS voided_by_name
             FROM `pos_transactions` t
             LEFT JOIN `branches` b ON b.id = t.branch_id
             LEFT JOIN `users` vu ON vu.id = t.voided_by
             WHERE t.`id` = ? AND t.`tenant_id` = ?"
        );
        $stmt->execute([$id, $tenantId]);
        return $stmt->fetch() ?: null;
    }

    public function findByToken(int $tenantId, string $token): ?array
    {
        $stmt = $this->pdo->prepare(
            "SELECT * FROM `pos_transactions` WHERE `tenant_id` = ? AND `client_token` = ?"
        );
        $stmt->execute([$tenantId, $token]);
        return $stmt->fetch() ?: null;
    }

    public function items(int $transactionId, int $tenantId): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT * FROM `pos_transaction_items`
             WHERE `transaction_id` = ? AND `tenant_id` = ?
             ORDER BY `line_no` ASC, `id` ASC"
        );
        $stmt->execute([$transactionId, $tenantId]);
        return $stmt->fetchAll();
    }

    /**
     * レシート番号を採番する（テナント・日付ごとの連番。トランザクション内で呼ぶ）
     *
     * カウンター行の更新は行ロックを伴うため、同時に会計しても番号は重複しない。
     */
    public function nextReceiptNo(int $tenantId, string $bizDate): string
    {
        $stmt = $this->pdo->prepare(
            "INSERT INTO `pos_counters` (`tenant_id`, `biz_date`, `last_no`)
             VALUES (?, ?, LAST_INSERT_ID(1))
             ON DUPLICATE KEY UPDATE `last_no` = LAST_INSERT_ID(`last_no` + 1)"
        );
        $stmt->execute([$tenantId, $bizDate]);
        $no = (int)$this->pdo->query("SELECT LAST_INSERT_ID()")->fetchColumn();
        if ($no < 1) {
            throw new \RuntimeException('レシート番号の採番に失敗しました。');
        }
        return str_replace('-', '', $bizDate) . '-' . str_pad((string)$no, 4, '0', STR_PAD_LEFT);
    }

    public function insert(array $d): int
    {
        $stmt = $this->pdo->prepare(
            "INSERT INTO `pos_transactions`
                (`tenant_id`, `branch_id`, `register_no`, `receipt_no`, `client_token`, `status`, `member_code`,
                 `member_id`, `member_name`, `item_count`,
                 `subtotal`, `discount_type`, `discount_value`, `discount_amount`, `tax_mode`, `tax_rate`,
                 `tax_amount`, `total`, `payment_method`, `tendered`, `change_amount`, `payment_ref`, `note`,
                 `store_info`, `cashier_name`, `receipt_status`, `created_by`, `created_at`)
             VALUES (?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        );
        $stmt->execute([
            $d['tenant_id'], $d['branch_id'], $d['register_no'] ?? null, $d['receipt_no'], $d['client_token'],
            $d['member_code'] !== '' ? $d['member_code'] : null,
            $d['member_id'] ?? null,
            ($d['member_name'] ?? '') !== '' ? $d['member_name'] : null,
            $d['item_count'], $d['subtotal'], $d['discount_type'], $d['discount_value'], $d['discount_amount'],
            $d['tax_mode'], $d['tax_rate'], $d['tax_amount'], $d['total'],
            $d['payment_method'], $d['tendered'], $d['change_amount'],
            $d['payment_ref'] !== '' ? $d['payment_ref'] : null,
            $d['note'] !== '' ? $d['note'] : null,
            $d['store_info'], $d['cashier_name'], $d['receipt_status'], $d['created_by'], $d['created_at'],
        ]);
        return (int)$this->pdo->lastInsertId();
    }

    public function insertItem(array $d): int
    {
        $stmt = $this->pdo->prepare(
            "INSERT INTO `pos_transaction_items`
                (`transaction_id`, `tenant_id`, `ledger_id`, `sale_id`, `line_no`, `item_name`, `serial_number`,
                 `quantity`, `unit_price`, `line_discount`, `amount`, `allocated_amount`)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        );
        $stmt->execute([
            $d['transaction_id'], $d['tenant_id'], $d['ledger_id'], $d['sale_id'], $d['line_no'],
            $d['item_name'], ($d['serial_number'] ?? '') !== '' ? $d['serial_number'] : null,
            $d['quantity'], $d['unit_price'], $d['line_discount'], $d['amount'], $d['allocated_amount'],
        ]);
        return (int)$this->pdo->lastInsertId();
    }

    /**
     * レシート・領収書の印刷結果を記録する
     *
     * @param string $doc    receipt|ryoshu
     * @param string $result printed|failed
     * @return array{before: array, after: array}|null
     */
    public function recordPrint(int $id, int $tenantId, string $doc, string $result): ?array
    {
        $this->pdo->beginTransaction();
        try {
            $stmt = $this->pdo->prepare(
                "SELECT `receipt_status`, `print_count`, `ryoshu_count` FROM `pos_transactions`
                 WHERE `id` = ? AND `tenant_id` = ? FOR UPDATE"
            );
            $stmt->execute([$id, $tenantId]);
            $before = $stmt->fetch();
            if ($before === false) {
                $this->pdo->rollBack();
                return null;
            }

            if ($doc === 'ryoshu') {
                if ($result === 'printed') {
                    $this->pdo->prepare(
                        "UPDATE `pos_transactions` SET `ryoshu_count` = `ryoshu_count` + 1 WHERE `id` = ? AND `tenant_id` = ?"
                    )->execute([$id, $tenantId]);
                }
            } elseif ($result === 'printed') {
                $this->pdo->prepare(
                    "UPDATE `pos_transactions`
                     SET `print_count` = `print_count` + 1, `receipt_status` = 'printed', `last_printed_at` = NOW()
                     WHERE `id` = ? AND `tenant_id` = ?"
                )->execute([$id, $tenantId]);
            } elseif ((int)$before['print_count'] === 0) {
                // 一度も印刷できていない場合のみ「印刷失敗」とする（再発行の失敗で印刷済みを上書きしない）
                $this->pdo->prepare(
                    "UPDATE `pos_transactions` SET `receipt_status` = 'print_failed' WHERE `id` = ? AND `tenant_id` = ?"
                )->execute([$id, $tenantId]);
            }

            $stmt = $this->pdo->prepare(
                "SELECT `receipt_status`, `print_count`, `ryoshu_count` FROM `pos_transactions` WHERE `id` = ? AND `tenant_id` = ?"
            );
            $stmt->execute([$id, $tenantId]);
            $after = $stmt->fetch();
            $this->pdo->commit();
            return ['before' => $before, 'after' => $after];
        } catch (\Throwable $e) {
            if ($this->pdo->inTransaction()) {
                $this->pdo->rollBack();
            }
            throw $e;
        }
    }

    /**
     * 会計を取り消す（販売記録を削除して在庫を戻す）
     *
     * @return array|null 取消前の会計（取消できない状態なら null）
     */
    public function void(int $id, int $tenantId, int $userId, string $reason): ?array
    {
        $this->pdo->beginTransaction();
        try {
            $stmt = $this->pdo->prepare(
                "SELECT * FROM `pos_transactions` WHERE `id` = ? AND `tenant_id` = ? FOR UPDATE"
            );
            $stmt->execute([$id, $tenantId]);
            $tx = $stmt->fetch();
            if ($tx === false || $tx['status'] !== 'completed') {
                $this->pdo->rollBack();
                return null;
            }

            // 販売記録は主キーで削除する（索引範囲のギャップロックで他の会計を止めない）
            $stmt = $this->pdo->prepare(
                "SELECT `sale_id` FROM `pos_transaction_items`
                 WHERE `transaction_id` = ? AND `tenant_id` = ? AND `sale_id` IS NOT NULL"
            );
            $stmt->execute([$id, $tenantId]);
            $saleIds = array_map('intval', $stmt->fetchAll(\PDO::FETCH_COLUMN));
            if ($saleIds !== []) {
                $ph = implode(',', array_fill(0, count($saleIds), '?'));
                $this->pdo->prepare(
                    "DELETE FROM `sales` WHERE `tenant_id` = ? AND `transaction_id` = ? AND `id` IN ($ph)"
                )->execute(array_merge([$tenantId, $id], $saleIds));
            }

            $this->pdo->prepare(
                "UPDATE `pos_transactions`
                 SET `status` = 'voided', `voided_by` = ?, `voided_at` = NOW(), `void_reason` = ?
                 WHERE `id` = ? AND `tenant_id` = ?"
            )->execute([$userId, $reason, $id, $tenantId]);

            $this->pdo->commit();
            return $tx;
        } catch (\Throwable $e) {
            if ($this->pdo->inTransaction()) {
                $this->pdo->rollBack();
            }
            throw $e;
        }
    }

    private static function likeEscape(string $v): string
    {
        return strtr($v, ['\\' => '\\\\', '%' => '\\%', '_' => '\\_']);
    }

    /**
     * レシート番号で取引を探す
     */
    public function findByReceiptNo(int $tenantId, string $receiptNo): ?array
    {
        $stmt = $this->pdo->prepare(
            "SELECT `id` FROM `pos_transactions` WHERE `tenant_id` = ? AND `receipt_no` = ?"
        );
        $stmt->execute([$tenantId, $receiptNo]);
        $id = $stmt->fetchColumn();
        return $id === false ? null : $this->findById((int)$id, $tenantId);
    }

    /**
     * 会員ごとの購入実績（取消を除く）
     *
     * @param int[] $memberIds
     * @return array<int, array{count:int, total:int, last_at:?string}>
     */
    public function memberStats(int $tenantId, array $memberIds): array
    {
        $ids = array_values(array_filter(array_map('intval', $memberIds), static fn ($i) => $i > 0));
        if ($ids === []) {
            return [];
        }
        $ph = implode(',', array_fill(0, count($ids), '?'));
        $stmt = $this->pdo->prepare(
            "SELECT `member_id`, COUNT(*) AS cnt, COALESCE(SUM(`total`), 0) AS total, MAX(`created_at`) AS last_at
             FROM `pos_transactions`
             WHERE `tenant_id` = ? AND `status` = 'completed' AND `member_id` IN ($ph)
             GROUP BY `member_id`"
        );
        $stmt->execute(array_merge([$tenantId], $ids));
        $out = [];
        foreach ($stmt->fetchAll() as $r) {
            $out[(int)$r['member_id']] = ['count' => (int)$r['cnt'], 'total' => (int)$r['total'], 'last_at' => $r['last_at']];
        }
        return $out;
    }

    /**
     * レジ明細（会計明細）の検索
     *
     * 取引単位の条件（期間・状態・支払方法・拠点・レジ・会員・担当・レシート番号）に加えて、
     * 明細単位の条件（品名・シリアル番号の部分一致、台帳ID）で絞り込む。
     *
     * @return array{rows: array, total: int, qty: int, amount: int, allocated: int}
     */
    public function searchItems(int $tenantId, array $filters, int $page = 1, int $perPage = 50): array
    {
        [$where, $params] = $this->itemWhere($tenantId, $filters);

        $stmt = $this->pdo->prepare(
            "SELECT COUNT(*) AS cnt,
                    COALESCE(SUM(CASE WHEN t.`status` = 'completed' THEN i.`quantity` END), 0) AS qty,
                    COALESCE(SUM(CASE WHEN t.`status` = 'completed' THEN i.`amount` END), 0) AS amount,
                    COALESCE(SUM(CASE WHEN t.`status` = 'completed' THEN i.`allocated_amount` END), 0) AS allocated
             FROM `pos_transaction_items` i
             JOIN `pos_transactions` t ON t.`id` = i.`transaction_id` AND t.`tenant_id` = i.`tenant_id`
             WHERE {$where}"
        );
        $stmt->execute($params);
        $agg = $stmt->fetch() ?: [];

        $offset = max(0, ($page - 1) * $perPage);
        $stmt = $this->pdo->prepare(
            "SELECT i.*, t.`id` AS tx_id, t.`receipt_no`, t.`created_at`, t.`status`, t.`register_no`,
                    t.`payment_method`, t.`member_code`, t.`member_id`, t.`member_name`, t.`cashier_name`,
                    t.`print_count`, b.name AS branch_name
             FROM `pos_transaction_items` i
             JOIN `pos_transactions` t ON t.`id` = i.`transaction_id` AND t.`tenant_id` = i.`tenant_id`
             LEFT JOIN `branches` b ON b.id = t.branch_id
             WHERE {$where}
             ORDER BY t.`created_at` DESC, t.`id` DESC, i.`line_no` ASC
             LIMIT " . (int)$perPage . " OFFSET " . (int)$offset
        );
        $stmt->execute($params);

        return [
            'rows'      => $stmt->fetchAll(),
            'total'     => (int)($agg['cnt'] ?? 0),
            'qty'       => (int)($agg['qty'] ?? 0),
            'amount'    => (int)($agg['amount'] ?? 0),
            'allocated' => (int)($agg['allocated'] ?? 0),
        ];
    }

    /**
     * 明細検索の WHERE 句（取引の条件 ＋ 明細の条件）
     *
     * @return array{0: string, 1: array}
     */
    private function itemWhere(int $tenantId, array $filters): array
    {
        $keyword  = (string)($filters['keyword'] ?? '');
        $ledgerId = (int)($filters['ledger_id'] ?? 0);
        unset($filters['keyword']); // 取引単位の EXISTS ではなく明細そのものを絞り込む
        [$where, $params] = $this->buildWhere($tenantId, $filters);
        if ($keyword !== '') {
            $where   .= ' AND (i.`item_name` LIKE ? OR i.`serial_number` LIKE ?)';
            $like     = '%' . self::likeEscape($keyword) . '%';
            $params[] = $like;
            $params[] = $like;
        }
        if ($ledgerId > 0) {
            $where   .= ' AND i.`ledger_id` = ?';
            $params[] = $ledgerId;
        }
        return [$where, $params];
    }

    /**
     * 検索条件の WHERE 句
     *
     * @return array{0: string, 1: array}
     */
    private function buildWhere(int $tenantId, array $f): array
    {
        $where  = ['t.`tenant_id` = ?'];
        $params = [$tenantId];

        if (!empty($f['date_from'])) {
            $where[]  = 't.`created_at` >= ?';
            $params[] = $f['date_from'] . ' 00:00:00';
        }
        if (!empty($f['date_to'])) {
            $where[]  = 't.`created_at` < DATE_ADD(?, INTERVAL 1 DAY)';
            $params[] = $f['date_to'];
        }
        if (!empty($f['status']) && in_array($f['status'], ['completed', 'voided'], true)) {
            $where[]  = 't.`status` = ?';
            $params[] = $f['status'];
        }
        if (!empty($f['payment_method'])) {
            $where[]  = 't.`payment_method` = ?';
            $params[] = $f['payment_method'];
        }
        if (isset($f['branch_id']) && $f['branch_id'] !== null && $f['branch_id'] !== '') {
            $where[]  = 't.`branch_id` = ?';
            $params[] = (int)$f['branch_id'];
        }
        if (!empty($f['receipt_no'])) {
            $where[]  = 't.`receipt_no` LIKE ?';
            $params[] = '%' . strtr((string)$f['receipt_no'], ['\\' => '\\\\', '%' => '\\%', '_' => '\\_']) . '%';
        }
        if (!empty($f['register_no'])) {
            $where[]  = 't.`register_no` = ?';
            $params[] = (int)$f['register_no'];
        }
        if (!empty($f['member_id'])) {
            $where[]  = 't.`member_id` = ?';
            $params[] = (int)$f['member_id'];
        }
        if (!empty($f['member'])) {
            // 会員番号の完全一致、または会員名の部分一致
            $where[]  = '(t.`member_code` = ? OR t.`member_name` LIKE ?)';
            $params[] = (string)$f['member'];
            $params[] = '%' . self::likeEscape((string)$f['member']) . '%';
        }
        if (!empty($f['member_code'])) {
            $where[]  = 't.`member_code` = ?';
            $params[] = (string)$f['member_code'];
        }
        if (!empty($f['cashier'])) {
            $where[]  = 't.`cashier_name` LIKE ?';
            $params[] = '%' . self::likeEscape((string)$f['cashier']) . '%';
        }
        if (!empty($f['keyword'])) {
            $where[]  = 'EXISTS (SELECT 1 FROM `pos_transaction_items` i
                                 WHERE i.`transaction_id` = t.`id` AND i.`tenant_id` = t.`tenant_id`
                                   AND (i.`item_name` LIKE ? OR i.`serial_number` LIKE ?))';
            $like = '%' . strtr((string)$f['keyword'], ['\\' => '\\\\', '%' => '\\%', '_' => '\\_']) . '%';
            $params[] = $like;
            $params[] = $like;
        }
        return [implode(' AND ', $where), $params];
    }

    /**
     * 取引履歴の検索
     *
     * @return array{rows: array, total: int, sum_total: int, sum_count: int}
     */
    public function search(int $tenantId, array $filters, int $page = 1, int $perPage = 50): array
    {
        [$where, $params] = $this->buildWhere($tenantId, $filters);

        $stmt = $this->pdo->prepare(
            "SELECT COUNT(*) AS cnt,
                    COALESCE(SUM(CASE WHEN t.`status` = 'completed' THEN t.`total` END), 0) AS sum_total,
                    COALESCE(SUM(CASE WHEN t.`status` = 'completed' THEN 1 END), 0) AS sum_count
             FROM `pos_transactions` t WHERE {$where}"
        );
        $stmt->execute($params);
        $agg = $stmt->fetch() ?: ['cnt' => 0, 'sum_total' => 0, 'sum_count' => 0];

        $offset = max(0, ($page - 1) * $perPage);
        $stmt = $this->pdo->prepare(
            "SELECT t.*, b.name AS branch_name,
                    (SELECT GROUP_CONCAT(i.`item_name` ORDER BY i.`line_no` SEPARATOR '、')
                     FROM `pos_transaction_items` i WHERE i.`transaction_id` = t.`id` AND i.`tenant_id` = t.`tenant_id`) AS item_names
             FROM `pos_transactions` t
             LEFT JOIN `branches` b ON b.id = t.branch_id
             WHERE {$where}
             ORDER BY t.`created_at` DESC, t.`id` DESC
             LIMIT " . (int)$perPage . " OFFSET " . (int)$offset
        );
        $stmt->execute($params);

        return [
            'rows'      => $stmt->fetchAll(),
            'total'     => (int)$agg['cnt'],
            'sum_total' => (int)$agg['sum_total'],
            'sum_count' => (int)$agg['sum_count'],
        ];
    }

    /**
     * CSV 出力用（明細単位）
     */
    public function exportRows(int $tenantId, array $filters, int $limit = 20000, bool $lineFilter = false): array
    {
        // $lineFilter = true: 明細検索の条件（品名・シリアル・台帳IDで明細を絞る）で出力する
        [$where, $params] = $lineFilter ? $this->itemWhere($tenantId, $filters) : $this->buildWhere($tenantId, $filters);
        $stmt = $this->pdo->prepare(
            "SELECT t.`created_at`, t.`receipt_no`, t.`register_no`, t.`status`, t.`payment_method`, t.`member_code`, t.`member_name`,
                    t.`cashier_name`, b.name AS branch_name, t.`subtotal`, t.`discount_amount`, t.`tax_mode`,
                    t.`tax_rate`, t.`tax_amount`, t.`total`, t.`tendered`, t.`change_amount`, t.`voided_at`, t.`void_reason`,
                    i.`line_no`, i.`ledger_id`, i.`item_name`, i.`serial_number`, i.`quantity`, i.`unit_price`,
                    i.`line_discount`, i.`amount`, i.`allocated_amount`
             FROM `pos_transactions` t
             JOIN `pos_transaction_items` i ON i.`transaction_id` = t.`id` AND i.`tenant_id` = t.`tenant_id`
             LEFT JOIN `branches` b ON b.id = t.branch_id
             WHERE {$where}
             ORDER BY t.`created_at` ASC, t.`id` ASC, i.`line_no` ASC
             LIMIT " . (int)$limit
        );
        $stmt->execute($params);
        return $stmt->fetchAll();
    }

    /**
     * 記録のあるレジ番号の一覧（絞り込みの選択肢用）
     *
     * @return int[]
     */
    public function registerNumbers(int $tenantId): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT DISTINCT `register_no` FROM `pos_transactions`
             WHERE `tenant_id` = ? AND `register_no` IS NOT NULL ORDER BY `register_no`"
        );
        $stmt->execute([$tenantId]);
        return array_map('intval', $stmt->fetchAll(\PDO::FETCH_COLUMN));
    }

    /**
     * 日計（レジ精算用の集計）
     *
     * @param int|null $branchId null = 全拠点
     */
    public function dailySummary(int $tenantId, string $date, ?int $branchId, ?int $registerNo = null): array
    {
        $where  = "`tenant_id` = ? AND `created_at` >= ? AND `created_at` < DATE_ADD(?, INTERVAL 1 DAY)";
        $params = [$tenantId, $date . ' 00:00:00', $date];
        if ($branchId !== null) {
            $where   .= " AND `branch_id` = ?";
            $params[] = $branchId;
        }
        if ($registerNo !== null) {
            $where   .= " AND `register_no` = ?";
            $params[] = $registerNo;
        }

        $stmt = $this->pdo->prepare(
            "SELECT `status`, `payment_method`, COUNT(*) AS cnt,
                    COALESCE(SUM(`item_count`), 0) AS items, COALESCE(SUM(`subtotal`), 0) AS subtotal,
                    COALESCE(SUM(`discount_amount`), 0) AS discount, COALESCE(SUM(`tax_amount`), 0) AS tax,
                    COALESCE(SUM(`total`), 0) AS total
             FROM `pos_transactions` WHERE {$where}
             GROUP BY `status`, `payment_method`"
        );
        $stmt->execute($params);

        $sum = [
            'tx_count' => 0, 'item_count' => 0, 'subtotal' => 0, 'discount' => 0, 'tax' => 0, 'total' => 0,
            'void_count' => 0, 'void_total' => 0, 'cash_sales' => 0, 'by_method' => [],
        ];
        foreach (['cash', 'credit', 'emoney', 'qr', 'other'] as $m) {
            $sum['by_method'][$m] = ['count' => 0, 'total' => 0];
        }
        foreach ($stmt->fetchAll() as $r) {
            if ($r['status'] === 'voided') {
                $sum['void_count'] += (int)$r['cnt'];
                $sum['void_total'] += (int)$r['total'];
                continue;
            }
            $sum['tx_count']   += (int)$r['cnt'];
            $sum['item_count'] += (int)$r['items'];
            $sum['subtotal']   += (int)$r['subtotal'];
            $sum['discount']   += (int)$r['discount'];
            $sum['tax']        += (int)$r['tax'];
            $sum['total']      += (int)$r['total'];
            $m = (string)$r['payment_method'];
            if (isset($sum['by_method'][$m])) {
                $sum['by_method'][$m]['count'] += (int)$r['cnt'];
                $sum['by_method'][$m]['total'] += (int)$r['total'];
            }
        }
        $sum['cash_sales'] = $sum['by_method']['cash']['total'];

        // 時間帯別（完了分）
        $stmt = $this->pdo->prepare(
            "SELECT HOUR(`created_at`) AS h, COUNT(*) AS cnt, COALESCE(SUM(`total`), 0) AS total
             FROM `pos_transactions` WHERE {$where} AND `status` = 'completed'
             GROUP BY h ORDER BY h"
        );
        $stmt->execute($params);
        $sum['by_hour'] = [];
        foreach ($stmt->fetchAll() as $r) {
            $sum['by_hour'][(int)$r['h']] = ['count' => (int)$r['cnt'], 'total' => (int)$r['total']];
        }

        // この日に取り消した「前日以前の会計」（返金はこの日のレジから行うため、現金分は理論残高から差し引く）
        $rwhere  = "`tenant_id` = ? AND `status` = 'voided' AND `voided_at` >= ? AND `voided_at` < DATE_ADD(?, INTERVAL 1 DAY) AND `created_at` < ?";
        $rparams = [$tenantId, $date . ' 00:00:00', $date, $date . ' 00:00:00'];
        if ($branchId !== null) {
            $rwhere   .= " AND `branch_id` = ?";
            $rparams[] = $branchId;
        }
        if ($registerNo !== null) {
            $rwhere   .= " AND `register_no` = ?";
            $rparams[] = $registerNo;
        }
        $stmt = $this->pdo->prepare(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(`total`), 0) AS total,
                    COALESCE(SUM(CASE WHEN `payment_method` = 'cash' THEN `total` ELSE 0 END), 0) AS cash
             FROM `pos_transactions` WHERE {$rwhere}"
        );
        $stmt->execute($rparams);
        $rf = $stmt->fetch() ?: [];
        $sum['refund_prev_count'] = (int)($rf['cnt'] ?? 0);
        $sum['refund_prev_total'] = (int)($rf['total'] ?? 0);
        $sum['refund_prev_cash']  = (int)($rf['cash'] ?? 0);

        // 台帳画面から直接登録された販売記録（POS 以外・参考表示）
        try {
            $stmt = $this->pdo->prepare(
                "SELECT COUNT(*) AS cnt, COALESCE(SUM(`quantity`), 0) AS qty, COALESCE(SUM(`sale_amount`), 0) AS total
                 FROM `sales`
                 WHERE `tenant_id` = ? AND `transaction_id` IS NULL
                   AND `sold_at` >= ? AND `sold_at` < DATE_ADD(?, INTERVAL 1 DAY)"
            );
            $stmt->execute([$tenantId, $date . ' 00:00:00', $date]);
            $o = $stmt->fetch() ?: [];
            $sum['other_sales'] = ['count' => (int)($o['cnt'] ?? 0), 'qty' => (int)($o['qty'] ?? 0), 'total' => (int)($o['total'] ?? 0)];
        } catch (\Throwable $e) {
            $sum['other_sales'] = ['count' => 0, 'qty' => 0, 'total' => 0];
        }

        return $sum;
    }
}
