WORKDIR        ?= /tmp/huavd-map-build
REGION         ?= china/guangxi
YYYYMMDD       ?= $(shell date -u +%Y%m%d)
SESSION        ?= $(shell echo $(REGION) | tr '/' '-')-$(YYYYMMDD)
WORKDIR_ROOT   ?= $(WORKDIR)
WORKDIR_ROOT   := $(WORKDIR_ROOT)
RELEASE_WORKDIR ?= $(WORKDIR_ROOT)/$(SESSION)
REGION_BASENAME ?= $(notdir $(REGION))
REGION_SLUG     ?= $(shell echo $(REGION) | tr '/' '-')
INPUT          ?=
ROLE           ?= both
FORMAT         ?= both
IMPORT_FORMAT  ?= zip
GLYPH          ?= 0
FORCE_BUILDING ?= 0
OVERVIEW       ?= south-china-overview
DERIVED_MAP    ?= china-base
ASSET          ?= china-regional-osm
HUAVD_MAP_BUILD_MACHINE_HOME ?= /opt/huavd-map-build

.PHONY: init init-workdir install-config init-build-machine-workdir install-build-machine-config setup doctor catalog fetch fetch-dem build build-dem build-overview raster-estimate source-inventory derived-inventory adapter-run compose-layers build-derived-map glyph sprite style verify verify-dem verify-overview verify-derived-map pack pack-overview pack-derived-map pack-tar pack-zip prepare-import prepare-import-all prepare-import-release prepare-import-release-all prepare-derived-import clean all release release-tar release-zip release-import release-import-all lint diff-products

init: init-workdir

init-workdir:
	HUAVD_MAP_BUILD_HOME="$(WORKDIR)" \
	HUAVD_MAP_BUILD_SESSION="$(SESSION)" \
	./scripts/init-workdir.sh

install-config:
	HUAVD_MAP_BUILD_HOME="$(WORKDIR)" \
	HUAVD_MAP_BUILD_SESSION="$(SESSION)" \
	HUAVD_MAP_BUILD_COPY_CONFIG=1 \
	./scripts/init-workdir.sh

init-build-machine-workdir:
	HUAVD_MAP_BUILD_HOME="$(HUAVD_MAP_BUILD_MACHINE_HOME)" \
	HUAVD_MAP_BUILD_SESSION="$(SESSION)" \
	./scripts/init-workdir.sh

install-build-machine-config:
	HUAVD_MAP_BUILD_HOME="$(HUAVD_MAP_BUILD_MACHINE_HOME)" \
	HUAVD_MAP_BUILD_SESSION="$(SESSION)" \
	HUAVD_MAP_BUILD_COPY_CONFIG=1 \
	./scripts/init-workdir.sh

setup:
	./scripts/setup-tools.sh

doctor:
	WORKDIR="$(WORKDIR)" ./scripts/doctor.sh

catalog:
	./scripts/manifest-catalog.sh

fetch: init-workdir
	WORKDIR="$(WORKDIR)" ./scripts/fetch.sh --region="$(REGION)"

fetch-dem: init-workdir
	WORKDIR="$(WORKDIR)" ./scripts/fetch-dem.sh --region="$(REGION)" --session="$(SESSION)" --source="$(DEM_SOURCE)" $(if $(DEM_INPUT),--input="$(DEM_INPUT)",)

build: init-workdir
	input="$(INPUT)"; \
	if [ -z "$$input" ]; then \
	  basename="$$(WORKDIR="$(WORKDIR)" REGION="$(REGION)" ./scripts/region-pbf-basename.sh "$(REGION)" 2>/dev/null || printf '%s-latest.osm.pbf\n' "$(REGION_BASENAME)")"; \
	  input="mirror/$$basename"; \
	fi; \
	WORKDIR="$(WORKDIR)" GLYPH="$(GLYPH)" FORCE_BUILDING="$(FORCE_BUILDING)" ./scripts/build.sh --input="$$input" --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --role="$(ROLE)" --glyph="$(GLYPH)" $(if $(filter 1,$(FORCE_BUILDING)),--force-building,)

raster-estimate:
	WORKDIR="$(WORKDIR)" ./scripts/render-bake.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --estimate $(if $(BAKE_MAX_TILES),--max-tiles="$(BAKE_MAX_TILES)",)

build-dem: init-workdir
	WORKDIR="$(WORKDIR)" ./scripts/build-dem.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" $(if $(DEM_SOURCE),--source="$(DEM_SOURCE)",) $(if $(DEM_INPUT),--input="$(DEM_INPUT)",) $(if $(DEM_ENCODING),--encoding="$(DEM_ENCODING)",)

build-overview: init-workdir
	WORKDIR="$(WORKDIR)" ./scripts/build-overview.sh --overview="$(OVERVIEW)" --yyyymmdd="$(YYYYMMDD)" $(if $(filter 1,$(FORCE)),--force,)

source-inventory:
	WORKDIR="$(WORKDIR)" ./scripts/source-inventory.sh --asset="$(ASSET)"

derived-inventory:
	WORKDIR="$(WORKDIR)" ./scripts/derived-inventory.sh --derived-map="$(DERIVED_MAP)"

adapter-run:
	WORKDIR="$(WORKDIR)" ./scripts/adapter-run.sh --asset="$(ASSET)" --yyyymmdd="$(YYYYMMDD)" $(if $(filter 1,$(FORCE)),--force,)

compose-layers:
	WORKDIR="$(WORKDIR)" ./scripts/compose-layers.sh --derived-map="$(DERIVED_MAP)" --yyyymmdd="$(YYYYMMDD)" $(if $(filter 1,$(FORCE)),--force,)

build-derived-map: init-workdir
	WORKDIR="$(WORKDIR)" GLYPH="$(GLYPH)" ./scripts/build-derived-map.sh --derived-map="$(DERIVED_MAP)" --yyyymmdd="$(YYYYMMDD)" --glyph="$(GLYPH)" $(if $(filter 1,$(FORCE)),--force,)

verify-overview:
	WORKDIR="$(WORKDIR)" ./scripts/verify-overview.sh --overview="$(OVERVIEW)" --yyyymmdd="$(YYYYMMDD)"

verify-derived-map:
	WORKDIR="$(WORKDIR)" ./scripts/verify-derived-map.sh --derived-map="$(DERIVED_MAP)" --yyyymmdd="$(YYYYMMDD)" --strict

pack-overview:
	WORKDIR="$(WORKDIR)" ./scripts/pack-overview.sh --overview="$(OVERVIEW)" --yyyymmdd="$(YYYYMMDD)" --format="$(FORMAT)"

pack-derived-map:
	WORKDIR="$(WORKDIR)" ./scripts/pack-derived-map.sh --derived-map="$(DERIVED_MAP)" --yyyymmdd="$(YYYYMMDD)" --format="$(FORMAT)"

glyph: init-workdir
	WORKDIR="$(WORKDIR)" ./scripts/glyph.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --force

sprite: init-workdir
	WORKDIR="$(WORKDIR)" ./scripts/sprite.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --force

style: init-workdir
	WORKDIR="$(WORKDIR)" ./scripts/style.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)"

verify:
	WORKDIR="$(WORKDIR)" ./scripts/verify.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --role="$(ROLE)"

verify-dem:
	WORKDIR="$(WORKDIR)" ./scripts/verify.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --role=dem --strict

pack:
	WORKDIR="$(WORKDIR)" ./scripts/pack.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --role="$(ROLE)" --format="$(FORMAT)"

pack-tar:
	WORKDIR="$(WORKDIR)" ./scripts/pack.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --role="$(ROLE)" --format=tar

pack-zip:
	WORKDIR="$(WORKDIR)" ./scripts/pack.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --role="$(ROLE)" --format=zip

prepare-import:
	role="$(ROLE)"; \
	if [ "$$role" = "both" ]; then role="base"; fi; \
	WORKDIR="$(WORKDIR)" ./scripts/prepare-import.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --role="$$role" --format="$(IMPORT_FORMAT)"

prepare-import-all:
	WORKDIR="$(WORKDIR)" ./scripts/prepare-import.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --role=both --format="$(IMPORT_FORMAT)"

prepare-derived-import:
	WORKDIR="$(WORKDIR)" ./scripts/prepare-derived-import.sh --derived-map="$(DERIVED_MAP)" --yyyymmdd="$(YYYYMMDD)" --format="$(IMPORT_FORMAT)"

lint:
	WORKDIR="$${WORKDIR:-/tmp/huavd-map-build}" ./scripts/style-lint.sh
	WORKDIR="$${WORKDIR:-/tmp/huavd-map-build}" ./scripts/viewport-lint.sh

diff-products:
	@if [[ -z "$(REGION_A)" || -z "$(REGION_B)" ]]; then \
		echo "usage: make diff-products REGION_A=china/guangxi REGION_B=china/guangdong"; exit 1; \
	fi
	WORKDIR="$${WORKDIR:-/tmp/huavd-map-build}" ./scripts/diff-region-products.sh "$(REGION_A)" "$(REGION_B)" "$(YYYYMMDD)"

clean:
	rm -rf "$(WORKDIR)/staging/$(SESSION)" \
	  "$(WORKDIR)/cache/configs" \
	  "$(WORKDIR)/cache/import/$(SESSION)" \
	  "$(WORKDIR)/cache/pack/$(SESSION)" \
	  "$(WORKDIR)/cache/tags-filter/$(REGION_SLUG)-"*.osm.pbf \
	  "$(WORKDIR)/outputs/$(SESSION).import.tar.gz" \
	  "$(WORKDIR)/outputs/$(SESSION).import.tar.gz.sha512" \
	  "$(WORKDIR)/outputs/$(SESSION).import.zip" \
	  "$(WORKDIR)/outputs/$(SESSION).import.zip.sha512" \
	  "$(WORKDIR)/outputs/$(SESSION).bundle.tar.gz" \
	  "$(WORKDIR)/outputs/$(SESSION).bundle.tar.gz.sha512" \
	  "$(WORKDIR)/outputs/$(SESSION).bundle.zip" \
	  "$(WORKDIR)/outputs/$(SESSION).bundle.zip.sha512" \
	  "$(WORKDIR)/outputs/$(SESSION).base.pmtiles" \
	  "$(WORKDIR)/outputs/$(SESSION).base.pmtiles.sha512" \
	  "$(WORKDIR)/outputs/$(SESSION).base.manifest.json" \
	  "$(WORKDIR)/outputs/$(SESSION).base.attribution.json" \
	  "$(WORKDIR)/outputs/$(SESSION).building.pmtiles" \
	  "$(WORKDIR)/outputs/$(SESSION).building.pmtiles.sha512" \
	  "$(WORKDIR)/outputs/$(SESSION).building.manifest.json" \
	  "$(WORKDIR)/outputs/$(SESSION).building.attribution.json" \
	  "$(WORKDIR)/outputs/$(SESSION).raster_bake.pmtiles" \
	  "$(WORKDIR)/outputs/$(SESSION).raster_bake.pmtiles.sha512" \
	  "$(WORKDIR)/outputs/$(SESSION).raster_bake.manifest.json" \
	  "$(WORKDIR)/outputs/$(SESSION).raster_bake.attribution.json" \
	  "$(WORKDIR)/outputs/$(SESSION).dem.pmtiles" \
	  "$(WORKDIR)/outputs/$(SESSION).dem.pmtiles.sha512" \
	  "$(WORKDIR)/outputs/$(SESSION).dem.manifest.json" \
	  "$(WORKDIR)/outputs/$(SESSION).dem.attribution.json" \
	  "$(WORKDIR)/outputs/$(SESSION).glyphs" \
	  "$(WORKDIR)/outputs/$(SESSION).sprite" \
	  "$(WORKDIR)/outputs/$(SESSION).style.json" \
	  "$(WORKDIR)/outputs/$(SESSION).style.json.sha512" \
	  "$(WORKDIR)/outputs/$(SESSION).style-raster.json" \
	  "$(WORKDIR)/outputs/$(SESSION).style-raster.json.sha512" \
	  "$(WORKDIR)/cache/bake/$(SESSION)"
	find "$(WORKDIR)/cache" "$(WORKDIR)/staging" "$(WORKDIR)/outputs" -depth -type d -empty -delete 2>/dev/null || true

all: build pack

release release-tar release-zip prepare-import-release prepare-import-release-all release-import release-import-all: override WORKDIR := $(RELEASE_WORKDIR)

release: build pack verify

release-tar: build pack-tar verify

release-zip: build pack-zip verify

prepare-import-release: prepare-import

prepare-import-release-all: prepare-import-all

release-import: build pack verify prepare-import

release-import-all: build pack verify prepare-import-all
