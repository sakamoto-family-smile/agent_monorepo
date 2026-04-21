-- mart_cache_efficiency.cache_hit_ratio は 0.0〜1.0 の範囲内。
SELECT *
FROM {{ ref('mart_cache_efficiency') }}
WHERE cache_hit_ratio < 0.0 OR cache_hit_ratio > 1.0
