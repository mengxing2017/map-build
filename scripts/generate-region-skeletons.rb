#!/usr/bin/env ruby
# frozen_string_literal: true

require "csv"
require "optparse"
require "yaml"

SCRIPT_DIR = File.expand_path(__dir__)
REPO_ROOT = File.expand_path("..", SCRIPT_DIR)

CONTINENTS = {
  "africa" => {
    "display_name" => "Africa",
    "url_slug" => "africa",
    "region_id" => "un-002-base"
  },
  "antarctica" => {
    "display_name" => "Antarctica",
    "url_slug" => "antarctica",
    "region_id" => "aq-base"
  },
  "asia" => {
    "display_name" => "Asia",
    "url_slug" => "asia",
    "region_id" => "un-142-base"
  },
  "australia-oceania" => {
    "display_name" => "Australia / Oceania",
    "url_slug" => "australia-oceania",
    "region_id" => "un-009-base"
  },
  "europe" => {
    "display_name" => "Europe",
    "url_slug" => "europe",
    "region_id" => "un-150-base"
  },
  "north-america" => {
    "display_name" => "North America",
    "url_slug" => "north-america",
    "region_id" => "un-003-base"
  },
  "south-america" => {
    "display_name" => "South America",
    "url_slug" => "south-america",
    "region_id" => "un-005-base"
  }
}.freeze

COUNTRY_ID_OVERRIDES = {
  "AQ" => "antarctica",
  "CN" => "china",
  "ID" => "indonesia",
  "IN" => "india",
  "JP" => "japan",
  "MO" => "china/macau",
  "PH" => "philippines",
  "RU" => "russia",
  "TH" => "thailand",
  "TW" => "china/taiwan"
}.freeze

COUNTRY_PARENT_OVERRIDES = {
  "MO" => "china",
  "TW" => "china"
}.freeze

COUNTRY_REGION_ID_OVERRIDES = {
  "MO" => "cn-92-base",
  "TW" => "cn-71-base"
}.freeze

SUBDIVISION_ID_OVERRIDES = {
  "CN-44" => "china/guangdong",
  "CN-45" => "china/guangxi",
  "CN-53" => "china/yunnan"
}.freeze

SUBDIVISION_COUNTRY_EXCLUDES = %w[
  MO
].freeze

SOUTH_AMERICA = %w[
  AR BO BR CL CO EC FK GF GY PE PY SR UY VE
].freeze

INDIAN_OCEAN_OVERRIDES = {
  "CC" => "australia-oceania",
  "CX" => "australia-oceania",
  "IO" => "asia",
  "KM" => "africa",
  "MG" => "africa",
  "MV" => "asia",
  "MU" => "africa",
  "RE" => "africa",
  "SC" => "africa",
  "TF" => "antarctica",
  "YT" => "africa"
}.freeze

ATLANTIC_OVERRIDES = {
  "BM" => "north-america",
  "CV" => "africa",
  "FK" => "south-america",
  "FO" => "europe",
  "GS" => "south-america",
  "IS" => "europe",
  "PT" => "europe",
  "SH" => "africa"
}.freeze

COUNTRY_CONTINENT_OVERRIDES = {
  "AN" => "north-america",
  "BV" => "antarctica",
  "HM" => "antarctica",
  "TP" => "asia",
  "YU" => "europe"
}.freeze

options = {
  iso_csv: nil,
  existing_config: File.join(REPO_ROOT, "config", "regions.yaml"),
  output: nil
}

OptionParser.new do |parser|
  parser.banner = "usage: #{$PROGRAM_NAME} --iso3166-2-csv=<path> [--existing-config=config/regions.yaml] [--output=config/regions.yaml]"
  parser.on("--iso3166-2-csv=PATH", "ISO 3166-2 CSV path") { |value| options[:iso_csv] = value }
  parser.on("--existing-config=PATH", "Existing regions.yaml path") { |value| options[:existing_config] = value }
  parser.on("--output=PATH", "Write merged regions.yaml to PATH; stdout prints skeleton entries when omitted") { |value| options[:output] = value }
  parser.on("-h", "--help", "Show help") do
    puts parser
    exit 0
  end
end.parse!

abort "--iso3166-2-csv is required" if options[:iso_csv].nil? || options[:iso_csv].empty?
abort "ISO CSV not found: #{options[:iso_csv]}" unless File.file?(options[:iso_csv])
abort "existing config not found: #{options[:existing_config]}" unless File.file?(options[:existing_config])

def slugify(value)
  ascii = value.to_s.unicode_normalize(:nfkd).encode("ASCII", invalid: :replace, undef: :replace, replace: "")
  slug = ascii.downcase.gsub(/&/, " and ").gsub(/[^a-z0-9]+/, "-").gsub(/\A-+|-+\z/, "").gsub(/-+/, "-")
  slug.empty? ? "unnamed" : slug
end

def stable_id_from_iso(code)
  parts = code.downcase.tr("_", "-").split("-")
  normalized = [parts.first] + parts.drop(1).map { |part| part.length == 1 ? "0#{part}" : part }
  "#{normalized.join("-")}-base"
end

def unique_stable_id_from_iso(code, name, used_region_ids)
  candidate = stable_id_from_iso(code)
  if used_region_ids.key?(candidate)
    stem = candidate.delete_suffix("-base")
    name_slug = slugify(name)
    candidate = "#{stem}-#{name_slug}-base"
    index = 2
    while used_region_ids.key?(candidate)
      candidate = "#{stem}-#{name_slug}-#{index}-base"
      index += 1
    end
  end
  used_region_ids[candidate] = true
  candidate
end

def zone_country_continents
  mapping = {}
  path = "/usr/share/zoneinfo/zone.tab"
  return mapping unless File.file?(path)

  File.readlines(path, chomp: true).each do |line|
    next if line.empty? || line.start_with?("#")

    country_code, _coords, zone_name = line.split("\t", 4)
    next if country_code.to_s.empty? || zone_name.to_s.empty?
    next if mapping.key?(country_code)

    area = zone_name.split("/", 2).first
    mapping[country_code] =
      case area
      when "Africa" then "africa"
      when "Antarctica" then "antarctica"
      when "Asia" then "asia"
      when "Australia", "Pacific" then "australia-oceania"
      when "Europe", "Arctic" then "europe"
      when "America" then SOUTH_AMERICA.include?(country_code) ? "south-america" : "north-america"
      when "Indian" then INDIAN_OCEAN_OVERRIDES[country_code]
      when "Atlantic" then ATLANTIC_OVERRIDES[country_code]
      end
  end
  mapping.compact.merge(COUNTRY_CONTINENT_OVERRIDES)
end

def continent_entry(id, existing = nil)
  spec = CONTINENTS.fetch(id)
  merged = existing ? Marshal.load(Marshal.dump(existing)) : {}
  merged["id"] = id
  merged["slug"] = id
  merged["display_name"] ||= spec.fetch("display_name")
  merged["priority"] ||= "split-source"
  merged["direct_tippecanoe"] = false
  merged["geofabrik"] ||= {}
  merged["geofabrik"]["pbf_url"] ||= "https://download.geofabrik.de/#{spec.fetch("url_slug")}-latest.osm.pbf"
  merged["geofabrik"]["md5_url"] ||= "https://download.geofabrik.de/#{spec.fetch("url_slug")}-latest.osm.pbf.md5"
  merged["geofabrik"]["basename"] ||= "#{spec.fetch("url_slug")}-latest.osm.pbf"
  merged["geofabrik"]["parent_region"] = nil
  merged["geofabrik"]["fallback"] = nil
  merged["huavd"] ||= {}
  merged["huavd"]["region_id"] ||= spec.fetch("region_id")
  merged["huavd"]["source_id"] = nil unless merged["huavd"].key?("source_id")
  merged["huavd"]["mapping_status"] ||= "not-direct-pmtiles"
  merged["huavd"]["asset_role"] ||= "base-vector"
  merged["huavd"]["source_type"] ||= "osm-pbf"
  merged["huavd"]["style_id"] ||= "osm-dev"
  merged["huavd"]["package_version_template"] = nil unless merged["huavd"].key?("package_version_template")
  merged
end

def skeleton_entry(id:, display_name:, parent_region:, region_id:)
  slug = id.tr("/", "-")
  {
    "id" => id,
    "slug" => slug,
    "display_name" => display_name,
    "priority" => "global-skeleton",
    "direct_tippecanoe" => true,
    "geofabrik" => {
      "pbf_url" => nil,
      "md5_url" => nil,
      "basename" => nil,
      "parent_region" => parent_region,
      "fallback" => nil
    },
    "huavd" => {
      "region_id" => region_id,
      "source_id" => nil,
      "mapping_status" => "pending-source-id",
      "package_version_template" => nil
    }
  }
end

def merge_generated(existing, generated)
  merged = existing ? Marshal.load(Marshal.dump(existing)) : generated
  merged["slug"] ||= generated.fetch("slug")
  merged["display_name"] ||= generated.fetch("display_name")
  merged["priority"] ||= generated.fetch("priority")
  merged["direct_tippecanoe"] = generated.fetch("direct_tippecanoe") unless merged.key?("direct_tippecanoe")
  merged["geofabrik"] ||= {}
  generated.fetch("geofabrik").each do |key, value|
    merged["geofabrik"][key] = value unless merged["geofabrik"].key?(key)
  end
  merged["geofabrik"]["parent_region"] = generated.fetch("geofabrik").fetch("parent_region") if merged["geofabrik"]["parent_region"].nil?
  merged["huavd"] ||= {}
  if merged["priority"] == "global-skeleton"
    merged["huavd"]["region_id"] = generated.fetch("huavd").fetch("region_id")
  else
    merged["huavd"]["region_id"] ||= generated.fetch("huavd").fetch("region_id")
  end
  merged["huavd"]["source_id"] = nil unless merged["huavd"].key?("source_id")
  merged["huavd"]["mapping_status"] ||= generated.fetch("huavd").fetch("mapping_status")
  merged["huavd"]["package_version_template"] = nil unless merged["huavd"].key?("package_version_template")
  merged
end

def yaml_quote(value)
  "\"#{value.to_s.gsub("\\", "\\\\\\").gsub("\"", "\\\"")}\""
end

def scalar_yaml(value)
  case value
  when NilClass then "null"
  when TrueClass then "true"
  when FalseClass then "false"
  when Numeric then value.to_s
  else yaml_quote(value)
  end
end

def emit_yaml(value, indent = 0)
  prefix = " " * indent
  case value
  when Hash
    value.map do |key, child|
      if child.is_a?(Hash) || child.is_a?(Array)
        "#{prefix}#{key}:\n#{emit_yaml(child, indent + 2)}"
      else
        "#{prefix}#{key}: #{scalar_yaml(child)}"
      end
    end.join("\n")
  when Array
    value.map do |child|
      if child.is_a?(Hash)
        first_key, first_value = child.first
        rest = child.drop(1).to_h
        if first_value.is_a?(Hash) || first_value.is_a?(Array)
          ["#{prefix}- #{first_key}:", emit_yaml(first_value, indent + 4), emit_yaml(rest, indent + 2)].reject(&:empty?).join("\n")
        else
          ["#{prefix}- #{first_key}: #{scalar_yaml(first_value)}", emit_yaml(rest, indent + 2)].reject(&:empty?).join("\n")
        end
      else
        "#{prefix}- #{scalar_yaml(child)}"
      end
    end.join("\n")
  else
    "#{prefix}#{scalar_yaml(value)}"
  end
end

config = YAML.load_file(options[:existing_config])
existing_by_id = (config["regions"] || []).to_h { |region| [region.fetch("id"), region] }
continent_by_country = zone_country_continents

country_info = {}
subdivision_info = []
current_country = nil
current_admin1 = nil
current_admin1_key = nil

CSV.foreach(options[:iso_csv], encoding: "UTF-8") do |row|
  row = row.map { |value| value.to_s.strip }
  country_code, admin1_code, admin2_code, name = row
  if !country_code.empty?
    current_country = country_code
    current_admin1 = nil
    current_admin1_key = nil
    country_info[country_code] = {
      "code" => country_code,
      "name" => name
    }
  elsif !admin1_code.empty?
    abort "subdivision without country at #{admin1_code}" unless current_country
    current_admin1 = admin1_code
    current_admin1_key = "#{admin1_code}@#{subdivision_info.length}"
    subdivision_info << {
      "key" => current_admin1_key,
      "level" => 1,
      "country_code" => current_country,
      "code" => admin1_code,
      "name" => name,
      "parent_key" => current_country
    }
  elsif !admin2_code.empty?
    abort "nested subdivision without admin-1 at #{admin2_code}" unless current_country && current_admin1 && current_admin1_key
    subdivision_info << {
      "key" => "#{admin2_code}@#{subdivision_info.length}",
      "level" => 2,
      "country_code" => current_country,
      "code" => admin2_code,
      "name" => name,
      "parent_key" => current_admin1_key
    }
  end
end

country_ids = {}
used_ids = CONTINENTS.keys.to_h { |id| [id, true] }
country_info.each do |code, info|
  base = COUNTRY_ID_OVERRIDES[code] || slugify(info.fetch("name"))
  id = base
  index = 1
  while used_ids.key?(id) && !(code == "AQ" && id == "antarctica")
    id = index == 1 ? "#{base}-#{code.downcase}" : "#{base}-#{code.downcase}-#{index}"
    index += 1
  end
  used_ids[id] = true
  country_ids[code] = id
end

subdivision_ids = {}
subdivision_info.each do |info|
  parent_id =
    if info.fetch("level") == 1
      country_ids.fetch(info.fetch("country_code"))
    else
      subdivision_ids.fetch(info.fetch("parent_key"))
  end
  base = SUBDIVISION_ID_OVERRIDES[info.fetch("code")] || "#{parent_id}/#{slugify(info.fetch("name"))}"
  id = base
  suffix = info.fetch("code").split("-", 2).last.downcase
  index = 1
  while used_ids.key?(id)
    id = index == 1 ? "#{base}-#{suffix}" : "#{base}-#{suffix}-#{index}"
    index += 1
  end
  used_ids[id] = true
  subdivision_ids[info.fetch("key")] = id
end

generated_by_id = {}
CONTINENTS.keys.each do |continent_id|
  generated_by_id[continent_id] = continent_entry(continent_id, existing_by_id[continent_id])
end

used_region_ids = CONTINENTS.values.to_h { |spec| [spec.fetch("region_id"), true] }
country_region_ids = {}
country_info.each do |code, info|
  next if code == "AQ"

  parent = COUNTRY_PARENT_OVERRIDES[code] || continent_by_country[code]
  abort "country has no continent mapping: #{code} #{info.fetch("name")}" if parent.nil? || parent.empty?
  id = country_ids.fetch(code)
  country_region_ids[code] =
    if COUNTRY_REGION_ID_OVERRIDES.key?(code)
      region_id = COUNTRY_REGION_ID_OVERRIDES.fetch(code)
      abort "duplicate region_id override: #{region_id}" if used_region_ids.key?(region_id)
      used_region_ids[region_id] = true
      region_id
    else
      unique_stable_id_from_iso(code, info.fetch("name"), used_region_ids)
    end
  generated_by_id[id] = skeleton_entry(
    id: id,
    display_name: info.fetch("name"),
    parent_region: parent,
    region_id: country_region_ids.fetch(code)
  )
end

subdivision_region_ids = {}
subdivision_info.each do |info|
  next if SUBDIVISION_COUNTRY_EXCLUDES.include?(info.fetch("country_code"))

  id = subdivision_ids.fetch(info.fetch("key"))
  parent =
    if info.fetch("level") == 1
      country_ids.fetch(info.fetch("country_code"))
    else
      subdivision_ids.fetch(info.fetch("parent_key"))
    end
  subdivision_region_ids[info.fetch("key")] = unique_stable_id_from_iso(
    info.fetch("code"),
    info.fetch("name"),
    used_region_ids
  )
  generated_by_id[id] = skeleton_entry(
    id: id,
    display_name: info.fetch("name"),
    parent_region: parent,
    region_id: subdivision_region_ids.fetch(info.fetch("key"))
  )
end

if options[:output]
  config["naming"] ||= {}
  config["naming"]["max_depth"] = 4
  config["naming"]["depth_segment_pattern"] = "^[a-z0-9]([a-z0-9-]*[a-z0-9])?$"
  config["naming"]["region_slug_examples"] ||= {}
  config["naming"]["region_slug_examples"]["china/guangxi/nanning"] = "china-guangxi-nanning"

  merged_by_id = {}
  ordered_regions = []

  generated_by_id.each do |id, generated|
    existing = existing_by_id[id]
    merged = id == "asia" || CONTINENTS.key?(id) ? continent_entry(id, existing) : merge_generated(existing, generated)
    merged_by_id[id] = merged
  end

  existing_by_id.each do |id, existing|
    next if merged_by_id.key?(id)

    merged_by_id[id] = existing
  end

  CONTINENTS.keys.each do |id|
    ordered_regions << merged_by_id.fetch(id)
  end
  country_info.each do |code, _info|
    ordered_regions << merged_by_id.fetch(country_ids.fetch(code)) unless code == "AQ"
    subdivision_info.select do |info|
      info.fetch("country_code") == code &&
        !SUBDIVISION_COUNTRY_EXCLUDES.include?(info.fetch("country_code"))
    end.each do |info|
      ordered_regions << merged_by_id.fetch(subdivision_ids.fetch(info.fetch("key")))
    end
  end
  existing_by_id.each_key do |id|
    ordered_regions << merged_by_id.fetch(id) unless ordered_regions.any? { |region| region.fetch("id") == id }
  end

  config["regions"] = ordered_regions
  File.write(options[:output], "#{emit_yaml(config)}\n")
else
  existing_ids = existing_by_id.keys.to_h { |id| [id, true] }
  skeletons = generated_by_id.reject { |id, _entry| existing_ids.key?(id) }.values
  puts emit_yaml(skeletons)
end
