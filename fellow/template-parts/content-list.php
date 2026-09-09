<?php
/**
 * 記事一覧の1件分(リスト型)。
 *
 * home.php / archive.php / search.php / index.php / single.php(関連記事)から
 * 共通で呼ぶ。アイキャッチ未設定の記事が多いブログでも間延びしないよう、
 * 画像がある記事だけ小さなサムネイルを出し、無ければ文字だけで組む。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

$fellow_item_score      = fellow_get_review_score();
$fellow_item_categories = get_the_category();
$fellow_item_excerpt    = fellow_get_excerpt( 100 );
$fellow_item_has_thumb  = has_post_thumbnail();
?>
<article id="post-<?php the_ID(); ?>" <?php post_class( 'post-item' . ( $fellow_item_has_thumb ? ' post-item--has-thumb' : '' ) ); ?>>
	<a class="post-item__link" href="<?php the_permalink(); ?>">
		<div class="post-item__body">
			<?php if ( $fellow_item_categories || null !== $fellow_item_score ) : ?>
				<div class="post-item__labels">
					<?php if ( $fellow_item_categories ) : ?>
						<span class="post-item__category"><?php echo esc_html( $fellow_item_categories[0]->name ); ?></span>
					<?php endif; ?>

					<?php if ( null !== $fellow_item_score ) : ?>
						<span class="post-item__score">
							<?php echo esc_html( number_format_i18n( $fellow_item_score, 1 ) ); ?>
						</span>
					<?php endif; ?>
				</div>
			<?php endif; ?>

			<h3 class="post-item__title"><?php the_title(); ?></h3>

			<?php if ( '' !== $fellow_item_excerpt ) : ?>
				<p class="post-item__excerpt"><?php echo esc_html( $fellow_item_excerpt ); ?></p>
			<?php endif; ?>

			<div class="post-item__meta">
				<?php fellow_entry_date(); ?>
			</div>
		</div>

		<?php if ( $fellow_item_has_thumb ) : ?>
			<?php
			/*
			 * サムネイルは本文の「後ろ」に置く。
			 * 画像が無い記事の方が多い前提なので、左に置くと画像のある行だけ
			 * 本文が右へずれて左端が揃わない。右に寄せておけば列が乱れない。
			 * 読み上げ順もタイトルが先に来るので都合がよい。
			 *
			 * 表示は最大160px。コアの medium(既定300px)ならどのサイトでも
			 * 生成済みで、無駄な転送も抑えられる。
			 */
			?>
			<div class="post-item__thumb">
				<?php
				the_post_thumbnail(
					'medium',
					array(
						'loading' => 'lazy',
						'class'   => 'post-item__image',
					)
				);
				?>
			</div>
		<?php endif; ?>
	</a>
</article>
