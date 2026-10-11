WORKDIR        ?= /tmp/huavd-map-build
.DEFAULT_GOAL := init
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
ARTIFACT_ROLE  ?= base
FORMAT         ?= both
IMPORT_FORMAT  ?= zip
GLYPH          ?= 0
FORCE_BUILDING ?= 0
FORCE          ?= 0
OVERVIEW       ?= south-china-overview
DERIVED_MAP    ?= china-base
ASSET          ?= china-regional-osm
HUAVD_MAP_BUILD_MACHINE_HOME ?= /opt/huavd-map-build
PYTHON         ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BAKE_RENDERER_ENGINE ?=
BAKE_RENDERER_COMMAND ?=
NATIVE_RENDERER_COMMAND ?=
BAKE_RENDERER_FLAGS = $(if $(BAKE_RENDERER_ENGINE),--renderer-engine="$(BAKE_RENDERER_ENGINE)",) $(if $(BAKE_RENDERER_COMMAND),--renderer-command="$(BAKE_RENDERER_COMMAND)",) $(if $(BAKE_DISPLAY_MODE),--display-mode="$(BAKE_DISPLAY_MODE)",) $(if $(BAKE_JOBS),--jobs="$(BAKE_JOBS)",) $(foreach sample,$(BAKE_SAMPLES),--sample="$(sample)")

.PHONY: setup-native-renderer check-native-renderer
setup-native-renderer:
	WORKDIR="$(WORKDIR)" bash scripts/setup-native-renderer.sh $(NATIVE_RENDERER_SETUP_ARGS)

check-native-renderer:
ifeq ($(strip $(NATIVE_RENDERER_COMMAND)),)
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build.production.south.adapter.process.native_tools check
else
	NATIVE_RENDERER_COMMAND="$(NATIVE_RENDERER_COMMAND)" PYTHONPATH=backend/src bash scripts/native-renderer-env.sh $(PYTHON) -c 'import os; from huavd_map_build.production.south.adapter.process.raster_native import native_renderer_identity; print(native_renderer_identity(os.environ["NATIVE_RENDERER_COMMAND"]))'
	bash scripts/native-renderer-env.sh "$(NATIVE_RENDERER_COMMAND)" --self-test
endif

.PHONY: init init-workdir python-workspace-init install-config init-build-machine-workdir install-build-machine-config setup doctor python-doctor catalog python-catalog-validate python-catalog-shadow python-build-plan python-artifact-paths python-test fetch fetch-dem build build-dem build-overview raster-estimate source-inventory derived-inventory adapter-run compose-layers build-derived-map glyph sprite style verify verify-dem verify-overview verify-derived-map pack pack-overview pack-derived-map pack-tar pack-zip prepare-import prepare-import-all prepare-import-release prepare-import-release-all prepare-derived-import clean all release release-tar release-zip release-import release-import-all lint diff-products

init: init-workdir

init-workdir:
	HUAVD_MAP_BUILD_HOME="$(WORKDIR)" \
	HUAVD_MAP_BUILD_SESSION="$(SESSION)" \
	./scripts/init-workdir.sh

python-workspace-init:
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build workspace init --workdir="$(WORKDIR)" --session="$(SESSION)"

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

python-doctor:
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build doctor --strict

catalog:
	./scripts/manifest-catalog.sh

python-catalog-validate:
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build catalog validate

python-catalog-shadow:
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build catalog region "$(REGION)" --role="$(ROLE)" --yyyymmdd="$(YYYYMMDD)"
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build catalog tippecanoe "$(REGION)" --role="$(firstword $(subst _, ,$(ROLE)))"
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build catalog raster-bake "$(REGION)"
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build catalog vector-layers "$(REGION)" --role="$(firstword $(subst _, ,$(ROLE)))"

python-build-plan:
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build build plan --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --role="$(ROLE)" --workdir="$(WORKDIR)" $(if $(INPUT),--input="$(INPUT)",)

python-artifact-paths:
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build artifact paths --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --role="$(ARTIFACT_ROLE)" --workdir="$(WORKDIR)"

python-test:
	PYTHONPATH=backend/src $(PYTHON) -m unittest discover -s backend/tests -v

fetch: init-workdir
	WORKDIR="$(WORKDIR)" ./scripts/fetch.sh --region="$(REGION)"

fetch-dem: init-workdir
	WORKDIR="$(WORKDIR)" ./scripts/fetch-dem.sh --region="$(REGION)" --session="$(SESSION)" --source="$(DEM_SOURCE)" $(if $(DEM_INPUT),--input="$(DEM_INPUT)",)

build: python-doctor python-workspace-init
ifneq ($(filter $(ROLE),base building both),)
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build build execute-vector \
	  --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --workdir="$(WORKDIR)" \
	  --role="$(ROLE)" --glyph="$(GLYPH)" $(if $(INPUT),--input="$(INPUT)",) \
	  $(if $(filter 1,$(FORCE)),--force,) \
	  $(if $(filter 1,$(FORCE_BUILDING)),--force-building,)
else ifneq ($(filter $(ROLE),base_raster both_raster),)
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build build execute-vector \
	  --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --workdir="$(WORKDIR)" \
	  --role="$(if $(filter base_raster,$(ROLE)),base,both)" --glyph=1 \
	  $(if $(INPUT),--input="$(INPUT)",) $(if $(filter 1,$(FORCE)),--force,) \
	  $(if $(filter 1,$(FORCE_BUILDING)),--force-building,)
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build build raster-bake \
	  $(BAKE_RENDERER_FLAGS) \
	  --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --workdir="$(WORKDIR)" \
	  $(if $(BAKE_BBOX),--bbox="$(BAKE_BBOX)",) \
	  $(if $(BAKE_MIN_ZOOM),--min-zoom="$(BAKE_MIN_ZOOM)",) \
	  $(if $(BAKE_MAX_ZOOM),--max-zoom="$(BAKE_MAX_ZOOM)",) \
	  $(if $(BAKE_MAX_TILES),--max-tiles="$(BAKE_MAX_TILES)",)
else ifeq ($(ROLE),raster_bake)
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build build raster-bake \
	  $(BAKE_RENDERER_FLAGS) \
	  --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --workdir="$(WORKDIR)" \
	  $(if $(BAKE_BBOX),--bbox="$(BAKE_BBOX)",) \
	  $(if $(BAKE_MIN_ZOOM),--min-zoom="$(BAKE_MIN_ZOOM)",) \
	  $(if $(BAKE_MAX_ZOOM),--max-zoom="$(BAKE_MAX_ZOOM)",) \
	  $(if $(BAKE_MAX_TILES),--max-tiles="$(BAKE_MAX_TILES)",)
else
	input="$(INPUT)"; \
	if [ -z "$$input" ]; then \
	  basename="$$(WORKDIR="$(WORKDIR)" REGION="$(REGION)" ./scripts/region-pbf-basename.sh "$(REGION)" 2>/dev/null || printf '%s-latest.osm.pbf\n' "$(REGION_BASENAME)")"; \
	  input="mirror/$$basename"; \
	fi; \
	WORKDIR="$(WORKDIR)" GLYPH="$(GLYPH)" FORCE_BUILDING="$(FORCE_BUILDING)" ./scripts/build.sh --input="$$input" --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --role="$(ROLE)" --glyph="$(GLYPH)" $(if $(filter 1,$(FORCE)),--force,) $(if $(filter 1,$(FORCE_BUILDING)),--force-building,)
endif

raster-estimate:
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build build raster-plan \
	  --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --workdir="$(WORKDIR)" \
	  $(if $(BAKE_BBOX),--bbox="$(BAKE_BBOX)",) \
	  $(if $(BAKE_MIN_ZOOM),--min-zoom="$(BAKE_MIN_ZOOM)",) \
	  $(if $(BAKE_MAX_ZOOM),--max-zoom="$(BAKE_MAX_ZOOM)",) \
	  $(if $(BAKE_MAX_TILES),--max-tiles="$(BAKE_MAX_TILES)",)

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
ifneq ($(filter $(ROLE),base building both),)
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build quality release --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --role="$(ROLE)" --workdir="$(WORKDIR)"
else
	WORKDIR="$(WORKDIR)" ./scripts/verify.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --role="$(ROLE)"
endif

verify-dem:
	WORKDIR="$(WORKDIR)" ./scripts/verify.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --role=dem --strict

pack:
ifneq ($(filter $(ROLE),base building both raster_bake base_raster both_raster),)
	PYTHONPATH=backend/src $(PYTHON) -m huavd_map_build artifact pack --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --role="$(ROLE)" --format="$(FORMAT)" --workdir="$(WORKDIR)"
else
	WORKDIR="$(WORKDIR)" ./scripts/pack.sh --region="$(REGION)" --yyyymmdd="$(YYYYMMDD)" --session="$(SESSION)" --role="$(ROLE)" --format="$(FORMAT)"
endif

pack-tar:
	$(MAKE) pack FORMAT=tar WORKDIR="$(WORKDIR)" REGION="$(REGION)" YYYYMMDD="$(YYYYMMDD)" SESSION="$(SESSION)" ROLE="$(ROLE)"

pack-zip:
	$(MAKE) pack FORMAT=zip WORKDIR="$(WORKDIR)" REGION="$(REGION)" YYYYMMDD="$(YYYYMMDD)" SESSION="$(SESSION)" ROLE="$(ROLE)"

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
