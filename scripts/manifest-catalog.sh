#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "${script_dir}/.." && pwd)"
config_path="${CONFIG_PATH:-${repo_dir}/config/regions.yaml}"
output_path="${OUTPUT:-${repo_dir}/config/derived/catalog.json}"

ruby -ryaml -rjson -rfileutils - "${config_path}" "${output_path}" <<'RUBY'
config_path = ARGV.fetch(0)
output_path = ARGV.fetch(1)

config = YAML.load_file(config_path)
regions = config.fetch("regions")
source_id_mappings = config.fetch("source_id_mappings", {})
index = regions.each_with_object({}) do |region, output|
  id = region.fetch("id")
  abort("duplicate region id in regions.yaml: #{id}") if output.key?(id)
  output[id] = region
end

ZH_BY_ID = {
  "africa" => "非洲",
  "antarctica" => "南极洲",
  "asia" => "亚洲",
  "australia-oceania" => "大洋洲",
  "europe" => "欧洲",
  "north-america" => "北美洲",
  "south-america" => "南美洲",
  "china" => "中国大陆",
  "china/anhui" => "安徽省",
  "china/beijing" => "北京市",
  "china/chongqing" => "重庆市",
  "china/fujian" => "福建省",
  "china/gansu" => "甘肃省",
  "china/guangdong" => "广东省",
  "china/guangxi" => "广西壮族自治区",
  "china/guizhou" => "贵州省",
  "china/hainan" => "海南省",
  "china/hebei" => "河北省",
  "china/heilongjiang" => "黑龙江省",
  "china/henan" => "河南省",
  "china/hong-kong" => "香港特别行政区",
  "china/macau" => "澳门特别行政区",
  "china/hubei" => "湖北省",
  "china/hunan" => "湖南省",
  "china/jiangsu" => "江苏省",
  "china/jiangxi" => "江西省",
  "china/jilin" => "吉林省",
  "china/liaoning" => "辽宁省",
  "china/nei-monggol" => "内蒙古自治区",
  "china/ningxia" => "宁夏回族自治区",
  "china/qinghai" => "青海省",
  "china/shaanxi" => "陕西省",
  "china/shandong" => "山东省",
  "china/shanghai" => "上海市",
  "china/shanxi" => "山西省",
  "china/sichuan" => "四川省",
  "china/taiwan" => "台湾省",
  "china/taiwan/changhua" => "彰化县",
  "china/taiwan/chiayi" => "嘉义市",
  "china/taiwan/hsinchu" => "新竹市",
  "china/taiwan/hualien" => "花莲县",
  "china/taiwan/ilan" => "宜兰县",
  "china/taiwan/kaohsiung" => "高雄市",
  "china/taiwan/keelung" => "基隆市",
  "china/taiwan/miaoli" => "苗栗县",
  "china/taiwan/nantou" => "南投县",
  "china/taiwan/penghu" => "澎湖县",
  "china/taiwan/pingtung" => "屏东县",
  "china/taiwan/taichung" => "台中市",
  "china/taiwan/tainan" => "台南市",
  "china/taiwan/taipei" => "台北市",
  "china/taiwan/taitung" => "台东县",
  "china/taiwan/taoyuan" => "桃园市",
  "china/taiwan/yunlin" => "云林县",
  "china/tianjin" => "天津市",
  "china/xinjiang" => "新疆维吾尔自治区",
  "china/xizang" => "西藏自治区",
  "china/yunnan" => "云南省",
  "china/zhejiang" => "浙江省",
  "japan" => "日本",
  "india" => "印度",
  "united-states-of-america" => "美国"
}.freeze

ZH_BY_NAME = {
  "Africa" => "非洲",
  "Antarctica" => "南极洲",
  "Asia" => "亚洲",
  "Australia / Oceania" => "大洋洲",
  "Europe" => "欧洲",
  "North America" => "北美洲",
  "South America" => "南美洲",
  "China" => "中国",
  "China Mainland" => "中国大陆",
  "Guangxi" => "广西壮族自治区",
  "Japan" => "日本",
  "India" => "印度",
  "United States of America" => "美国"
}.freeze

def inherited(index, id, *path)
  current = id
  seen = {}

  while current
    abort("parent cycle while resolving #{id}") if seen[current]
    seen[current] = true
    region = index.fetch(current)
    value = region.dig(*path)
    return value unless value.nil? || value == ""
    current = region.dig("geofabrik", "parent_region")
  end

  nil
end

def source_id_for(index, source_id_mappings, id)
  current = id
  seen = {}

  while current
    abort("parent cycle while resolving source_id for #{id}") if seen[current]
    seen[current] = true
    region = index.fetch(current)
    source_id = region.dig("huavd", "source_id")
    return source_id unless source_id.nil? || source_id == ""

    mapped = source_id_mappings[current]
    return mapped unless mapped.nil? || mapped == ""

    current = region.dig("geofabrik", "parent_region")
  end

  nil
end

def depth_for(index, id, memo, visiting)
  return memo[id] if memo.key?(id)
  abort("parent cycle while computing depth for #{id}") if visiting.include?(id)

  region = index.fetch(id)
  parent = region.dig("geofabrik", "parent_region")
  memo[id] =
    if parent.nil?
      1
    else
      abort("parent_region does not exist for #{id}: #{parent}") unless index.key?(parent)
      depth_for(index, parent, memo, visiting + [id]) + 1
    end
end

def required(value, field, id)
  abort("missing #{field} for #{id}") if value.nil? || value == ""
  value
end

depths = {}
catalog_regions = regions.map do |region|
  id = region.fetch("id")
  huavd = region.fetch("huavd", {})
  parent_id = region.dig("geofabrik", "parent_region")
  parent_region_id = parent_id.nil? ? nil : required(index.fetch(parent_id).dig("huavd", "region_id"), "parent huavd.region_id", id)
  display_name = required(region["display_name"], "display_name", id)
  display_name_zh = region["display_name_zh"] || ZH_BY_ID[id] || ZH_BY_NAME[display_name] || display_name

  {
    "id" => id,
    "slug" => required(region["slug"], "slug", id),
    "region_id" => required(huavd["region_id"], "huavd.region_id", id),
    "depth" => depth_for(index, id, depths, []),
    "parent_region" => parent_region_id,
    "asset_role" => inherited(index, id, "huavd", "asset_role") || "base-vector",
    "source_id" => source_id_for(index, source_id_mappings, id),
    "source_type" => inherited(index, id, "huavd", "source_type") || "osm-pbf",
    "style_id" => inherited(index, id, "huavd", "style_id") || "osm-dev",
    "mapping_status" => huavd["mapping_status"] || inherited(index, id, "huavd", "mapping_status") || "pending-source-id",
    "priority" => required(region["priority"], "priority", id),
    "deprecated" => huavd.fetch("deprecated", false),
    "replacement_region_id" => huavd["replacement_region_id"],
    "display_name" => display_name,
    "display_name_zh" => display_name_zh
  }.tap do |entry|
    entry.delete("parent_region") if entry["parent_region"].nil?
    entry.delete("asset_role") if entry["asset_role"] == "base-vector"
    entry.delete("source_id") if entry["source_id"].nil?
    entry.delete("source_type") if entry["source_type"] == "osm-pbf"
    entry.delete("style_id") if entry["style_id"] == "osm-dev"
    entry.delete("mapping_status") if entry["mapping_status"] == "pending-source-id"
    entry.delete("priority") if entry["priority"] == "global-skeleton"
    entry.delete("deprecated") unless entry["deprecated"]
    entry.delete("replacement_region_id") if entry["replacement_region_id"].nil?
    entry.delete("display_name_zh") if entry["display_name_zh"] == entry["display_name"]
  end
end

snapshot = {
  "schema_version" => Integer(config.fetch("schema_version")),
  "regions" => catalog_regions
}

FileUtils.mkdir_p(File.dirname(output_path))
File.write(output_path, JSON.pretty_generate(snapshot) + "\n")
RUBY

printf 'wrote %s\n' "${output_path}"
