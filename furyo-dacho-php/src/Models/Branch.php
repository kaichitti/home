<?php

namespace FuryoDacho\Models;

/**
 * Branch モデル
 * 拠点の管理を担当する。全操作に tenant_id を強制してテナント間分離を保証する。
 */
class Branch extends BaseModel
{
    protected string $table = 'branches';

    /**
     * テナント内の拠点一覧を取得
     *
     * @param int $tenantId
     * @return array
     */
    public function findAllByTenant(int $tenantId): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT * FROM `branches` WHERE `tenant_id` = ? ORDER BY `name` ASC"
        );
        $stmt->execute([$tenantId]);
        return $stmt->fetchAll();
    }

    /**
     * 後方互換: getByTenant() は findAllByTenant() に委譲
     */
    public function getByTenant(int $tenantId): array
    {
        return $this->findAllByTenant($tenantId);
    }

    /**
     * IDとテナントIDで拠点を取得
     *
     * @param int $id
     * @param int $tenantId
     * @return array|null
     */
    public function findById(int $id, int $tenantId): ?array
    {
        $stmt = $this->pdo->prepare(
            "SELECT * FROM `branches` WHERE `id` = ? AND `tenant_id` = ?"
        );
        $stmt->execute([$id, $tenantId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    /**
     * 拠点を作成
     *
     * @param int    $tenantId
     * @param string $name
     * @param string|null $address
     * @return int 生成されたID
     */
    /**
     * 拠点ログインコードが使用済みか
     *
     * ログイン時は拠点ログインコードを「全テナント横断」で検索するため、
     * 一意性もテナント内ではなく全テナント横断で保証する必要がある。
     * 以前はテナント内の重複しか確認しておらず、他テナントと同じコードを
     * 登録するとログインが別テナントへ混線する恐れがあった。
     * また、テナントコードはログイン時に拠点ログインコードより優先されるため、
     * いずれかのテナントコードと同じ値も使用不可とする。
     *
     * @param int      $tenantId  （後方互換のため残している。判定は全テナント横断）
     * @param string   $code
     * @param int|null $excludeId 編集時に除外する自拠点ID
     */
    public function loginCodeExists(int $tenantId, string $code, ?int $excludeId = null): bool
    {
        $sql = "SELECT COUNT(*) FROM `branches` WHERE `login_code` = ?";
        $params = [$code];
        if ($excludeId !== null) { $sql .= " AND `id` != ?"; $params[] = $excludeId; }
        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($params);
        if ((int)$stmt->fetchColumn() > 0) {
            return true;
        }

        $stmt = $this->pdo->prepare("SELECT COUNT(*) FROM `tenants` WHERE `code` = ?");
        $stmt->execute([$code]);
        return (int)$stmt->fetchColumn() > 0;
    }

    public function create(int $tenantId, string $name, ?string $address = null, ?string $loginCode = null): int
    {
        $stmt = $this->pdo->prepare(
            "INSERT INTO `branches` (`tenant_id`, `name`, `address`, `login_code`) VALUES (?, ?, ?, ?)"
        );
        $stmt->execute([$tenantId, $name, $address, $loginCode ?: null]);
        return (int)$this->pdo->lastInsertId();
    }

    /**
     * 拠点情報を更新
     *
     * @param int    $id
     * @param int    $tenantId
     * @param string $name
     * @param string|null $address
     * @return bool
     */
    public function update(int $id, int $tenantId, string $name, ?string $address = null, ?string $loginCode = null): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `branches` SET `name` = ?, `address` = ?, `login_code` = ?, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?"
        );
        return $stmt->execute([$name, $address,
            $loginCode ?: null, $id, $tenantId]);
    }

    /**
     * 拠点を削除
     * 所属ユーザーが存在する場合は例外をスローする。
     *
     * @param int $id
     * @param int $tenantId
     * @return bool
     * @throws \RuntimeException 所属ユーザーが存在する場合
     */
    public function delete(int $id, int $tenantId): bool
    {
        // 所属ユーザーが存在するか確認。
        // 無効化したユーザーも外部キーで拠点を参照しているため数える
        // （以前は有効なユーザーだけを数えており、無効化したユーザーが残っていると
        //   削除の実行時に外部キー制約エラーとなって 500 エラーになっていた）
        $stmt = $this->pdo->prepare(
            "SELECT SUM(`is_active` = 1) AS active_cnt, SUM(`is_active` <> 1) AS inactive_cnt
             FROM `users` WHERE `branch_id` = ? AND `tenant_id` = ?"
        );
        $stmt->execute([$id, $tenantId]);
        $row = $stmt->fetch() ?: [];
        if ((int)($row['active_cnt'] ?? 0) > 0) {
            throw new \RuntimeException('この拠点には所属ユーザーが存在するため削除できません。先にユーザー管理で所属拠点を変更してください。');
        }
        if ((int)($row['inactive_cnt'] ?? 0) > 0) {
            throw new \RuntimeException('この拠点には無効化したユーザーが所属しているため削除できません。ユーザー管理でそのユーザーの所属拠点を変更してください。');
        }

        // 台帳レコードが紐づいていないか確認（削除済みの台帳も法定帳簿の記録として残るため含める）
        $stmt2 = $this->pdo->prepare(
            "SELECT SUM(`deleted_at` IS NULL) AS live_cnt, COUNT(*) AS all_cnt
             FROM `ledgers` WHERE `branch_id` = ? AND `tenant_id` = ?"
        );
        $stmt2->execute([$id, $tenantId]);
        $row2 = $stmt2->fetch() ?: [];
        if ((int)($row2['live_cnt'] ?? 0) > 0) {
            throw new \RuntimeException('この拠点には台帳レコードが存在するため削除できません。');
        }
        if ((int)($row2['all_cnt'] ?? 0) > 0) {
            throw new \RuntimeException('この拠点には削除済みの台帳レコード（記録として保存されています）が紐づいているため削除できません。名称を変更してご利用ください。');
        }

        try {
            $stmt3 = $this->pdo->prepare(
                "DELETE FROM `branches` WHERE `id` = ? AND `tenant_id` = ?"
            );
            return $stmt3->execute([$id, $tenantId]);
        } catch (\PDOException $e) {
            // 上記以外の参照（外部キー）が残っている場合も 500 エラーにせず案内する
            if ((int)($e->errorInfo[1] ?? 0) === 1451) {
                throw new \RuntimeException('この拠点は他のデータから参照されているため削除できません。');
            }
            throw $e;
        }
    }
}
