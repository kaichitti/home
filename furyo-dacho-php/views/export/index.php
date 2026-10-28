<?php
$pageTitle  = 'CSV・PDF出力 - 古物台帳管理システム';
$activePage = 'export';

// 古物の種類はコントローラーから渡される（法定13区分 + 独自区分 + その他）
$itemTypes = $itemTypes ?? \FuryoDacho\Models\ItemCategory::STATUTORY;
$transactionTypes = [
    'buy'         => '買取',
    'exchange'    => '交換',
    'consignment' => '委託販売受け',
    'other'       => 'その他',
];

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">CSV・PDF出力</h1>
</div>

<div class="alert alert-info" style="margin-bottom: 20px;">
    添付ファイルは出力対象外です。PDFはA4縦・古物台帳フォーマットで出力されます。
</div>

<div class="card">
    <div class="card__header">出力条件</div>
    <div class="card__body">
        <form method="POST" action="/index.php?page=export.export" id="exportForm">
            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">

            <div class="form-row form-row-3">
                <!-- 取引年月日 From -->
                <div class="form-group">
                    <label class="form-label" for="date_from">取引年月日（From）</label>
                    <input type="date" id="date_from" name="date_from" class="form-control"
                           value="<?= htmlspecialchars($search['date_from'] ?? '') ?>">
                </div>

                <!-- 取引年月日 To -->
                <div class="form-group">
                    <label class="form-label" for="date_to">取引年月日（To）</label>
                    <input type="date" id="date_to" name="date_to" class="form-control"
                           value="<?= htmlspecialchars($search['date_to'] ?? '') ?>">
                </div>

                <!-- 年度 -->
                <div class="form-group">
                    <label class="form-label" for="fiscal_year">年度</label>
                    <select id="fiscal_year" name="fiscal_year" class="form-control">
                        <option value="">-- すべて --</option>
                        <?php
                        $currentYear = (int)date('Y');
                        for ($y = $currentYear; $y >= $currentYear - 10; $y--):
                        ?>
                        <option value="<?= $y ?>"
                            <?= ($search['fiscal_year'] ?? '') == $y ? 'selected' : '' ?>>
                            <?= $y ?>年度
                        </option>
                        <?php endfor; ?>
                    </select>
                </div>

                <!-- 古物の種類 -->
                <div class="form-group">
                    <label class="form-label" for="item_type">古物の種類</label>
                    <select id="item_type" name="item_type" class="form-control">
                        <option value="">-- すべて --</option>
                        <?php foreach ($itemTypes as $val => $label): ?>
                        <option value="<?= htmlspecialchars($val) ?>"
                            <?= ($search['item_type'] ?? '') === $val ? 'selected' : '' ?>>
                            <?= htmlspecialchars($label) ?>
                        </option>
                        <?php endforeach; ?>
                    </select>
                </div>

                <!-- 取引種別 -->
                <div class="form-group">
                    <label class="form-label" for="transaction_type">取引種別</label>
                    <select id="transaction_type" name="transaction_type" class="form-control">
                        <option value="">-- すべて --</option>
                        <?php foreach ($transactionTypes as $val => $label): ?>
                        <option value="<?= htmlspecialchars($val) ?>"
                            <?= ($search['transaction_type'] ?? '') === $val ? 'selected' : '' ?>>
                            <?= htmlspecialchars($label) ?>
                        </option>
                        <?php endforeach; ?>
                    </select>
                </div>

                <!-- 品目 -->
                <div class="form-group">
                    <label class="form-label" for="item_name">品目</label>
                    <input type="text" id="item_name" name="item_name" class="form-control"
                           placeholder="品目名で絞り込み"
                           value="<?= htmlspecialchars($search['item_name'] ?? '') ?>">
                </div>

                <!-- 相手方氏名 -->
                <div class="form-group">
                    <label class="form-label" for="counterpart_name">相手方氏名</label>
                    <input type="text" id="counterpart_name" name="counterpart_name" class="form-control"
                           placeholder="氏名で絞り込み"
                           value="<?= htmlspecialchars($search['counterpart_name'] ?? '') ?>">
                </div>

                <!-- 登録者 -->
                <div class="form-group">
                    <label class="form-label" for="registered_by">登録者</label>
                    <select id="registered_by" name="registered_by" class="form-control">
                        <option value="">-- すべて --</option>
                        <?php if (!empty($users)): ?>
                        <?php foreach ($users as $u): ?>
                        <option value="<?= (int)$u['id'] ?>"
                            <?= ($search['registered_by'] ?? '') == $u['id'] ? 'selected' : '' ?>>
                            <?= htmlspecialchars($u['display_name']) ?>
                        </option>
                        <?php endforeach; ?>
                        <?php endif; ?>
                    </select>
                </div>

                <!-- 拠点 -->
                <div class="form-group">
                    <label class="form-label" for="branch_id">拠点</label>
                    <select id="branch_id" name="branch_id" class="form-control">
                        <option value="">-- すべて --</option>
                        <?php if (!empty($branches)): ?>
                        <?php foreach ($branches as $b): ?>
                        <option value="<?= (int)$b['id'] ?>"
                            <?= ($search['branch_id'] ?? '') == $b['id'] ? 'selected' : '' ?>>
                            <?= htmlspecialchars($b['name']) ?>
                        </option>
                        <?php endforeach; ?>
                        <?php endif; ?>
                    </select>
                </div>
            </div>

            <!-- 出力ボタン -->
            <div style="border-top: 1px solid var(--color-border); margin-top: 8px; padding-top: 20px;">
                <div class="d-flex gap-8" style="flex-wrap: wrap;">
                    <button type="submit" name="format" value="csv" class="btn btn-accent btn-lg">
                        &#8595; CSV出力
                    </button>
                    <button type="submit" name="format" value="pdf" class="btn btn-primary btn-lg">
                        &#8595; PDF出力
                    </button>
                </div>
                <p class="form-hint" style="margin-top: 10px;">
                    CSV: 全カラムを出力します。PDF: A4縦・古物台帳フォーマット（添付ファイルは含みません）。
                </p>
            </div>

        </form>
    </div>
</div>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
