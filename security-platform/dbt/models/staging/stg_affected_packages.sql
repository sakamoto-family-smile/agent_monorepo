-- 影響パッケージ。ecosystem は "Debian:12" のような版付きを基底名に揃えた列も持つ
select
    r.advisory_id,
    f.record_id,
    f.ecosystem,
    split_part(f.ecosystem, ':', 1) as ecosystem_base,
    f.name as package_name,
    f.purl,
    cast(f.fixed_json as json) as fixed_versions,
    json_array_length(cast(f.fixed_json as json)) > 0 as has_fix,
    f.versions_count
from {{ source('intel', 'record_affected') }} f
join {{ source('intel', 'osv_records') }} r using (record_id)
