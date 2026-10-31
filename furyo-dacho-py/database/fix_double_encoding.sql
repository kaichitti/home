-- ============================================================
-- 既存データ修復用SQL（1回だけ実行）
--
-- 旧バージョンでは入力値を htmlspecialchars してからDB保存して
-- いたため、「&」「<」「>」「"」「'」を含むデータが
-- &amp; &lt; &gt; &quot; &#039; としてDBに残っている。
-- 修正版アプリはDBに平文を保存するため、このSQLで既存行を
-- 平文に戻す。既存データが無い（新規導入）場合は実行不要。
--
-- 実行前に必ずバックアップを取得すること:
--   mysqldump -u USER -p DBNAME > backup.sql
-- ============================================================

UPDATE `ledgers` SET
  `item_name`              = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`item_name`,              '&lt;','<'),'&gt;','>'),'&quot;','"'),'&#039;','\''),'&amp;','&'),
  `item_description`       = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`item_description`,       '&lt;','<'),'&gt;','>'),'&quot;','"'),'&#039;','\''),'&amp;','&'),
  `transaction_type_note`  = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`transaction_type_note`,  '&lt;','<'),'&gt;','>'),'&quot;','"'),'&#039;','\''),'&amp;','&'),
  `counterpart_name`       = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`counterpart_name`,       '&lt;','<'),'&gt;','>'),'&quot;','"'),'&#039;','\''),'&amp;','&'),
  `counterpart_address`    = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`counterpart_address`,    '&lt;','<'),'&gt;','>'),'&quot;','"'),'&#039;','\''),'&amp;','&'),
  `counterpart_occupation` = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`counterpart_occupation`, '&lt;','<'),'&gt;','>'),'&quot;','"'),'&#039;','\''),'&amp;','&'),
  `id_document_number`     = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`id_document_number`,     '&lt;','<'),'&gt;','>'),'&quot;','"'),'&#039;','\''),'&amp;','&');

UPDATE `users` SET
  `display_name` = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`display_name`, '&lt;','<'),'&gt;','>'),'&quot;','"'),'&#039;','\''),'&amp;','&');

UPDATE `branches` SET
  `name`    = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`name`,    '&lt;','<'),'&gt;','>'),'&quot;','"'),'&#039;','\''),'&amp;','&'),
  `address` = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`address`, '&lt;','<'),'&gt;','>'),'&quot;','"'),'&#039;','\''),'&amp;','&');

UPDATE `tenants` SET
  `name` = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`name`, '&lt;','<'),'&gt;','>'),'&quot;','"'),'&#039;','\''),'&amp;','&');
