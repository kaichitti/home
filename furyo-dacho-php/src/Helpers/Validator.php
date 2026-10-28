<?php

namespace FuryoDacho\Helpers;

/**
 * 入力バリデーションヘルパー
 * フォームデータの検証ルールを定義・実行する。
 */
class Validator
{
    /** @var array<string, string[]> エラーメッセージ */
    private array $errors = [];

    /** @var array 検証対象データ */
    private array $data;

    /** @var array<string, string> 項目名の表示ラベル（エラーメッセージで英語の項目名の代わりに使う） */
    private array $labels = [];

    public function __construct(array $data, array $labels = [])
    {
        $this->data   = $data;
        $this->labels = $labels;
    }

    /**
     * バリデーションを実行する
     *
     * @param array<string, string> $rules フィールド名 => ルール文字列（'required|max:255|email'形式）
     * @return bool 全ルールを通過した場合 true
     */
    public function validate(array $rules): bool
    {
        $this->errors = [];

        foreach ($rules as $field => $ruleString) {
            $ruleList = explode('|', $ruleString);
            $value    = $this->data[$field] ?? null;

            // フォームの項目はすべて単一の値。配列（name[]=x 等）が送られた場合は不正な入力とし、
            // 以降のルールは適用しない（文字列変換の警告や型エラーによる500エラーを防ぐ）
            if (is_array($value)) {
                $this->addError($field, ($this->labels[$field] ?? $field) . " の形式が正しくありません。");
                continue;
            }

            foreach ($ruleList as $rule) {
                [$ruleName, $param] = array_pad(explode(':', $rule, 2), 2, null);
                $this->applyRule($field, $value, $ruleName, $param);
            }
        }

        return empty($this->errors);
    }

    /**
     * エラーメッセージ一覧を返す
     *
     * @return array<string, string[]>
     */
    public function errors(): array
    {
        return $this->errors;
    }

    /**
     * 最初のエラーメッセージだけをフラットに返す（簡易表示用）
     *
     * @return array<string, string>
     */
    public function firstErrors(): array
    {
        return array_map(fn($msgs) => $msgs[0], $this->errors);
    }

    /**
     * 個別ルールを適用
     */
    private function applyRule(string $fieldKey, $value, string $rule, ?string $param): void
    {
        // メッセージ中の項目名は日本語ラベルがあればそれを使う（以前は「admin_email は必須項目です。」のように表示されていた）
        $field = $this->labels[$fieldKey] ?? $fieldKey;
        switch ($rule) {
            case 'required':
                if ($value === null || $value === '') {
                    $this->addError($fieldKey, "{$field} は必須項目です。");
                }
                break;

            case 'max':
                if ($value !== null && mb_strlen((string)$value) > (int)$param) {
                    $this->addError($fieldKey, "{$field} は {$param} 文字以内で入力してください。");
                }
                break;

            case 'min':
                if ($value !== null && mb_strlen((string)$value) < (int)$param) {
                    $this->addError($fieldKey, "{$field} は {$param} 文字以上で入力してください。");
                }
                break;

            case 'email':
                if ($value !== null && $value !== '' && !filter_var($value, FILTER_VALIDATE_EMAIL)) {
                    $this->addError($fieldKey, "{$field} は正しいメールアドレス形式で入力してください。");
                }
                break;

            case 'numeric':
                if ($value !== null && $value !== '' && !is_numeric($value)) {
                    $this->addError($fieldKey, "{$field} は数値で入力してください。");
                }
                break;

            case 'integer':
                if ($value !== null && $value !== '' && filter_var($value, FILTER_VALIDATE_INT) === false) {
                    $this->addError($fieldKey, "{$field} は整数で入力してください。");
                }
                break;

            case 'date':
                if ($value !== null && $value !== '') {
                    $d = \DateTime::createFromFormat('Y-m-d', $value);
                    if (!$d || $d->format('Y-m-d') !== $value) {
                        $this->addError($fieldKey, "{$field} は YYYY-MM-DD 形式の日付で入力してください。");
                    }
                }
                break;

            case 'in':
                $allowed = explode(',', $param ?? '');
                if ($value !== null && $value !== '' && !in_array($value, $allowed, true)) {
                    $this->addError($fieldKey, "{$field} の値が無効です。");
                }
                break;

            case 'regex':
                if ($value !== null && $value !== '' && !preg_match($param, $value)) {
                    $this->addError($fieldKey, "{$field} の形式が正しくありません。");
                }
                break;
        }
    }

    private function addError(string $field, string $message): void
    {
        $this->errors[$field][] = $message;
    }

    // ----------------------------------------------------------------
    // 静的ユーティリティメソッド（パスワードポリシー・XSS対策・個別チェック用）
    // ----------------------------------------------------------------

    /**
     * XSS対策サニタイズ
     * htmlspecialchars + trim を適用して安全な文字列を返す。
     *
     * @param mixed $value
     * @return string
     */
    public static function sanitize($value): string
    {
        return htmlspecialchars(trim((string)$value), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    }

    /**
     * Y-m-d 形式の日付かチェック
     *
     * @param mixed $value
     * @return bool
     */
    public static function isValidDate($value): bool
    {
        if ($value === null || $value === '') {
            return false;
        }
        $d = \DateTime::createFromFormat('Y-m-d', (string)$value);
        return $d !== false && $d->format('Y-m-d') === (string)$value;
    }

    /**
     * パスワードポリシーを検証し、違反していればエラーメッセージを返す（問題なければ null）
     * 規則: 最小文字数以上・英字と数字をそれぞれ1文字以上・公開されている初期パスワードは不可
     *
     * @param mixed $password
     */
    public static function passwordPolicyError($password, int $minLength = 8): ?string
    {
        if (!is_string($password) || $password === '') {
            return 'パスワードを入力してください。';
        }
        if (strpos($password, "\0") !== false) {
            return 'パスワードに使用できない文字が含まれています。';
        }
        if (strlen($password) > 72) {
            // bcrypt は72バイトを超える部分を無視するため上限を設ける
            return 'パスワードは72バイト（半角72文字）以内で入力してください。';
        }
        if (mb_strlen($password) < $minLength || !self::isAlphaNumeric($password)) {
            return 'パスワードは' . $minLength . '文字以上で、英字・数字をそれぞれ1文字以上含めてください。';
        }
        if (hash_equals(\FuryoDacho\Core\Auth::DEFAULT_PASSWORD, $password)) {
            return '初期パスワード（公開されている値）は使用できません。別のパスワードを設定してください。';
        }
        return null;
    }

    /**
     * 英字と数字が両方含まれるかチェック（パスワードポリシー用）
     *
     * @param mixed $value
     * @return bool
     */
    public static function isAlphaNumeric($value): bool
    {
        $str = (string)$value;
        return preg_match('/[a-zA-Z]/', $str) === 1
            && preg_match('/[0-9]/', $str) === 1;
    }

    /**
     * 最小文字数チェック
     *
     * @param mixed $value
     * @param int   $min
     * @return bool
     */
    public static function hasMinLength($value, int $min): bool
    {
        return mb_strlen((string)$value) >= $min;
    }

    /**
     * 最大文字数チェック
     *
     * @param mixed $value
     * @param int   $max
     * @return bool
     */
    public static function hasMaxLength($value, int $max): bool
    {
        return mb_strlen((string)$value) <= $max;
    }
}
