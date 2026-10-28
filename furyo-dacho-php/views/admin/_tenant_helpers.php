<?php
/**
 * システム管理画面の共通表示ヘルパー（テナントの種別・状態のラベル）
 */
if (!function_exists('furyo_admin_status_badge')) {
    function furyo_admin_status_badge(string $status): string
    {
        $map = [
            'active'    => ['badge-success', '有効'],
            'suspended' => ['badge-warning', '停止中'],
            'deleted'   => ['badge-secondary', '削除済み'],
        ];
        [$cls, $label] = $map[$status] ?? ['badge-secondary', $status];
        return '<span class="badge ' . $cls . '">' . htmlspecialchars($label, ENT_QUOTES, 'UTF-8') . '</span>';
    }

    function furyo_admin_type_label(string $type): string
    {
        return $type === 'own' ? '自社' : '顧客';
    }
}
