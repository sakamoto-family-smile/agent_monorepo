-- エコシステムごとの Advisory 件数と深刻度の内訳
with pkg as (
    select distinct advisory_id, ecosystem_base, has_fix
    from {{ ref('stg_affected_packages') }}
    where ecosystem_base is not null
),

per_adv as (
    select advisory_id, ecosystem_base, bool_or(has_fix) as has_fix
    from pkg group by 1, 2
)

select
    p.ecosystem_base as ecosystem,
    count(*) as advisories,
    count(*) filter (where a.severity = 'CRITICAL') as critical,
    count(*) filter (where a.severity = 'HIGH') as high,
    count(*) filter (where a.severity = 'MEDIUM') as medium,
    count(*) filter (where a.severity = 'LOW') as low,
    count(*) filter (where a.severity is null) as unscored,
    count(*) filter (where a.kev) as kev,
    count(*) filter (where p.has_fix) as with_fix,
    count(*) filter (where a.withdrawn) as withdrawn,
    max(a.published_at) as latest_published_at
from per_adv p
join {{ ref('stg_advisories') }} a using (advisory_id)
group by 1
