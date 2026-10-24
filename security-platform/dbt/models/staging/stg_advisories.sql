-- Advisory に KEV・EPSS を結合したもの (intel.db の v_advisories と同じ定義)
with signals as (
    select
        c.advisory_id,
        bool_or(k.cve is not null) as kev,
        min(cast(k.date_added as date)) as kev_date_added,
        max(e.epss) as epss,
        max(e.percentile) as epss_percentile
    from {{ source('intel', 'advisory_cves') }} c
    left join {{ source('intel', 'kev_entries') }} k on k.cve = c.cve
    left join {{ source('intel', 'epss_scores') }} e on e.cve = c.cve
    group by 1
)

select
    a.advisory_id,
    a.kind,
    cast(a.cves_json as json) as cves,
    a.summary,
    a.cvss_score,
    a.cvss_vector,
    a.severity,
    cast(a.published_at as timestamptz) as published_at,
    cast(a.modified_at as timestamptz) as modified_at,
    cast(a.withdrawn as boolean) as withdrawn,
    a.record_count,
    a.affected_hash,
    a.fixed_hash,
    coalesce(s.kev, false) as kev,
    s.kev_date_added,
    s.epss,
    s.epss_percentile,
    cast(a.first_seen_at as timestamptz) as first_seen_at,
    cast(a.updated_at as timestamptz) as updated_at
from {{ source('intel', 'advisories') }} a
left join signals s using (advisory_id)
