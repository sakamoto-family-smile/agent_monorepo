-- KEV 掲載 CVE のうち、OSV でパッケージとバージョン範囲まで分かるもの (= A2 で照合できるもの)
with kev_pkgs as (
    select k.cve, p.ecosystem_base, p.package_name
    from {{ ref('stg_kev') }} k
    left join {{ source('intel', 'advisory_cves') }} c on c.cve = k.cve
    left join {{ ref('stg_affected_packages') }} p on p.advisory_id = c.advisory_id
),

per_cve as (
    select
        cve,
        list(distinct ecosystem_base order by ecosystem_base) filter (where ecosystem_base is not null) as ecosystems,
        count(distinct coalesce(ecosystem_base, '') || ':' || package_name) as packages
    from kev_pkgs
    group by 1
),

advisories as (
    select k.cve, list(distinct c.advisory_id order by c.advisory_id) filter (where c.advisory_id is not null) as advisory_ids
    from {{ ref('stg_kev') }} k
    left join {{ source('intel', 'advisory_cves') }} c on c.cve = k.cve
    group by 1
)

select
    k.cve,
    k.vendor,
    k.product,
    k.date_added,
    k.ransomware_known,
    a.advisory_ids,
    p.ecosystems,
    p.packages,
    p.packages > 0 as matchable_by_package
from {{ ref('stg_kev') }} k
left join per_cve p using (cve)
left join advisories a using (cve)
