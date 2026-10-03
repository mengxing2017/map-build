#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

INPUT=""

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --input=*) INPUT="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --input=<source.osm.pbf> --region=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq osmium awk
require_region "${REGION}"
normalize_session_vars
place_label_hierarchy_validate

[[ -n "${INPUT}" ]] || die "${HUAVD_EXIT_INPUT}" "--input is required"
INPUT="$(resolve_workspace_path "${INPUT}")"
require_file "${INPUT}"

place_labels="$(layers_dir)/place_label.geojsonseq"
require_file "${place_labels}"
if [[ ! -s "${place_labels}" ]]; then
  report="$(place_admin_report_path)"
  ensure_dir "$(dirname -- "${report}")"
  jq -n '
    {
      schema_version: 1,
      source: {place_feature_count: 0, administrative_relation_count: 0},
      summary: {
        role_member_relations_with_place_candidates: 0,
        role_member_canonical_feature_count: 0,
        fallback_canonical_feature_count: 0,
        fallback_dropped_count: 0,
        exact_duplicate_dropped_count: 0,
        same_name_tier_dropped_count: 0,
        redundant_role_member_dropped_count: 0,
        admin_display_name_override_count: 0,
        output_feature_count: 0
      },
      relations: [],
      shared_member_choices: [],
      fallback_dropped: [],
      exact_duplicates: [],
      same_name_tier_duplicates: [],
      redundant_role_members: []
    }
  ' > "${report}"
  log_info "place-label administrative enrichment: no place_label features; report=${report}"
  exit 0
fi

cache_dir="$(place_admin_cache_dir)"
ensure_dir "${cache_dir}"
relations_pbf="${cache_dir}/admin-relations.osm.pbf"
relations_index="${cache_dir}/admin-relations.ndjson"
node_wikidata_index="${cache_dir}/place-node-wikidata.ndjson"
boundaries_geojsonseq="${cache_dir}/admin-boundaries.geojsonseq"
boundaries_index="${cache_dir}/admin-boundaries.ndjson"
boundary_export_config="${cache_dir}/admin-boundaries-export.json"
hierarchy="$(place_label_hierarchy_json)"
adn_config="$(place_label_admin_display_name_json "${REGION}")"
report="$(place_admin_report_path)"
combined="${cache_dir}/place-label-enriched.json"
tmp="${place_labels}.place-admin.tmp"

log_info "extract administrative relations + place nodes -> ${relations_pbf}"
# 不加 -R：保留被引用的 ways/nodes，用于装配行政边界多边形；并附带 place 节点以读取 wikidata。
osmium tags-filter -O -o "${relations_pbf}" "${INPUT}" r/boundary=administrative n/place \
  || die "${HUAVD_EXIT_ERROR}" "administrative relation filter failed"

# Relation members and roles are ASCII in OPL. Non-ASCII tag values stay OPL-escaped
# ("%<hex>%") on purpose and are decoded in the jq stage via implode, so no Python is
# needed for tag decoding. Boundary polygons (wikidata-missing fallback) are assembled
# by osmium export and tested with an arithmetic point-in-polygon inside jq.
log_info "index administrative relation role members"
osmium cat -f opl "${relations_pbf}" | awk '
  function jesc(s) { gsub(/\\/, "\\\\", s); gsub(/"/, "\\\"", s); return s }
  function jstr(k, v) { return "\"" k "\":" (v == "" ? "null" : "\"" jesc(v) "\"") }
  {
    if (substr($0, 1, 1) != "r") next
    n = split($0, f, " ")
    rid = substr(f[1], 2) + 0
    t = ""; m = ""
    for (i = 2; i <= n; i++) {
      c = substr(f[i], 1, 1)
      if (c == "T") t = substr(f[i], 2)
      else if (c == "M") m = substr(f[i], 2)
    }
    if (t == "") next
    delete kv
    cnt = split(t, ta, ",")
    for (i = 1; i <= cnt; i++) {
      p = index(ta[i], "=")
      if (p > 1) kv[substr(ta[i], 1, p - 1)] = substr(ta[i], p + 1)
    }
    if (kv["boundary"] != "administrative") next
    lvl = (kv["admin_level"] ~ /^[0-9]+$/) ? kv["admin_level"] : "null"
    nodes = ""
    if (m != "") {
      mc = split(m, ma, ",")
      for (i = 1; i <= mc; i++) {
        if (ma[i] !~ /^n[0-9]+@(admin_centre|label)$/) continue
        at = index(ma[i], "@")
        ref = substr(ma[i], 2, at - 2)
        role = substr(ma[i], at + 1)
        nodes = nodes (nodes == "" ? "" : ",") "{\"ref\":" ref ",\"role\":\"" role "\"}"
      }
    }
    printf "{\"id\":%d,\"level\":%s,%s,%s,%s,%s,%s,\"nodes\":[%s]}\n", rid, lvl,
      jstr("name_zh_hans", kv["name:zh-Hans"]), jstr("name_zh", kv["name:zh"]),
      jstr("name", kv["name"]), jstr("name_en", kv["name:en"]), jstr("wikidata", kv["wikidata"]), nodes
  }
' > "${relations_index}" \
  || die "${HUAVD_EXIT_ERROR}" "administrative relation index failed"

# place 节点 wikidata：enrich 在 normalize 之后运行，wikidata 已被 final_fields 裁剪，
# 故直接从源 PBF 的 place 节点读取，用于判定“同名字节点与行政关系是否同一实体”。
log_info "index place node wikidata"
osmium cat -f opl "${relations_pbf}" | awk '
  {
    if (substr($0, 1, 1) != "n") next
    n = split($0, f, " ")
    nid = substr(f[1], 2) + 0
    t = ""
    for (i = 2; i <= n; i++) {
      if (substr(f[i], 1, 1) == "T") { t = substr(f[i], 2); break }
    }
    if (t == "") next
    delete kv
    cnt = split(t, ta, ",")
    for (i = 1; i <= cnt; i++) {
      p = index(ta[i], "=")
      if (p > 1) kv[substr(ta[i], 1, p - 1)] = substr(ta[i], p + 1)
    }
    if (kv["wikidata"] == "") next
    printf "{\"node_id\":%d,\"wikidata\":\"%s\"}\n", nid, kv["wikidata"]
  }
' > "${node_wikidata_index}" \
  || die "${HUAVD_EXIT_ERROR}" "place node wikidata index failed"

# 行政边界多边形：wikidata 缺失时回退到“同名字节点是否落在匹配关系边界内”判定同实体。
log_info "assemble administrative boundaries -> ${boundaries_geojsonseq}"
cat > "${boundary_export_config}" <<'JSON'
{
  "attributes": { "type": false, "id": true, "version": false, "changeset": false, "timestamp": false, "uid": false, "user": false },
  "include_tags": ["admin_level"]
}
JSON
osmium export -c "${boundary_export_config}" "${relations_pbf}" -f geojsonseq -o "${boundaries_geojsonseq}" --overwrite \
  || die "${HUAVD_EXIT_ERROR}" "administrative boundary export failed"
jq --seq -c 'select(.geometry.type == "MultiPolygon") | {id: .properties["@id"], polys: .geometry.coordinates}' \
  "${boundaries_geojsonseq}" | tr -d '\036' > "${boundaries_index}" \
  || die "${HUAVD_EXIT_ERROR}" "administrative boundary index failed"

jq_program=$(cat <<'JQ'
def hexv($s): reduce ($s | explode[]) as $c (0;
    . * 16 + (if $c >= 48 and $c <= 57 then $c - 48
              elif $c >= 97 and $c <= 102 then $c - 87
              elif $c >= 65 and $c <= 70 then $c - 55
              else 0 end));
def opl_decode: (split("%")) as $p
  | reduce range(0; ($p | length)) as $i ([];
      if ($i % 2) == 1 then . + [([hexv($p[$i])] | implode)]
      elif $p[$i] != "" then . + [$p[$i]]
      else . end)
  | join("");
def trim: gsub("^[\\s]+|[\\s]+$"; "");
def name_key($p):
  (first( ("name:zh-Hans", "name:zh", "name", "name:en") as $k
           | ($p[$k] // null) | select(type == "string") | trim | select(length > 0)) // null);
def rel_name($r):
  (first( ($r.name_zh_hans, $r.name_zh, $r.name, $r.name_en) as $v
           | ($v // null) | select(type == "string") | opl_decode | trim | select(length > 0)) // null);
def cplen($a; $b):
  ($a | explode) as $x | ($b | explode) as $y
  | ([ ($x | length), ($y | length) ] | min) as $m
  | ( first( range(0; $m) | select($x[.] != $y[.]) ) // $m );
# 判定“同名字节点 P 是否落在行政关系 R 的边界多边形内”（射线法，纯算术，无需几何库）。
# 仅在 wikidata 缺失、无法用唯一实体 ID 判定时作为回退判据。
def pip_ring($pt; $ring):
  ($ring | length) as $n
  | if $n < 3 then false
    else
      (reduce range(0; $n) as $i (0;
        (($i - 1 + $n) % $n) as $j
        | ($ring[$i][0]) as $xi | ($ring[$i][1]) as $yi
        | ($ring[$j][0]) as $xj | ($ring[$j][1]) as $yj
        | if ((($yi > $pt[1]) != ($yj > $pt[1]))
              and ($pt[0] < ($xj - $xi) * ($pt[1] - $yi) / ($yj - $yi) + $xi))
            then . + 1 else . end
      )) % 2 == 1
    end;
def pip_poly($pt; $poly):
  (pip_ring($pt; $poly[0]))
  and (([ $poly[1:][] | pip_ring($pt; .) ] | any) | not);
def pip_multi($pt; $polys):
  ([ $polys[] | select(pip_poly($pt; .)) ] | length) > 0;
# 显示名覆盖闸门：仅当关系名是当前名的“更完整形式”时才覆盖，避免把无关/双语/缩写名改坏：
# 同源（公共前缀≥2）、不更短、且不含双语斜杠。
def adn_ok($cur; $fn):
  if ($cur == null or $fn == null) then false
  elif ($fn | contains("/")) then false
  elif (($fn | length) < ($cur | length)) then false
  else (cplen($cur; $fn) >= 2) end;
def pop_of($f): (($f.properties.population // 0) | (try tonumber catch 0)) | (if . < 0 then 0 else . end);
def fid($f): (($f.properties["@id"] // null) | (try tonumber catch null));
def role_prio($t; $r):
  if ($t == "country" or $t == "province" or $t == "prefecture") then (if $r == "admin_centre" then 1 else 0 end)
  elif ($t == "county" or $t == "township" or $t == "locality") then (if $r == "label" then 1 else 0 end)
  else 0 end;
def cand_key($h): . as $c | [
    # 1) 优先与该关系同名的节点（避免“州/地区”选到与下级共用的驻地节点）
    (if (($c.name != null) and ($c.name == name_key($c.feature.properties))) then -1 else 0 end),
    # 2) 其次优先 label 角色（OSM 为 boundary 提供的专用标签节点）
    (if ($c.role == "label") then -1 else 0 end),
    # 3) 其次层级期望要素类型匹配
    (if ($c.tier != null and (($h.tier_expected_place[$c.tier] // []) | index($c.feature.properties.place))) then -1 else 0 end),
    (- pop_of($c.feature)),
    ((fid($c.feature)) // 9223372036854775807) ];
def primary_key($h): . as $c | [
    (- (if $c.tier != null then ($h.rank[$c.tier] // 0) else 0 end)),
    (- role_prio($c.tier; $c.role)),
    $c.id ];

$hierarchy[0] as $h
| ( $relations | map(. + {tier: (if .level == null then null else ($h.boundary_tier[(.level | tostring)] // null) end)}) ) as $rels
| [inputs] | map(select(.type == "Feature")) as $F
| ( reduce ($node_wd // [])[] as $e ({}; .[($e.node_id | tostring)] = $e.wikidata) ) as $nodeWd
| ( reduce ($boundaries // [])[] as $e ({}; .[($e.id | tostring)] = $e.polys) ) as $boundMap
| (reduce $F[] as $f ({}; (fid($f)) as $i | if $i != null then .[($i | tostring)] = $f else . end)) as $byId
| (reduce $rels[] as $r ({}; reduce (($r.nodes) // [])[] as $n (.;
      .[($n.ref | tostring)] = ((.[($n.ref | tostring)] // []) + [{rel: $r, role: $n.role}]) ))) as $byNode
| ( [ $byNode | to_entries[] | (.key) as $nk | select($byId[$nk] != null)
      | .value[] | {id: .rel.id, level: .rel.level, tier: .rel.tier, role: .role,
                     name: rel_name(.rel), node_id: ($nk | tonumber), feature: $byId[$nk]} ] ) as $cands
| ( $cands | group_by(.id) | map(
      ( sort_by(cand_key($h)) | .[0] ) as $chosen
      | {relation_id: .[0].id, chosen: $chosen, candidates: .} ) ) as $groups
| ( $groups | map(.chosen) ) as $chosenCands
| ( $chosenCands | group_by(.node_id) | map(
      ( sort_by(primary_key($h)) | .[0] ) as $sel
      | {node_id: .[0].node_id, chosen: $sel} ) ) as $byNodeSel
# 冗余角色成员：某关系的候选节点未被选中、也未被任何关系选中，且其名字与被选中
# 节点名字有≥2 字公共前缀时（如 admin_centre 与 label 同名或简称/全称），判为同一
# 实体的冗余代表点而丢弃。名字差异大的（例如被某乡镇关系借用作 admin_centre 的真实
# 村庄）保留，避免误删独立地名。
| ( [ $groups[] as $g
      | ($g.chosen.node_id) as $keep
      | ( name_key($g.chosen.feature.properties) ) as $kname
      | $g.candidates[] | select(.node_id != $keep)
      | .node_id as $mid
      | select(([ $byNodeSel[].node_id ] | index($mid)) == null)
      | ( name_key(.feature.properties) ) as $nm
      | select(($nm != null) and ($kname != null) and (cplen($nm; $kname) >= 2))
      | {dropped_node_id: $mid, kept_node_id: $keep, reason: "redundant-role-member"} ] ) as $memberDups
| ( reduce $byNodeSel[] as $g ({}; .[($g.node_id | tostring)] = $g.chosen) ) as $assignments
| ( reduce $groups[] as $g
      ( {order: [], by: {}};
        ($g.chosen.node_id) as $nid
        | (.by[($nid | tostring)] // []) as $prev
        | .by[($nid | tostring)] = ($prev + [$g.chosen])
        | if ($prev | length) == 0 then .order = (.order + [$nid]) else . end
      ) ) as $nodeOrder
| ( [ $nodeOrder.order[] as $nid
      | ($nodeOrder.by[($nid | tostring)]) as $cs
      | select(($cs | length) > 1)
      | ( $cs | sort_by(primary_key($h)) ) as $s
      | {node_id: $nid, selected_admin_id: $s[0].id,
         discarded_admin_ids: ([$s[1:][] | .id] | sort)} ] ) as $shared
| ( reduce $rels[] as $r ({}; (rel_name($r)) as $nm
      | if $nm != null then .[$nm] = ((.[$nm] // []) + [$r]) else . end ) ) as $relByName
| ( reduce $groups[] as $g ({}; .[($g.relation_id | tostring)] = true) ) as $keptIds
| ( reduce $F[] as $f
      ( {dropped: [], cands: {}, kept: $keptIds};
        (fid($f)) as $i
        | if ($assignments[($i | tostring)] // null) != null then .
          elif ((["city", "county", "district", "town"] | index($f.properties.place))) == null then .
          else
            (name_key($f.properties)) as $nm
            | (if $nm != null then ($relByName[$nm] // []) else [] end) as $m
            | if ($m | length) != 1 then .
              elif (($keptIds[($m[0].id | tostring)]) // false) then
                # 关系 R 已由自身节点选中。判定同名字节点 P 是否与 R 同一实体：
                # 1) 双方都有 wikidata：同 QID=同实体→去重；不同 QID=异地同名→保留。
                # 2) 否则回退到边界包含：P 落在 R 的行政边界多边形内才判为冗余代表点。
                (($nodeWd[($i | tostring)] // null)) as $nwd
                | (($m[0].wikidata // null)) as $rwd
                | (if (($nwd != null) and ($rwd != null))
                     then $nwd == $rwd
                     else pip_multi($f.geometry.coordinates; ($boundMap[($m[0].id | tostring)] // []))
                   end) as $same
                | if $same
                    then .dropped += [{node_id: $i, admin_id: $m[0].id, reason: "relation-already-selected"}]
                    else . end
              else
                .cands[($m[0].id | tostring)] = ((.cands[($m[0].id | tostring)] // []) + [[$f, $m[0]]])
              end
          end
      ) ) as $fb
| ( reduce (($fb.cands | to_entries | sort_by(.key | tonumber))[]) as $e
      ( {assign: $assignments, dropped: ($fb.dropped | map(.node_id)), count: 0, extra: []};
        ( $e.value | sort_by([ (- pop_of(.[0])), ((fid(.[0])) // 9223372036854775807) ]) | .[0] ) as $win
        | ($win[1]) as $rel
        | { assign: (.assign + {((fid($win[0])) | tostring):
              {id: $rel.id, level: $rel.level, tier: $rel.tier, role: "name-fallback"}}),
            dropped: (.dropped + [ $e.value[] | select(fid(.[0]) != fid($win[0])) | fid(.[0]) ]),
            count: (.count + 1),
            extra: (.extra + [ $e.value[] | select(fid(.[0]) != fid($win[0]))
                     | {node_id: fid(.[0]), admin_id: $rel.id, reason: "fallback-canonical-lost"} ]) }
      ) ) as $fb2
| ( [ $F[] as $f
      | (fid($f)) as $i
      | select(($fb2.dropped | index($i)) == null)
      | ($fb2.assign[($i | tostring)] // null) as $c
      | ( if ($c != null and ($c.tier // null) != null and $c.tier != "") then $c.tier
          else ($h.place_fallback_tier[($f.properties.place // "default")] // $h.place_fallback_tier.default) end ) as $tier
      | ( ((pop_of($f)) | floor) | (if . < 0 then 0 else . end) | (if . > 999999999 then 999999999 else . end) ) as $p
      | $f
      | (if $c != null
           then (.properties.admin_id = $c.id
                 | (if $c.level != null then .properties.boundary_admin_level = $c.level else . end))
           else . end)
      # 显示名覆盖延后到全部去重之后（见 $out）：覆盖会改写 name_key，若在去重前应用，
      # 会让“同一实体但覆盖应用不一致”的节点名字分歧，导致精确/同名同层去重漏判。
      | .properties.label_tier = $tier
      | .properties.label_rank = (($h.rank[$tier]) * 1000000000 + $p)
      | ($h.tier_zoom[$tier] // $h.tier_zoom.default) as $tz
      | .tippecanoe = ({ minzoom: $tz.minzoom }
                       + (if ($tz.maxzoom // null) != null then { maxzoom: $tz.maxzoom } else {} end))
    ] ) as $out0
| ( [ $out0 | group_by([ (name_key(.properties)), .properties.place, (.geometry.coordinates | tojson) ])[]
      | . as $grp
      | ( $grp | sort_by([ (if (.properties.admin_id != null) then -1 else 0 end),
                           (- pop_of(.)), ((fid(.)) // 9223372036854775807) ]) | .[0] ) as $w
      | $grp[] | select(fid(.) != fid($w))
      | {dropped_node_id: fid(.), kept_node_id: fid($w), reason: "exact-duplicate"} ] ) as $exactDups
# 同名同层去重：某层级下同名候选恰好只有一个带 admin_id 时，丢弃其余无 admin_id 的冗余点。
# 0 个或 ≥2 个 admin_id 的同名点视为合法重名，保留。
| ( [ $out0
      | group_by([ (name_key(.properties)), .properties.label_tier ])[]
      | . as $grp
      | ( [ $grp[] | select(.properties.admin_id != null) ] ) as $withId
      | select(($withId | length) == 1
               and ((($h.dedupe_name_tiers // []) | index($grp[0].properties.label_tier)) != null))
      | $grp[] | select(.properties.admin_id == null)
      | {dropped_node_id: fid(.), kept_node_id: fid($withId[0]), reason: "same-name-tier-redundant"} ] ) as $nameDups
| ( [ $exactDups[].dropped_node_id ] + [ $nameDups[].dropped_node_id ] + [ $memberDups[].dropped_node_id ] ) as $dropped
| ( [ $out0[] | . as $f | select(($dropped | index(fid($f))) == null)
      | (.properties |= del(.["@id"]))
      # 行政地名显示名：去重后再用 official_name（官方全称）覆盖渲染字段，不影响去重键。
      # 限行政层级（省市县镇乡）；locality 层仅当 official_name 含 locality_keywords 时例外。
      | (.properties.official_name // null) as $on
      | (.properties.label_tier) as $lvl
      | (if (($adn.enabled // false)
             and ( ((($adn.tiers // []) | index($lvl)) != null)
                   or ($on != null and ([ ($adn.locality_keywords // [])[] as $k | ($on | contains($k)) ] | any)) )
             and adn_ok((.properties.name // null); $on))
           then (reduce ($adn.target_fields // [])[] as $k (.; .properties[$k] = $on))
           else . end) ] ) as $out
| ( if ($adn.enabled // false)
      then ([ $F[] as $f
              | (fid($f)) as $i
              | select(($fb2.dropped | index($i)) == null)
              | ($fb2.assign[($i | tostring)] // null) as $c
              | ( if ($c != null and ($c.tier // null) != null and $c.tier != "") then $c.tier
                  else ($h.place_fallback_tier[($f.properties.place // "default")] // $h.place_fallback_tier.default) end ) as $tier
              | ($f.properties.official_name // null) as $on
              | select( ((($adn.tiers // []) | index($tier)) != null)
                        or ($on != null and ([ ($adn.locality_keywords // [])[] as $k | ($on | contains($k)) ] | any)) )
              | select(adn_ok($f.properties.name; $on)) ] | length)
      else 0 end ) as $adnCount
| { features: $out,
    report: {
      schema_version: 1,
      source: {place_feature_count: ($F | length), administrative_relation_count: ($rels | length)},
      summary: {
        role_member_relations_with_place_candidates: ($groups | length),
        role_member_canonical_feature_count: ($byNodeSel | length),
        fallback_canonical_feature_count: $fb2.count,
        fallback_dropped_count: (($fb.dropped | length) + ($fb2.extra | length)),
        exact_duplicate_dropped_count: ($exactDups | length),
        same_name_tier_dropped_count: ($nameDups | length),
        redundant_role_member_dropped_count: ($memberDups | length),
        admin_display_name_override_count: $adnCount,
        output_feature_count: ($out | length)
      },
      relations: [ $groups[] | {admin_id: .relation_id,
          selected_node_id: .chosen.node_id,
          selected_role: .chosen.role,
          selected_tier: .chosen.tier,
          candidate_node_ids: ([.candidates[] | .node_id] | unique | sort)} ],
      shared_member_choices: $shared,
      fallback_dropped: ($fb.dropped + $fb2.extra),
      exact_duplicates: $exactDups,
      same_name_tier_duplicates: $nameDups,
      redundant_role_members: $memberDups
    } }
JQ
)

log_info "enrich place_label with administrative relations"
jq --seq -n -c \
  --slurpfile hierarchy "${hierarchy}" \
  --argjson adn "${adn_config}" \
  --slurpfile relations "${relations_index}" \
  --slurpfile node_wd "${node_wikidata_index}" \
  --slurpfile boundaries "${boundaries_index}" \
  "${jq_program}" "${place_labels}" > "${combined}" \
  || die "${HUAVD_EXIT_ERROR}" "place-label administrative enrichment failed"

jq --seq -c '.report' "${combined}" | tail -c +2 > "${report}" \
  || die "${HUAVD_EXIT_ERROR}" "place-label administrative report failed"
jq --seq -c '.features[]' "${combined}" > "${tmp}" \
  || die "${HUAVD_EXIT_ERROR}" "place-label administrative output failed"

mv "${tmp}" "${place_labels}"
log_info "place-label administrative enrichment OK: ${report}"
