-- 同じ CVE が各情報源に載った時刻と、最初の情報源からの遅れ。どこが一番早いかを見る
with appearances as (
    select advisory_id, db_prefix as source_db, min(published_at) as appeared_at
    from {{ ref('stg_osv_records') }}
    where advisory_id like 'CVE-%' and published_at is not null
    group by 1, 2

    union all

    select cve as advisory_id, 'KEV' as source_db, cast(date_added as timestamptz) as appeared_at
    from {{ ref('stg_kev') }}
),

ranked as (
    select
        *,
        min(appeared_at) over (partition by advisory_id) as first_appeared_at,
        count(*) over (partition by advisory_id) as source_count
    from appearances
)

select
    advisory_id,
    source_db,
    appeared_at,
    first_appeared_at,
    round(date_diff('minute', first_appeared_at, appeared_at) / 60.0, 1) as lag_hours,
    appeared_at = first_appeared_at as is_first,
    source_count
from ranked
