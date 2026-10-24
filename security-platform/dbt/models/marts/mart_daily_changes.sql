-- 日別・変化の種類別の件数 (ブートストラップ分は履歴に残さないので含まない)
select
    cast(occurred_at as date) as day,
    change_type,
    count(*) as changes,
    count(distinct advisory_id) as advisories
from {{ ref('stg_advisory_history') }}
group by 1, 2
