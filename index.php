<?php
/**
 * index.php
 *
 * 管理画面。パスワード認証で保護されており、以下を行える:
 *   - 決済リンクの登録（slug, 名前, 金額, 通貨, 秘密URL）
 *   - 登録済みリンクの一覧／有効化・無効化・削除
 *   - 最近の支払い状況の表示
 *   - Checkout URL の確認
 */

declare(strict_types=1);

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/lib/auth.php';
require_once __DIR__ . '/lib/db.php';

pgw_session_start();

$errors  = [];
$notices = [];

// ---------------------------------------------------------------------
// ログアウト
// ---------------------------------------------------------------------
if (isset($_GET['logout'])) {
    pgw_logout();
    pgw_redirect(pgw_url('index.php'));
}

// ---------------------------------------------------------------------
// ログイン処理
// ---------------------------------------------------------------------
if (!pgw_is_logged_in()) {
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['action']) && $_POST['action'] === 'login') {
        $password = (string)($_POST['password'] ?? '');
        if (pgw_login($password)) {
            pgw_redirect(pgw_url('index.php'));
        }
        $errors[] = 'ログインに失敗しました。パスワードを確認してください。';

        // 管理パスワードが未設定の場合は親切に案内する。
        $cfg = pgw_config();
        if (empty($cfg['admin_password_hash'])) {
            $errors[] = 'config.php の admin_password_hash が未設定です。'
                      . 'php -r "echo password_hash(\'your-password\', PASSWORD_DEFAULT);" で生成してください。';
        }
    }

    render_login($errors);
    exit;
}

// ---------------------------------------------------------------------
// 以下、ログイン後の処理
// ---------------------------------------------------------------------
$pdo = pgw_db();

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = (string)($_POST['action'] ?? '');

    if (!pgw_csrf_check($_POST['csrf'] ?? null)) {
        $errors[] = 'CSRF トークンが一致しません。再度お試しください。';
    } else {
        try {
            switch ($action) {
                case 'create_link':
                    $slug       = trim((string)($_POST['slug'] ?? ''));
                    $name       = trim((string)($_POST['name'] ?? ''));
                    $price      = (int)($_POST['price'] ?? 0);
                    $currency   = strtolower(trim((string)($_POST['currency'] ?? pgw_config()['default_currency'])));
                    $target_url = trim((string)($_POST['target_url'] ?? ''));

                    if ($slug === '') {
                        // 未指定の場合は自動生成。
                        $slug = bin2hex(random_bytes(6));
                    }
                    if (!preg_match('/^[A-Za-z0-9_\-]{3,64}$/', $slug)) {
                        throw new RuntimeException('slug は半角英数・ハイフン・アンダースコア 3〜64 文字で指定してください。');
                    }
                    if ($name === '') {
                        throw new RuntimeException('商品名を入力してください。');
                    }
                    if ($price < 1) {
                        throw new RuntimeException('価格は1以上の整数（最小通貨単位）で入力してください。');
                    }
                    if (!preg_match('/^[a-z]{3}$/', $currency)) {
                        throw new RuntimeException('通貨コードは ISO 4217（例: jpy, usd）の3文字で指定してください。');
                    }
                    if (!filter_var($target_url, FILTER_VALIDATE_URL) || !preg_match('#^https?://#i', $target_url)) {
                        throw new RuntimeException('リダイレクト先URLは http:// または https:// で始まる有効なURLを指定してください。');
                    }

                    $stmt = $pdo->prepare('INSERT INTO links (slug, name, price, currency, target_url) VALUES (:slug, :name, :price, :currency, :target_url)');
                    $stmt->execute([
                        ':slug'       => $slug,
                        ':name'       => $name,
                        ':price'      => $price,
                        ':currency'   => $currency,
                        ':target_url' => $target_url,
                    ]);
                    $notices[] = 'リンクを作成しました: ' . $slug;
                    break;

                case 'toggle_link':
                    $id = (int)($_POST['id'] ?? 0);
                    $pdo->prepare('UPDATE links SET active = CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id = :id')
                        ->execute([':id' => $id]);
                    $notices[] = 'リンクの有効状態を切り替えました。';
                    break;

                case 'delete_link':
                    $id = (int)($_POST['id'] ?? 0);
                    $pdo->prepare('DELETE FROM links WHERE id = :id')->execute([':id' => $id]);
                    $notices[] = 'リンクを削除しました（関連する支払履歴は残ります）。';
                    break;

                default:
                    $errors[] = '不明な操作です。';
            }
        } catch (PDOException $e) {
            if (str_contains($e->getMessage(), 'UNIQUE')) {
                $errors[] = 'その slug は既に使用されています。';
            } else {
                $errors[] = 'データベースエラー: ' . $e->getMessage();
            }
        } catch (Throwable $e) {
            $errors[] = $e->getMessage();
        }
    }
}

$links = $pdo->query('SELECT * FROM links ORDER BY created_at DESC')->fetchAll();
$payments = $pdo->query("
    SELECT p.*, l.slug AS link_slug, l.name AS link_name
      FROM payments p
      LEFT JOIN links l ON l.id = p.link_id
     ORDER BY p.created_at DESC
     LIMIT 20
")->fetchAll();

render_admin($links, $payments, $errors, $notices);


// =====================================================================
// ビュー
// =====================================================================
function render_login(array $errors): void
{
    ?><!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>管理ログイン - 決済リンク・ゲートウェイ</title>
  <style><?php echo pgw_admin_css(); ?></style>
</head>
<body class="login">
  <main>
    <h1>管理ログイン</h1>
    <?php foreach ($errors as $e): ?>
      <div class="error"><?= pgw_h($e) ?></div>
    <?php endforeach; ?>
    <form method="post" action="index.php">
      <input type="hidden" name="action" value="login">
      <label>パスワード
        <input type="password" name="password" autocomplete="current-password" required autofocus>
      </label>
      <button type="submit">ログイン</button>
    </form>
    <p class="hint">パスワードは config.php の <code>admin_password_hash</code> で設定されたものです。</p>
  </main>
</body>
</html>
<?php
}

function render_admin(array $links, array $payments, array $errors, array $notices): void
{
    $csrf = pgw_csrf_token();
    $base = pgw_base_url();
    ?><!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>決済リンク管理</title>
  <style><?php echo pgw_admin_css(); ?></style>
</head>
<body>
  <header class="topbar">
    <h1>決済リンク・ゲートウェイ</h1>
    <nav><a href="index.php?logout=1">ログアウト</a></nav>
  </header>
  <main>
    <?php foreach ($notices as $n): ?>
      <div class="notice"><?= pgw_h($n) ?></div>
    <?php endforeach; ?>
    <?php foreach ($errors as $e): ?>
      <div class="error"><?= pgw_h($e) ?></div>
    <?php endforeach; ?>

    <section>
      <h2>新しいリンクを作成</h2>
      <form method="post" action="index.php" class="grid">
        <input type="hidden" name="csrf" value="<?= pgw_h($csrf) ?>">
        <input type="hidden" name="action" value="create_link">
        <label>slug（URLに使う識別子・空欄で自動生成）
          <input type="text" name="slug" pattern="[A-Za-z0-9_\-]{3,64}" placeholder="例: premium-pdf">
        </label>
        <label>商品名
          <input type="text" name="name" required placeholder="例: プレミアムPDF">
        </label>
        <label>価格（最小通貨単位・JPYは円）
          <input type="number" name="price" min="1" step="1" required placeholder="例: 500">
        </label>
        <label>通貨（ISO 4217, 3文字）
          <input type="text" name="currency" maxlength="3" pattern="[a-zA-Z]{3}" value="<?= pgw_h(pgw_config()['default_currency']) ?>" required>
        </label>
        <label class="full">リダイレクト先（秘密のURL）
          <input type="url" name="target_url" required placeholder="https://example.com/secret-contents">
        </label>
        <button type="submit">作成</button>
      </form>
    </section>

    <section>
      <h2>登録済みリンク</h2>
      <?php if (!$links): ?>
        <p>まだリンクはありません。</p>
      <?php else: ?>
        <table>
          <thead><tr>
            <th>slug</th><th>商品名</th><th>価格</th><th>通貨</th>
            <th>Checkout URL</th><th>リダイレクト先</th><th>状態</th><th>操作</th>
          </tr></thead>
          <tbody>
          <?php foreach ($links as $l):
            $checkoutUrl = $base . '/checkout.php?slug=' . urlencode($l['slug']);
          ?>
            <tr>
              <td><code><?= pgw_h($l['slug']) ?></code></td>
              <td><?= pgw_h($l['name']) ?></td>
              <td class="num"><?= pgw_h(number_format((int)$l['price'])) ?></td>
              <td><?= pgw_h(strtoupper($l['currency'])) ?></td>
              <td><a href="<?= pgw_h($checkoutUrl) ?>" target="_blank" rel="noopener"><?= pgw_h($checkoutUrl) ?></a></td>
              <td class="trunc" title="<?= pgw_h($l['target_url']) ?>"><?= pgw_h($l['target_url']) ?></td>
              <td><?= $l['active'] ? '<span class="badge ok">有効</span>' : '<span class="badge off">無効</span>' ?></td>
              <td>
                <form method="post" action="index.php" class="inline">
                  <input type="hidden" name="csrf" value="<?= pgw_h($csrf) ?>">
                  <input type="hidden" name="action" value="toggle_link">
                  <input type="hidden" name="id" value="<?= (int)$l['id'] ?>">
                  <button type="submit">切替</button>
                </form>
                <form method="post" action="index.php" class="inline" onsubmit="return confirm('このリンクを削除しますか？');">
                  <input type="hidden" name="csrf" value="<?= pgw_h($csrf) ?>">
                  <input type="hidden" name="action" value="delete_link">
                  <input type="hidden" name="id" value="<?= (int)$l['id'] ?>">
                  <button type="submit" class="danger">削除</button>
                </form>
              </td>
            </tr>
          <?php endforeach; ?>
          </tbody>
        </table>
      <?php endif; ?>
    </section>

    <section>
      <h2>最近の支払い（最新20件）</h2>
      <?php if (!$payments): ?>
        <p>まだ支払いはありません。</p>
      <?php else: ?>
        <table>
          <thead><tr>
            <th>作成日時</th><th>リンク</th><th>金額</th><th>状態</th>
            <th>支払日時</th><th>受渡日時</th><th>Email</th>
          </tr></thead>
          <tbody>
          <?php foreach ($payments as $p): ?>
            <tr>
              <td><?= pgw_h($p['created_at']) ?></td>
              <td><code><?= pgw_h($p['link_slug'] ?? '-') ?></code></td>
              <td class="num"><?= pgw_h(number_format((int)$p['amount'])) ?> <?= pgw_h(strtoupper($p['currency'])) ?></td>
              <td><span class="badge s-<?= pgw_h($p['status']) ?>"><?= pgw_h($p['status']) ?></span></td>
              <td><?= pgw_h($p['paid_at'] ?? '-') ?></td>
              <td><?= pgw_h($p['redeemed_at'] ?? '-') ?></td>
              <td><?= pgw_h($p['customer_email'] ?? '-') ?></td>
            </tr>
          <?php endforeach; ?>
          </tbody>
        </table>
      <?php endif; ?>
    </section>

    <section class="info">
      <h2>Webhook 設定</h2>
      <p>Stripe ダッシュボードで下記のエンドポイントを登録し、<code>checkout.session.completed</code> を購読してください。</p>
      <p><code><?= pgw_h($base . '/webhook.php') ?></code></p>
    </section>
  </main>
</body>
</html>
<?php
}

function pgw_admin_css(): string
{
    return <<<CSS
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, "Hiragino Sans", sans-serif; margin: 0; background: #f6f7f9; color: #222; }
main { max-width: 1100px; margin: 0 auto; padding: 1.5rem; }
body.login main { max-width: 420px; margin-top: 10vh; background: #fff; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,.06); }
.topbar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.5rem; background: #222; color: #fff; }
.topbar h1 { margin: 0; font-size: 1.1rem; }
.topbar a { color: #fff; text-decoration: none; }
h1, h2 { margin-top: 0; }
section { background: #fff; padding: 1.25rem 1.5rem; border-radius: 8px; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,.04); }
label { display: flex; flex-direction: column; font-size: .9rem; gap: .25rem; }
input[type=text], input[type=url], input[type=number], input[type=password] { padding: .5rem .6rem; border: 1px solid #ccd; border-radius: 4px; font-size: 1rem; }
button { padding: .5rem 1rem; font-size: .95rem; background: #2a63d0; color: #fff; border: 0; border-radius: 4px; cursor: pointer; }
button.danger { background: #c0392b; }
button:hover { opacity: .9; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem 1rem; align-items: end; }
.grid .full { grid-column: 1 / -1; }
.grid button { grid-column: 1 / -1; justify-self: start; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th, td { padding: .5rem .6rem; border-bottom: 1px solid #eee; text-align: left; vertical-align: top; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.trunc { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.inline { display: inline; }
.badge { display: inline-block; padding: .1rem .5rem; border-radius: 999px; font-size: .75rem; }
.badge.ok { background: #d4edda; color: #155724; }
.badge.off { background: #f1f1f1; color: #777; }
.badge.s-pending { background: #fff3cd; color: #856404; }
.badge.s-paid { background: #cce5ff; color: #004085; }
.badge.s-redeemed { background: #d4edda; color: #155724; }
.badge.s-failed { background: #f8d7da; color: #721c24; }
.notice { background: #d4edda; color: #155724; padding: .5rem .75rem; border-radius: 4px; margin-bottom: 1rem; }
.error { background: #f8d7da; color: #721c24; padding: .5rem .75rem; border-radius: 4px; margin-bottom: 1rem; }
.hint { color: #666; font-size: .85rem; }
code { background: #f1f3f5; padding: .1rem .3rem; border-radius: 3px; font-size: .85em; }
a { color: #2a63d0; }
CSS;
}
