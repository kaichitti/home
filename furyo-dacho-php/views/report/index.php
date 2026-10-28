<?php
$pageTitle  = '集計レポート - 古物台帳管理システム';
$activePage = 'report';

$fmt = static fn ($n) => number_format((float)$n);

// 棒グラフ用の最大値
$maxVal = 1;
foreach ($periods as $row) {
    $maxVal = max($maxVal, (int)($row['purchase']['total'] ?? 0), (int)($row['sale']['total'] ?? 0));
}

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">集計レポート</h1>
</div>

<!-- 期間・粒度の選択 -->
<div class="card">
    <div class="card__body">
        <form method="GET" action="/index.php" style="display:flex; gap:12px; flex-wrap:wrap; align-items:flex-end;">
            <input type="hidden" name="page" value="report">
            <div class="form-group" style="margin:0;">
                <label class="form-label">表示単位</label>
                <div style="display:flex; gap:6px;">
                    <?php foreach ($granularities as $gv => $gl): ?>
                    <label class="btn <?= $granularity === $gv ? 'btn-primary' : 'btn-secondary' ?> btn-sm" style="cursor:pointer;">
                        <input type="radio" name="granularity" value="<?= $gv ?>" <?= $granularity === $gv ? 'checked' : '' ?>
                               onchange="this.form.submit()" style="display:none;">
                        <?= $gl ?>
                    </label>
                    <?php endforeach; ?>
                </div>
            </div>
            <div class="form-group" style="margin:0;">
                <label class="form-label" for="from">開始日</label>
                <input type="date" id="from" name="from" class="form-control" value="<?= htmlspecialchars($from) ?>">
            </div>
            <div class="form-group" style="margin:0;">
                <label class="form-label" for="to">終了日</label>
                <input type="date" id="to" name="to" class="form-control" value="<?= htmlspecialchars($to) ?>">
            </div>
            <button type="submit" class="btn btn-primary">表示</button>
        </form>
    </div>
</div>

<!-- サマリー -->
<div class="card">
    <div class="card__body" style="display:flex; gap:24px; flex-wrap:wrap;">
        <div>
            <div class="text-muted" style="font-size:.8rem;">仕入合計（<?= htmlspecialchars($from) ?> 〜 <?= htmlspecialchars($to) ?>）</div>
            <div style="font-size:1.4rem; font-weight:700;">¥<?= $fmt($totalPurchase) ?></div>
        </div>
        <div>
            <div class="text-muted" style="font-size:.8rem;">売上合計</div>
            <div style="font-size:1.4rem; font-weight:700; color:#27ae60;">¥<?= $fmt($totalSale) ?></div>
        </div>
        <div>
            <div class="text-muted" style="font-size:.8rem;">差引（売上 − 仕入）</div>
            <?php $diff = $totalSale - $totalPurchase; ?>
            <div style="font-size:1.4rem; font-weight:700; color:<?= $diff >= 0 ? '#27ae60' : '#c0392b' ?>;">
                <?= $diff >= 0 ? '+' : '−' ?>¥<?= $fmt(abs($diff)) ?>
            </div>
        </div>
    </div>
</div>

<?php if (empty($periods)): ?>
<div class="card"><div class="card__body">
    <p class="text-muted">この期間のデータはありません。</p>
</div></div>
<?php else: ?>

<!-- 推移グラフ（CSSバー・外部ライブラリ不使用） -->
<div class="card">
    <div class="card__header">推移グラフ
        <span style="font-size:.75rem; font-weight:normal; margin-left:8px;">
            <span style="display:inline-block; width:10px; height:10px; background:#1e3a5f; border-radius:2px;"></span> 仕入
            <span style="display:inline-block; width:10px; height:10px; background:#27ae60; border-radius:2px; margin-left:8px;"></span> 売上
        </span>
    </div>
    <div class="card__body" style="overflow-x:auto;">
        <div style="display:flex; align-items:flex-end; gap:10px; min-height:180px; padding-bottom:4px;">
            <?php foreach ($periods as $period => $row):
                $pv = (int)($row['purchase']['total'] ?? 0);
                $sv = (int)($row['sale']['total'] ?? 0);
                $ph = (int)round($pv / $maxVal * 150);
                $sh = (int)round($sv / $maxVal * 150);
            ?>
            <div style="display:flex; flex-direction:column; align-items:center; gap:2px; min-width:52px;">
                <div style="display:flex; align-items:flex-end; gap:3px; height:152px;">
                    <div title="仕入 ¥<?= $fmt($pv) ?>" style="width:16px; height:<?= max($ph, $pv > 0 ? 2 : 0) ?>px; background:#1e3a5f; border-radius:3px 3px 0 0;"></div>
                    <div title="売上 ¥<?= $fmt($sv) ?>" style="width:16px; height:<?= max($sh, $sv > 0 ? 2 : 0) ?>px; background:#27ae60; border-radius:3px 3px 0 0;"></div>
                </div>
                <div style="font-size:.65rem; color:#666; white-space:nowrap;"><?= htmlspecialchars((string)$period) ?></div>
            </div>
            <?php endforeach; ?>
        </div>
    </div>
</div>

<!-- 明細テーブル -->
<div class="card">
    <div class="card__header">明細（<?= htmlspecialchars($granularities[$granularity]) ?>別）</div>
    <div class="card__body">
        <div class="table-wrap">
            <table class="table table--striped">
                <thead>
                    <tr>
                        <th>期間<?= $granularity === 'week' ? '（週の開始日）' : '' ?></th>
                        <th style="text-align:right;">仕入件数</th>
                        <th style="text-align:right;">仕入点数</th>
                        <th style="text-align:right;">仕入金額</th>
                        <th style="text-align:right;">売上件数</th>
                        <th style="text-align:right;">売上点数</th>
                        <th style="text-align:right;">売上金額</th>
                    </tr>
                </thead>
                <tbody>
                    <?php foreach ($periods as $period => $row):
                        $p = $row['purchase'] ?? null;
                        $sRow = $row['sale'] ?? null;
                    ?>
                    <tr>
                        <td><?= htmlspecialchars((string)$period) ?></td>
                        <td style="text-align:right;"><?= $p ? $fmt($p['cnt']) : '-' ?></td>
                        <td style="text-align:right;"><?= $p ? $fmt($p['qty']) : '-' ?></td>
                        <td style="text-align:right;"><?= $p ? '¥' . $fmt($p['total']) : '-' ?></td>
                        <td style="text-align:right;"><?= $sRow ? $fmt($sRow['cnt']) : '-' ?></td>
                        <td style="text-align:right;"><?= $sRow ? $fmt($sRow['qty']) : '-' ?></td>
                        <td style="text-align:right; color:#27ae60;"><?= $sRow ? '¥' . $fmt($sRow['total']) : '-' ?></td>
                    </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        </div>
        <p class="text-muted" style="font-size:.75rem; margin-top:8px;">
            仕入 = 台帳の取引金額（取引年月日基準）／売上 = 販売記録の販売金額（販売日時基準・POS含む）
        </p>
    </div>
</div>
<?php endif; ?>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
