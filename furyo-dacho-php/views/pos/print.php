<?php
/**
 * レシート・領収書・精算レポートの HTML 描画（ブラウザ印刷・画面表示用）
 *
 * 変数:
 *  - $printLayout : ReceiptLayout が組み立てた行の配列
 *  - $title  : 文書名
 *  - $paper  : 用紙幅（58 / 80 mm）
 *  - $embed  : true = 画面内のプレビュー・印刷用フレーム（操作ボタンを出さない）
 *
 * ※ 直結プリンタ（USB / シリアル）は同じレイアウトを views/pos/_printer.php の
 *    Canvas 描画で印刷する。行の種類を増やす場合は両方に追加すること。
 */
$h = static fn ($v): string => htmlspecialchars((string)$v, ENT_QUOTES, 'UTF-8');
$paper = (int)($paper ?? 80) === 58 ? 58 : 80;
$contentWidth = $paper === 58 ? 48 : 72; // 印字可能幅（mm）
?>
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?= $h($title ?? 'レシート') ?></title>
<style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { background: #e9ecef; }
    body {
        font-family: 'Noto Sans JP', 'Hiragino Kaku Gothic ProN', 'Hiragino Sans', 'Yu Gothic', 'Meiryo', sans-serif;
        color: #000; font-size: <?= $paper === 58 ? '11px' : '12.5px' ?>; line-height: 1.45;
    }
    .toolbar { display: flex; gap: 8px; justify-content: center; padding: 12px; }
    .toolbar button, .toolbar a {
        background: #1e3a5f; color: #fff; border: none; border-radius: 4px; padding: 8px 18px;
        font-size: 14px; cursor: pointer; text-decoration: none; font-family: inherit;
    }
    .toolbar a { background: #6c757d; }
    .paper {
        width: <?= $contentWidth ?>mm; margin: 0 auto 24px; background: #fff; padding: 4mm 3mm;
        box-shadow: 0 1px 6px rgba(0,0,0,.25); word-break: break-all;
    }
    body.embed { background: #fff; }
    body.embed .paper { box-shadow: none; margin: 0 auto; }
    .l { text-align: left; } .c { text-align: center; } .r { text-align: right; }
    .s2 { font-size: 1.6em; line-height: 1.3; }
    .b { font-weight: 700; }
    .row { display: flex; justify-content: space-between; gap: 6px; }
    .row .rv { white-space: nowrap; text-align: right; }
    .row .lv { min-width: 0; }
    .hr  { border-top: 1px dashed #000; margin: 4px 0; }
    .hr2 { border-top: 3px double #000; margin: 4px 0; }
    .feed { height: 1.45em; }
    .box {
        width: 22mm; height: 22mm; border: 1px solid #000; margin: 2mm 0 0 auto;
        display: flex; align-items: center; justify-content: center; font-size: .85em;
    }
    pre { white-space: pre-wrap; }
    .bc { text-align: center; line-height: 0; }
    .bc svg { fill: #000; background: #fff; }
    @media print {
        @page { margin: 0; }
        html, body { background: #fff; }
        .toolbar { display: none; }
        .paper { box-shadow: none; margin: 0; width: 100%; max-width: <?= $contentWidth ?>mm; padding: 2mm 1mm; }
    }
</style>
</head>
<body class="<?= !empty($embed) ? 'embed' : '' ?>">
<?php if (empty($embed)): ?>
<div class="toolbar">
    <button type="button" onclick="window.print()">印刷する</button>
    <a href="javascript:history.back()">戻る</a>
</div>
<?php endif; ?>
<div class="paper">
<?php foreach (($printLayout ?? []) as $ln):
    $type = $ln['t'] ?? 'text';
    $cls  = (($ln['s'] ?? 1) === 2 ? ' s2' : '') . (!empty($ln['b']) ? ' b' : '');
    switch ($type):
        case 'row': ?>
    <div class="row<?= $cls ?>"><span class="lv"><?= $h($ln['l'] ?? '') ?></span><span class="rv"><?= $h($ln['r'] ?? '') ?></span></div>
<?php       break;
        case 'hr': ?>
    <div class="hr"></div>
<?php       break;
        case 'hr2': ?>
    <div class="hr2"></div>
<?php       break;
        case 'feed':
            for ($i = 0; $i < max(1, (int)($ln['n'] ?? 1)); $i++): ?>
    <div class="feed"></div>
<?php       endfor;
            break;
        case 'box': ?>
    <div class="box"><?= $h($ln['v'] ?? '') ?></div>
<?php       break;
        case 'barcode':
            // CODE128（前後に10モジュールの余白）。1モジュール 0.375mm（203dpiのレシートプリンタで3ドット）
            $mods  = array_map('intval', is_array($ln['m'] ?? null) ? $ln['m'] : []);
            $total = array_sum($mods) + 20;
            $wmm   = min($contentWidth - 2, round($total * 0.375, 3));
            $x     = 10;
            $rects = '';
            foreach ($mods as $i => $mw) {
                if ($i % 2 === 0) {
                    $rects .= '<rect x="' . $x . '" y="0" width="' . $mw . '" height="40"/>';
                }
                $x += $mw;
            } ?>
    <div class="bc"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 <?= $total ?> 40" preserveAspectRatio="none"
         shape-rendering="crispEdges" style="width:<?= $wmm ?>mm; height:11mm;" role="img" aria-label="<?= $h($ln['v'] ?? '') ?>"><?= $rects ?></svg></div>
<?php       break;
        default:
            $align = in_array($ln['a'] ?? 'l', ['l', 'c', 'r'], true) ? $ln['a'] : 'l'; ?>
    <div class="<?= $align . $cls ?>"><?= $h($ln['v'] ?? '') !== '' ? $h($ln['v']) : '&nbsp;' ?></div>
<?php   endswitch;
endforeach; ?>
</div>
</body>
</html>
