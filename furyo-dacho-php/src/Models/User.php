<?php

namespace FuryoDacho\Models;

/**
 * User モデル
 * テナントユーザーの認証・管理を担当する。
 * 全操作に tenant_id フィルタを強制してテナント間分離を保証する。
 */
class User extends BaseModel
{
    protected string $table = 'users';

    /**
     * テナント内のユーザー一覧を取得
     */
    public function getByTenant(int $tenantId): array
    {
        // 所属拠点名も返す（以前は拠点名を取得しておらず、ユーザー一覧の「所属拠点」が常に「-」だった）
        $stmt = $this->pdo->prepare(
            "SELECT u.`id`, u.`branch_id`, u.`display_name`, u.`email`, u.`role`, u.`is_owner`, u.`is_active`,
                    u.`must_change_password`, u.`failed_login_attempts`, u.`locked_until`,
                    (u.`locked_until` IS NOT NULL AND u.`locked_until` > NOW()) AS `is_locked`,
                    u.`last_login_at`, u.`created_at`, b.`name` AS `branch_name`
             FROM `users` u
             LEFT JOIN `branches` b ON b.`id` = u.`branch_id` AND b.`tenant_id` = u.`tenant_id`
             WHERE u.`tenant_id` = ? ORDER BY u.`is_active` DESC, u.`display_name` ASC"
        );
        $stmt->execute([$tenantId]);
        return $stmt->fetchAll();
    }

    /**
     * メールアドレスとテナントIDでユーザーを取得（ログイン用・is_activeフィルタなし）
     * ロック中のユーザーも取得して呼び出し側で判定する。
     */
    public function findByEmail(int $tenantId, string $email): ?array
    {
        $stmt = $this->pdo->prepare(
            "SELECT * FROM `users` WHERE `tenant_id` = ? AND `email` = ?"
        );
        $stmt->execute([$tenantId, $email]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    /**
     * IDとテナントIDでユーザーを取得（テナント間アクセス防止）
     */
    public function findById(int $id, int $tenantId): ?array
    {
        $stmt = $this->pdo->prepare(
            "SELECT * FROM `users` WHERE `id` = ? AND `tenant_id` = ?"
        );
        $stmt->execute([$id, $tenantId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    /**
     * ユーザーを作成（パスワードはbcryptでハッシュ化）
     *
     * @return int 生成されたID
     */
    public function create(array $data): int
    {
        $stmt = $this->pdo->prepare(
            "INSERT INTO `users`
             (`tenant_id`, `branch_id`, `display_name`, `email`, `password_hash`, `role`, `is_active`, `must_change_password`)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        );
        $stmt->execute([
            $data['tenant_id'],
            $data['branch_id'] ?? null,
            $data['display_name'],
            $data['email'],
            password_hash($data['password'], PASSWORD_BCRYPT),
            $data['role'] ?? 'user',
            $data['is_active'] ?? 1,
            $data['must_change_password'] ?? 1,
        ]);
        return (int)$this->pdo->lastInsertId();
    }

    /**
     * ユーザー情報を更新
     */
    public function update(int $id, int $tenantId, array $data): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `users`
             SET `display_name` = ?, `email` = ?, `role` = ?, `is_active` = COALESCE(?, `is_active`),
                 `branch_id` = ?, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?"
        );
        // is_active が null（未指定）なら現在の値を変えない
        // （読み取り後に別の管理者が無効化した場合に、古い値で書き戻さないため）
        return $stmt->execute([
            $data['display_name'],
            $data['email'],
            $data['role'],
            $data['is_active'] ?? null,
            $data['branch_id'] ?? null,
            $id,
            $tenantId,
        ]);
    }

    /**
     * ユーザーを無効化（is_active = 0）
     */
    public function deactivate(int $id, int $tenantId): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `users` SET `is_active` = 0, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?"
        );
        return $stmt->execute([$id, $tenantId]);
    }

    /**
     * ユーザーを再有効化（is_active = 1）。ロック状態も初期化する
     */
    public function activate(int $id, int $tenantId): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `users` SET `is_active` = 1, `failed_login_attempts` = 0, `locked_until` = NULL,
                    `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?"
        );
        return $stmt->execute([$id, $tenantId]);
    }

    /**
     * テナント内の全ユーザーを無効化（テナント削除時に使用）
     */
    public function deactivateAllByTenant(int $tenantId): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `users` SET `is_active` = 0, `updated_at` = NOW() WHERE `tenant_id` = ?"
        );
        return $stmt->execute([$tenantId]);
    }

    /**
     * メールアドレス（ログインID）を変更
     */
    public function changeEmail(int $id, int $tenantId, string $newEmail): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `users` SET `email` = ?, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?"
        );
        return $stmt->execute([$newEmail, $id, $tenantId]);
    }

    /**
     * パスワードを変更（bcryptハッシュ化・must_change_passwordをクリア）
     */
    public function changePassword(int $id, int $tenantId, string $newPassword): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `users`
             SET `password_hash` = ?, `must_change_password` = 0, `failed_login_attempts` = 0,
                 `locked_until` = NULL, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?"
        );
        return $stmt->execute([
            password_hash($newPassword, PASSWORD_BCRYPT),
            $id,
            $tenantId,
        ]);
    }

    /**
     * パスワードを更新（旧名・後方互換）
     */
    /**
     * 管理者によるパスワード再設定（仮パスワードを設定し、次回ログイン時に変更を求める）
     * あわせてアカウントロックを解除する。
     */
    public function resetPassword(int $id, int $tenantId, string $tempPassword): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `users`
             SET `password_hash` = ?, `must_change_password` = 1, `failed_login_attempts` = 0,
                 `locked_until` = NULL, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?"
        );
        return $stmt->execute([password_hash($tempPassword, PASSWORD_BCRYPT), $id, $tenantId]);
    }

    /**
     * アカウントロックを解除する（失敗回数もリセット）
     */
    public function unlock(int $id, int $tenantId): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `users` SET `failed_login_attempts` = 0, `locked_until` = NULL, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?"
        );
        return $stmt->execute([$id, $tenantId]);
    }

    public function updatePassword(int $id, int $tenantId, string $plainPassword): bool
    {
        return $this->changePassword($id, $tenantId, $plainPassword);
    }

    /**
     * ログイン失敗回数をリセット
     */
    public function resetFailedAttempts(int $id): void
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `users` SET `failed_login_attempts` = 0, `locked_until` = NULL WHERE `id` = ?"
        );
        $stmt->execute([$id]);
    }

    /**
     * 期限切れのロックを解除する（回数もリセット）
     */
    public function expireLock(int $id): void
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `users` SET `failed_login_attempts` = 0, `locked_until` = NULL
             WHERE `id` = ? AND `locked_until` IS NOT NULL AND `locked_until` <= NOW()"
        );
        $stmt->execute([$id]);
    }

    /**
     * パスワード照合の「前」に試行1回分を原子的に予約する
     *
     * ロックされていなければ失敗回数を1増やし（5回目でロックを設定）true を返す。
     * ロック中なら何もせず false を返す。照合後に回数を増やす方式では、同時に大量の
     * リクエストを送ると記録前に全リクエストが判定を通過してしまうため、
     * 1文の UPDATE で「判定と加算」を同時に行う。成功時は resetFailedAttempts() で戻す。
     *
     * SET 句の評価順（MySQL は左から順・更新後の値を参照）に依存しないよう、
     * locked_until の式は failed_login_attempts（未更新）だけを、
     * failed_login_attempts の式は自分自身だけを参照する。
     */
    public function reserveAttempt(int $id): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `users`
             SET `locked_until` = CASE
                     WHEN `failed_login_attempts` + 1 >= 5 THEN DATE_ADD(NOW(), INTERVAL 30 MINUTE)
                     ELSE NULL
                 END,
                 `failed_login_attempts` = LEAST(`failed_login_attempts` + 1, 255)
             WHERE `id` = ? AND `locked_until` IS NULL"
        );
        $stmt->execute([$id]);
        return $stmt->rowCount() > 0;
    }

    /**
     * パスワードハッシュを差し替える（ログイン時の再ハッシュ用）
     */
    public function updatePasswordHash(int $id, string $hash, ?string $oldHash = null): void
    {
        if ($oldHash === null) {
            $stmt = $this->pdo->prepare("UPDATE `users` SET `password_hash` = ? WHERE `id` = ?");
            $stmt->execute([$hash, $id]);
            return;
        }
        // 旧ハッシュが一致する場合のみ更新（照合中の別操作によるパスワード変更を上書きしない）
        $stmt = $this->pdo->prepare(
            "UPDATE `users` SET `password_hash` = ? WHERE `id` = ? AND `password_hash` = ?"
        );
        $stmt->execute([$hash, $id, $oldHash]);
    }

    /**
     * 初期パスワードのまま利用されているアカウントに変更を強制する
     */
    public function requirePasswordChange(int $id): void
    {
        $stmt = $this->pdo->prepare("UPDATE `users` SET `must_change_password` = 1 WHERE `id` = ?");
        $stmt->execute([$id]);
    }

    /**
     * アカウントが現在ロック中か（期限判定はDB側の現在時刻で行う）
     *
     * locked_until はDBの NOW() で書き込まれるため、PHP側の strtotime() と
     * 比較するとDBとPHPのタイムゾーン差の分だけ判定がずれる。DB側で比較する。
     */
    public function isLocked(int $id): bool
    {
        $stmt = $this->pdo->prepare(
            "SELECT (`locked_until` IS NOT NULL AND `locked_until` > NOW()) FROM `users` WHERE `id` = ?"
        );
        $stmt->execute([$id]);
        return (int)$stmt->fetchColumn() === 1;
    }

    /**
     * ログイン失敗回数をインクリメント
     * 5回連続失敗でアカウントを30分ロック
     *
     * 注意: MySQL/MariaDB の単一テーブル UPDATE は SET 句を左から順に評価し、
     * 後続の式では更新後の値が参照される。以前は回数を先に加算してから
     * 「加算後の値 + 1 >= 5」を判定していたため、実際には4回目の失敗でロックされていた。
     * locked_until を先に（加算前の値で）判定するよう順序を入れ替えて修正。
     * また TINYINT UNSIGNED（最大255）の範囲外エラーを避けるため上限で頭打ちにする。
     */
    public function incrementFailedAttempts(int $id): void
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `users`
             SET `locked_until` = CASE
                     WHEN `failed_login_attempts` + 1 >= 5 THEN DATE_ADD(NOW(), INTERVAL 30 MINUTE)
                     ELSE `locked_until`
                 END,
                 `failed_login_attempts` = LEAST(`failed_login_attempts` + 1, 255)
             WHERE `id` = ?"
        );
        $stmt->execute([$id]);
    }

    /**
     * 最終ログイン日時を更新
     */
    public function updateLastLogin(int $id): void
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `users` SET `last_login_at` = NOW() WHERE `id` = ?"
        );
        $stmt->execute([$id]);
    }
}
