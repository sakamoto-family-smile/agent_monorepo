-- エコシステムごとの Advisory 件数と深刻度の内訳。
-- 悪性パッケージ (kind = 'malicious') は CVSS を持たないので malicious 列に分け、
-- 深刻度の内訳 (critical〜unscored) は取り下げられていない脆弱性だけで数える
-- (Chainguard・Wolfi は CVE 単位のレコードへ統合した旧レコードを大量に取り下げている)
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
    count(*) filter (where a.kind = 'malicious') as malicious,
    count(*) filter (where a.kind <> 'malicious' and not a.withdrawn and a.severity = 'CRITICAL') as critical,
    count(*) filter (where a.kind <> 'malicious' and not a.withdrawn and a.severity = 'HIGH') as high,
    count(*) filter (where a.kind <> 'malicious' and not a.withdrawn and a.severity = 'MEDIUM') as medium,
    count(*) filter (where a.kind <> 'malicious' and not a.withdrawn and a.severity = 'LOW') as low,
    count(*) filter (where a.kind <> 'malicious' and not a.withdrawn and a.severity is null) as unscored,
    count(*) filter (where a.kev) as kev,
    count(*) filter (where p.has_fix) as with_fix,
    count(*) filter (where a.withdrawn) as withdrawn,
    max(a.published_at) as latest_published_at
from per_adv p
join {{ ref('stg_advisories') }} a using (advisory_id)
group by 1
