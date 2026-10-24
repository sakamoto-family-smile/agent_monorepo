-- 情報源ごとの鮮度。静かに止まるのが最大のリスクなので、最終成功からの経過時間を主役にする (FR-I07)
with runs as (
    select * from {{ ref('stg_source_runs') }}
),

last_success as (
    select source, max(finished_at) as last_success_at
    from runs where status = 'success'
    group by 1
),

last_run as (
    select distinct on (source) source, status as last_status, error as last_error, started_at as last_started_at
    from runs
    order by source, started_at desc
),

recent as (
    select
        source,
        count(*) as runs_24h,
        count(*) filter (where status = 'failed') as failures_24h,
        sum(fetched) as fetched_24h,
        sum(changed) as changed_24h,
        median(duration_seconds) as median_duration_seconds_24h
    from runs
    where started_at >= now() - interval 24 hour
    group by 1
)

select
    l.source,
    s.last_success_at,
    round(date_diff('minute', s.last_success_at, now()) / 60.0, 1) as hours_since_success,
    l.last_status,
    l.last_error,
    l.last_started_at,
    coalesce(r.runs_24h, 0) as runs_24h,
    coalesce(r.failures_24h, 0) as failures_24h,
    coalesce(r.fetched_24h, 0) as fetched_24h,
    coalesce(r.changed_24h, 0) as changed_24h,
    r.median_duration_seconds_24h
from last_run l
left join last_success s using (source)
left join recent r using (source)
