-- 照合で見つかった Finding (サービス × Advisory × パッケージ)
select
    finding_id,
    service_id,
    advisory_id,
    purl,
    dependency_path,
    priority,
    state,
    fix_type,
    fixed_version,
    json_extract_string(evidence_json, '$.package') as package,
    json_extract_string(evidence_json, '$.version') as version,
    json_extract_string(evidence_json, '$.ecosystem') as ecosystem,
    json_extract_string(evidence_json, '$.scope') as scope,
    -- 見つかった元: source (lockfile) / image (本番イメージ)。この列を入れる前の Finding は lockfile 由来
    coalesce(json_extract_string(evidence_json, '$.source_kind'), 'source') as source_kind,
    coalesce(json_extract_string(evidence_json, '$.source'), json_extract_string(evidence_json, '$.lockfile'))
        as source,
    json_extract_string(evidence_json, '$.severity') as severity,
    json_extract_string(evidence_json, '$.kind') as kind,
    cast(json_extract(evidence_json, '$.kev') as boolean) as kev,
    cast(json_extract(evidence_json, '$.epss') as double) as epss,
    json_extract_string(evidence_json, '$.summary') as summary,
    cast(due_at as timestamptz) as due_at,
    cast(first_seen_at as timestamptz) as first_seen_at,
    cast(updated_at as timestamptz) as updated_at,
    cast(closed_at as timestamptz) as closed_at
from {{ source('detection', 'findings') }}
