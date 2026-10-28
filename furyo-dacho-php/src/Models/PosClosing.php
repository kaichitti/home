<?php

namespace FuryoDacho\Models;

/**
 * レジ精算（日計・現金過不足）の記録
 *
 * 精算のたびに1行追加する（やり直した場合も履歴として残し、最新を正とする）。
 */
class PosClosing extends BaseModel
{
    protected string $table = 'pos_closings';

    /** 金種（円） */
    public const DENOMINATIONS = [10000, 5000, 2000, 1000, 500, 100, 50, 10, 5, 1];

    public function create(array $d): int
    {
        $stmt = $this->pdo->prepare(
            "INSERT INTO `pos_closings`
                (`tenant_id`, `branch_id`, `register_no`, `biz_date`, `tx_count`, `sales_total`, `cash_sales`, `opening_float`,
                 `expected_cash`, `counted_cash`, `difference`, `denominations`, `summary`, `note`,
                 `closed_by`, `closed_by_name`)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        );
        $stmt->execute([
            $d['tenant_id'], $d['branch_id'], $d['register_no'] ?? null, $d['biz_date'], $d['tx_count'], $d['sales_total'], $d['cash_sales'],
            $d['opening_float'], $d['expected_cash'], $d['counted_cash'], $d['difference'],
            json_encode($d['denominations'], JSON_UNESCAPED_UNICODE),
            json_encode($d['summary'], JSON_UNESCAPED_UNICODE),
            $d['note'] !== '' ? $d['note'] : null,
            $d['closed_by'], $d['closed_by_name'],
        ]);
        return (int)$this->pdo->lastInsertId();
    }

    public function findById(int $id, int $tenantId): ?array
    {
        $stmt = $this->pdo->prepare(
            "SELECT c.*, b.name AS branch_name FROM `pos_closings` c
             LEFT JOIN `branches` b ON b.id = c.branch_id
             WHERE c.`id` = ? AND c.`tenant_id` = ?"
        );
        $stmt->execute([$id, $tenantId]);
        $row = $stmt->fetch();
        return $row ? self::decode($row) : null;
    }

    /**
     * 指定日の精算履歴（新しい順）
     */
    public function findByDate(int $tenantId, string $date): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT c.*, b.name AS branch_name FROM `pos_closings` c
             LEFT JOIN `branches` b ON b.id = c.branch_id
             WHERE c.`tenant_id` = ? AND c.`biz_date` = ?
             ORDER BY c.`created_at` DESC, c.`id` DESC"
        );
        $stmt->execute([$tenantId, $date]);
        return array_map([self::class, 'decode'], $stmt->fetchAll());
    }

    private static function decode(array $row): array
    {
        foreach (['denominations', 'summary'] as $k) {
            $v = json_decode((string)($row[$k] ?? ''), true);
            $row[$k] = is_array($v) ? $v : [];
        }
        return $row;
    }
}
