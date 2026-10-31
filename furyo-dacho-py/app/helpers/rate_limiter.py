"""
セッション単位の回数制限（会員照会・在庫検索などの機械的な連続照会を遅らせる）

完全な防止策ではない（セッションを作り直せばリセットされる）。PHP版と同じ「ベストエフォート」の抑止策。
"""
import time


def hit(session, key, max_count, window_sec):
    """1回分を数え、上限内なら True"""
    now = int(time.time())
    buckets = session.get('_rate_limit')
    if not isinstance(buckets, dict):
        buckets = {}
    bucket = buckets.get(key)
    if not isinstance(bucket, list):
        bucket = []
    bucket = [t for t in bucket if isinstance(t, int) and t > now - window_sec]
    if len(bucket) >= max_count:
        buckets[key] = bucket
        session.set('_rate_limit', buckets)
        return False
    bucket.append(now)
    buckets[key] = bucket
    session.set('_rate_limit', buckets)
    return True
