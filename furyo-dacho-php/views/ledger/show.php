<?php
$pageTitle  = '台帳詳細 - 古物台帳管理システム';
$activePage = 'ledger';

$transactionTypeLabels = [
    'buy'         => '買取',
    'exchange'    => '交換',
    'consignment' => '委託販売受け',
    'other'       => 'その他',
];
$itemTypeLabels = [
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
$idDocumentTypeLabels = [
    'driver_license'    => '運転免許証',
    'my_number'         => 'マイナンバーカード',
    'passport'          => 'パスポート',
    'health_insurance'  => '健康保険証',
    'residence_card'    => '住民基本台帳カード',
    'residence_status'  => '在留カード',
    'special_permanent' => '特別永住者証明書',
    'other'             => 'その他',
];

ob_start();
?>

<!-- アクションボタン -->
<div class="page-header">
    <h1 class="page-header__title">
        台帳詳細
        <span style="font-size: 0.85rem; font-weight: 400; color: #6c757d; margin-left: 8px;">
            #<?= (int)($ledger['id'] ?? 0) ?>
        </span>
    </h1>
    <div class="page-header__actions">
        <a href="/index.php?page=ledger" class="btn btn-outline">&#8592; 一覧に戻る</a>
        <?php if (!empty($canEdit)): ?>
        <a href="/index.php?page=ledger.edit&id=<?= (int)$ledger['id'] ?>" class="btn btn-accent">編集</a>
        <?php endif; ?>
        <?php if (!empty($isAdmin)): ?>
        <button type="button" class="btn btn-danger" data-modal-open="deleteModal">削除</button>
        <?php endif; ?>
    </div>
</div>

<!-- ============================================================
     システム情報
============================================================ -->
<?php $apv = $ledger['approval_status'] ?? 'none'; ?>
<?php if ($apv === 'pending'): ?>
<div class="alert alert-danger" style="display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;">
    <div>
        <b>&#9888; 管理者の承認待ち</b><br>
        <span style="font-size:.85rem;">本人確認情報が未登録かつ相手方が未認証（本人確認済み会員に紐付いていない）の売買記録です。内容を確認して承認してください。</span>
    </div>
    <?php if (!empty($isAdmin)): ?>
    <form method="POST" action="/index.php?page=ledger.approve" style="margin:0;">
        <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
        <input type="hidden" name="id" value="<?= (int)$ledger['id'] ?>">
        <button type="submit" class="btn btn-primary"
                onclick="return confirm('この台帳を承認しますか？\n（内容と相手方を確認済みであることを確認してください）')">
            &#10003; 承認する
        </button>
    </form>
    <?php endif; ?>
</div>
<?php elseif ($apv === 'approved'): ?>
<div class="alert alert-success" style="font-size:.85rem;">
    &#10003; この台帳は管理者により承認済みです<?= !empty($ledger['approved_at']) ? '（' . htmlspecialchars($ledger['approved_at']) . '）' : '' ?>。
</div>
<?php endif; ?>

<div class="card">
    <div class="card__header">システム情報</div>
    <div class="card__body" style="padding: 0;">
        <table class="detail-table">
            <tr>
                <th>台帳ID</th>
                <td><span style="font-family: monospace;">#<?= (int)($ledger['id'] ?? 0) ?></span></td>
            </tr>
            <tr>
                <th>登録日時</th>
                <td><?= htmlspecialchars($ledger['created_at'] ?? '') ?></td>
            </tr>
            <tr>
                <th>登録者</th>
                <td><?= htmlspecialchars($ledger['registered_by_name'] ?? '') ?: '-' ?></td>
            </tr>
            <tr>
                <th>所属拠点</th>
                <td><?= htmlspecialchars($ledger['branch_name'] ?? '') ?></td>
            </tr>
            <tr>
                <th>最終更新者</th>
                <td><?= htmlspecialchars($ledger['updated_by_name'] ?? '') ?: '-' ?></td>
            </tr>
            <tr>
                <th>最終更新日時</th>
                <td><?= htmlspecialchars($ledger['updated_at'] ?? '') ?></td>
            </tr>
        </table>
    </div>
</div>

<!-- ============================================================
     取引情報
============================================================ -->
<div class="card">
    <div class="card__header">取引情報</div>
    <div class="card__body" style="padding: 0;">
        <table class="detail-table">
            <tr>
                <th>取引年月日</th>
                <td><?= htmlspecialchars($ledger['transaction_date'] ?? '') ?></td>
            </tr>
            <tr>
                <th>取引種別</th>
                <td>
                    <?php
                    $txType = $ledger['transaction_type'] ?? '';
                    echo htmlspecialchars($transactionTypeLabels[$txType] ?? $txType);
                    if ($txType === 'other' && !empty($ledger['transaction_type_note'])):
                    ?>
                        <span class="text-muted">（<?= htmlspecialchars($ledger['transaction_type_note']) ?>）</span>
                    <?php endif; ?>
                </td>
            </tr>
            <tr>
                <th>古物の種類</th>
                <td>
                    <?php
                    $iType = $ledger['item_category'] ?? '';
                    echo htmlspecialchars(\FuryoDacho\Models\ItemCategory::label($iType, $ledger['item_category_note'] ?? null));
                    ?>
                </td>
            </tr>
            <tr>
                <th>品目</th>
                <td><?= htmlspecialchars($ledger['item_name'] ?? '') ?></td>
            </tr>
            <?php if (!empty($ledger['serial_number'])): ?>
            <tr>
                <th>シリアル番号</th>
                <td><?= htmlspecialchars($ledger['serial_number']) ?></td>
            </tr>
            <?php endif; ?>
            <tr>
                <th>特徴・説明</th>
                <td style="white-space: pre-wrap;"><?= ($ledger['item_description'] ?? '') !== '' ? htmlspecialchars((string)$ledger['item_description']) : '<span class="text-muted">-</span>' ?></td>
            </tr>
            <tr>
                <th>数量</th>
                <td><?= number_format((int)($ledger['quantity'] ?? 0)) ?> 点</td>
            </tr>
            <tr>
                <th>取引金額</th>
                <td>
                    <?php if (isset($ledger['transaction_amount']) && $ledger['transaction_amount'] !== ''): ?>
                        &#165;<?= number_format((float)$ledger['transaction_amount']) ?>
                    <?php else: ?>
                        -
                    <?php endif; ?>
                </td>
            </tr>
            <?php if (isset($ledger['sale_price']) && $ledger['sale_price'] !== null && $ledger['sale_price'] !== ''): ?>
            <tr>
                <th>販売予定価格</th>
                <td>&#165;<?= number_format((float)$ledger['sale_price']) ?> <span class="text-muted" style="font-size:.8rem;">（POSレジの単価の初期値）</span></td>
            </tr>
            <?php endif; ?>
        </table>
    </div>
</div>

<!-- ============================================================
     相手方情報
============================================================ -->
<div class="card">
    <div class="card__header">相手方情報</div>
    <div class="card__body" style="padding: 0;">
        <?php $isCorporate = ($ledger['counterpart_type'] ?? 'individual') === 'corporate'; ?>
        <table class="detail-table">
            <tr>
                <th>区分</th>
                <td>
                    <span class="badge <?= $isCorporate ? 'badge-secondary' : 'badge-primary' ?>">
                        <?= $isCorporate ? '法人' : '個人' ?>
                    </span>
                </td>
            </tr>
            <?php if (!empty($ledger['member_code'])): ?>
            <tr>
                <th>会員番号</th>
                <td><?= htmlspecialchars($ledger['member_code']) ?></td>
            </tr>
            <?php endif; ?>
            <tr>
                <th><?= $isCorporate ? '名称' : '氏名' ?></th>
                <td><?= htmlspecialchars($ledger['counterpart_name'] ?? '') ?></td>
            </tr>
            <?php if ($isCorporate): ?>
            <tr>
                <th>担当者名</th>
                <td><?= htmlspecialchars($ledger['counterpart_contact_name'] ?? '-') ?></td>
            </tr>
            <?php endif; ?>
            <tr>
                <th><?= $isCorporate ? '所在地' : '住所' ?></th>
                <td><?= htmlspecialchars($ledger['counterpart_address'] ?? '') ?></td>
            </tr>
            <?php if (!$isCorporate): ?>
            <tr>
                <th>職業</th>
                <td><?= htmlspecialchars($ledger['counterpart_occupation'] ?? '-') ?></td>
            </tr>
            <tr>
                <th>年齢</th>
                <td><?= $ledger['counterpart_age'] !== null && $ledger['counterpart_age'] !== '' ? htmlspecialchars((string)$ledger['counterpart_age']) . ' 歳' : '-' ?></td>
            </tr>
            <?php endif; ?>
            <tr>
                <th>電話番号</th>
                <td><?= htmlspecialchars($ledger['counterpart_phone'] ?? '-') ?></td>
            </tr>
            <?php if (!empty($ledger['counterpart_account'])): ?>
            <tr>
                <th>取引アカウント</th>
                <td><?= htmlspecialchars($ledger['counterpart_account']) ?></td>
            </tr>
            <?php endif; ?>
            <?php if (!empty($ledger['counterpart_note'])): ?>
            <tr>
                <th>備考</th>
                <td style="white-space: pre-wrap;"><?= htmlspecialchars($ledger['counterpart_note']) ?></td>
            </tr>
            <?php endif; ?>
        </table>
    </div>
</div>

<!-- ============================================================
     本人確認情報
============================================================ -->
<div class="card">
    <div class="card__header">本人確認情報</div>
    <div class="card__body" style="padding: 0;">
        <table class="detail-table">
            <tr>
                <th>確認書類種別</th>
                <td>
                    <?php
                    $docType = $ledger['id_document_type'] ?? '';
                    if ($docType === '' || $docType === null) {
                        echo '<span class="badge badge-danger">&#9888; 未登録</span> <span class="text-muted" style="font-size:.8rem;">本人確認情報が登録されていません</span>';
                    } else {
                        echo htmlspecialchars($idDocumentTypeLabels[$docType] ?? (string)$docType);
                    }
                    if ($docType === 'other' && !empty($ledger['id_document_type_note'])):
                    ?>
                        <span class="text-muted">（<?= htmlspecialchars($ledger['id_document_type_note']) ?>）</span>
                    <?php endif; ?>
                </td>
            </tr>
            <tr>
                <th>書類番号・記号</th>
                <td><?= ($ledger['id_document_number'] ?? '') !== '' ? htmlspecialchars((string)$ledger['id_document_number']) : '<span class="text-muted">-</span>' ?></td>
            </tr>
        </table>
    </div>
</div>

<!-- ============================================================
     在庫・販売記録
============================================================ -->
<?php
$qtyTotal   = (int)($ledger['quantity'] ?? 1);
$soldQ      = (int)($soldQuantity ?? 0);
$remainQ    = (int)($remaining ?? $qtyTotal);
$saleTotal  = 0;
foreach (($sales ?? []) as $sr) { $saleTotal += (int)($sr['sale_amount'] ?? 0); }
?>
<div class="card">
    <div class="card__header">在庫・販売記録</div>
    <div class="card__body">
        <div style="display:flex; gap:20px; flex-wrap:wrap; margin-bottom:14px;">
            <div>
                <div class="text-muted" style="font-size:.75rem;">仕入数量</div>
                <div style="font-weight:700;"><?= $qtyTotal ?> 点</div>
            </div>
            <div>
                <div class="text-muted" style="font-size:.75rem;">販売済</div>
                <div style="font-weight:700;"><?= $soldQ ?> 点</div>
            </div>
            <div>
                <div class="text-muted" style="font-size:.75rem;">残在庫</div>
                <div style="font-weight:700;">
                    <?php if ($remainQ === 0): ?>
                        <span class="badge badge-danger">売切</span>
                    <?php else: ?>
                        <span class="badge badge-success"><?= $remainQ ?> 点</span>
                    <?php endif; ?>
                </div>
            </div>
            <div>
                <div class="text-muted" style="font-size:.75rem;">売上合計</div>
                <div style="font-weight:700; color:#27ae60;">¥<?= number_format($saleTotal) ?></div>
            </div>
        </div>

        <?php if (!empty($sales)): ?>
        <div class="table-wrap">
            <table class="table table--striped">
                <thead>
                    <tr>
                        <th>販売日時</th>
                        <th style="text-align:right;">個数</th>
                        <th style="text-align:right;">販売金額</th>
                        <th>会員番号</th>
                        <th>備考</th>
                        <th>記録者</th>
                        <?php if (!empty($isAdmin)): ?><th style="width:120px;"></th><?php endif; ?>
                    </tr>
                </thead>
                <tbody>
                    <?php foreach ($sales as $sr): ?>
                    <tr>
                        <td><?= htmlspecialchars($sr['sold_at'] ?? '') ?></td>
                        <td style="text-align:right;"><?= (int)$sr['quantity'] ?></td>
                        <td style="text-align:right;"><?= $sr['sale_amount'] !== null ? '¥' . number_format((float)$sr['sale_amount']) : '-' ?></td>
                        <td style="font-size:.8rem;"><?= htmlspecialchars($sr['member_code'] ?? '') ?: '-' ?></td>
                        <td style="font-size:.8rem;"><?= htmlspecialchars($sr['note'] ?? '') ?>
                            <?php if (!empty($sr['transaction_id'])): ?>
                                <br><a href="/index.php?page=pos.show&id=<?= (int)$sr['transaction_id'] ?>">POSレシート <?= htmlspecialchars($sr['pos_receipt_no'] ?? ('#' . $sr['transaction_id'])) ?></a>
                            <?php endif; ?>
                        </td>
                        <td style="font-size:.8rem;"><?= htmlspecialchars($sr['created_by_name'] ?? '-') ?></td>
                        <?php if (!empty($isAdmin)): ?>
                        <td>
                            <?php if (!empty($sr['transaction_id'])): ?>
                            <a href="/index.php?page=pos.show&id=<?= (int)$sr['transaction_id'] ?>"
                               class="btn btn-secondary btn-sm" title="POSで会計した販売は取引詳細から取消します">POS取引</a>
                            <?php else: ?>
                            <a href="/index.php?page=ledger.sale.edit&sale_id=<?= (int)$sr['id'] ?>"
                               class="btn btn-secondary btn-sm">編集</a>
                            <form method="POST" action="/index.php?page=ledger.sale.delete" style="display:inline;">
                                <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
                                <input type="hidden" name="sale_id" value="<?= (int)$sr['id'] ?>">
                                <button type="submit" class="btn btn-secondary btn-sm"
                                        onclick="return confirm('この販売記録を削除しますか？\n（在庫数が戻ります）')">削除</button>
                            </form>
                            <?php endif; ?>
                        </td>
                        <?php endif; ?>
                    </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        </div>
        <?php endif; ?>

        <?php if ($remainQ > 0): ?>
        <!-- 販売記録の追加 -->
        <form method="POST" action="/index.php?page=ledger.sale.store"
              style="display:flex; gap:8px; flex-wrap:wrap; align-items:flex-end; margin-top:12px; padding-top:12px; border-top:1px solid #eee;">
            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
            <input type="hidden" name="id" value="<?= (int)$ledger['id'] ?>">
            <div class="form-group" style="margin:0;">
                <label class="form-label" style="font-size:.75rem;">個数（残<?= $remainQ ?>）</label>
                <input type="number" name="quantity" class="form-control" value="1" min="1" max="<?= $remainQ ?>" style="width:90px;" required>
            </div>
            <div class="form-group" style="margin:0;">
                <label class="form-label" style="font-size:.75rem;">販売金額（円・合計）</label>
                <input type="text" name="sale_amount" class="form-control" inputmode="numeric" placeholder="例：15000" style="width:130px;">
            </div>
            <div class="form-group" style="margin:0;">
                <label class="form-label" style="font-size:.75rem;">販売日時（空欄=現在）</label>
                <input type="datetime-local" name="sold_at" class="form-control" style="width:200px;">
            </div>
            <div class="form-group" style="margin:0;">
                <label class="form-label" style="font-size:.75rem;">会員番号（任意）</label>
                <input type="text" name="member_code" class="form-control" maxlength="50" placeholder="例：M-0001" style="width:130px;">
            </div>
            <div class="form-group" style="margin:0; flex:1; min-width:160px;">
                <label class="form-label" style="font-size:.75rem;">備考</label>
                <input type="text" name="note" class="form-control" maxlength="512" placeholder="販売先・チャネル等（任意）">
            </div>
            <button type="submit" class="btn btn-primary">販売を記録</button>
        </form>
        <?php else: ?>
        <p class="text-muted" style="font-size:.8rem; margin-top:8px;">この商品は売切です。販売記録を削除すると在庫が戻ります。</p>
        <?php endif; ?>
    </div>
</div>

<!-- ============================================================
     商品画像
============================================================ -->
<?php if (!empty($itemPhotos)): ?>
<div class="card">
    <div class="card__header">商品画像（<?= count($itemPhotos) ?>点）</div>
    <div class="card__body">
        <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(140px, 1fr)); gap:12px;">
            <?php foreach ($itemPhotos as $ph): ?>
            <a href="/index.php?page=file.download&id=<?= (int)$ph['id'] ?>&inline=1" target="_blank" rel="noopener"
               style="display:block; text-decoration:none;"
               title="<?= htmlspecialchars($ph['original_filename']) ?>（クリックで拡大表示）">
                <img src="/index.php?page=file.download&id=<?= (int)$ph['id'] ?>&inline=1"
                     alt="<?= htmlspecialchars($ph['original_filename']) ?>"
                     loading="lazy"
                     style="width:100%; height:140px; object-fit:cover; border-radius:6px; border:1px solid #e0e4ea; background:#f4f5f7;">
                <span style="display:block; font-size:.7rem; color:#666; margin-top:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                    <?= htmlspecialchars($ph['original_filename']) ?>
                </span>
            </a>
            <?php endforeach; ?>
        </div>
    </div>
</div>
<?php endif; ?>

<!-- ============================================================
     添付ファイル（本人確認書類・買取受付表）
============================================================ -->
<div class="card">
    <div class="card__header">添付ファイル</div>
    <div class="card__body">
        <?php if (!empty($ledger['has_id_document']) || !empty($ledger['has_receipt_form'])): ?>
        <div class="d-flex gap-8" style="flex-wrap: wrap;">
            <?php if (!empty($ledger['has_id_document'])): ?>
            <a href="/index.php?page=file.download&id=<?= (int)$ledger['id'] ?>&type=id_document"
               class="btn btn-outline btn-sm">
                &#128196; 本人確認書類をダウンロード
            </a>
            <?php endif; ?>
            <?php if (!empty($ledger['has_receipt_form'])): ?>
            <a href="/index.php?page=file.download&id=<?= (int)$ledger['id'] ?>&type=receipt_form"
               class="btn btn-outline btn-sm">
                &#128196; 買取受付表をダウンロード
            </a>
            <?php endif; ?>
        </div>
        <?php else: ?>
        <p class="text-muted" style="font-size: 0.875rem;">添付ファイルはありません。</p>
        <?php endif; ?>
    </div>
</div>

<!-- ============================================================
     削除確認モーダル
============================================================ -->
<?php if (!empty($isAdmin)): ?>
<div class="modal-overlay" id="deleteModal">
    <div class="modal">
        <div class="modal__header">
            <span class="modal__title">削除の確認</span>
            <button class="modal__close" data-modal-close aria-label="閉じる">&#10005;</button>
        </div>
        <div class="modal__body">
            <p style="margin-bottom: 16px;">
                この操作は取り消せません。パスワードを入力してください。
            </p>
            <form method="POST" action="/index.php?page=ledger.delete" id="deleteForm">
                <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
                <input type="hidden" name="id" value="<?= (int)($ledger['id'] ?? 0) ?>">
                <div class="form-group">
                    <label class="form-label" for="delete_password">パスワード</label>
                    <input type="password" id="delete_password" name="confirm_password"
                           class="form-control" autocomplete="current-password" required>
                </div>
            </form>
        </div>
        <div class="modal__footer">
            <button type="button" class="btn btn-secondary" data-modal-close>キャンセル</button>
            <button type="submit" form="deleteForm" class="btn btn-danger">削除する</button>
        </div>
    </div>
</div>
<?php endif; ?>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
