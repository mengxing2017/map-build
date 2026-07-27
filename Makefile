WORKDIR        ?= /tmp/huavd-map-build
REGION         ?= china/guangxi
YYYYMM         ?= $(shell date -u +%Y%m)
SESSION        ?= $(shell echo $(REGION) | tr '/' '-')-$(YYYYMM)
REGION_BASENAME ?= $(notdir $(REGION))
INPUT          ?=
ROLE           ?= both
FORMAT         ?= both
IMPORT_FORMAT  ?= zip
HUAVD_MAP_BUILD_MACHINE_HOME ?= /opt/huavd-map-build

.PHONY: init init-workdir install-config init-build-machine-workdir install-build-machine-config setup doctor fetch build verify pack pack-tar pack-zip prepare-import prepare-import-all clean all release release-tar release-zip

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

fetch: init-workdir
	WORKDIR="$(WORKDIR)" ./scripts/fetch.sh --region="$(REGION)"

build: init-workdir
	input="$(INPUT)"; \
	if [ -z "$$input" ]; then \
	  basename="$$(WORKDIR="$(WORKDIR)" REGION="$(REGION)" ./scripts/region-pbf-basename.sh "$(REGION)" 2>/dev/null || printf '%s-latest.osm.pbf\n' "$(REGION_BASENAME)")"; \
	  input="mirror/$$basename"; \
	fi; \
	WORKDIR="$(WORKDIR)" ./scripts/build.sh --input="$$input" --region="$(REGION)" --yyyymm="$(YYYYMM)" --role="$(ROLE)"

verify:
	WORKDIR="$(WORKDIR)" ./scripts/verify.sh --region="$(REGION)" --yyyymm="$(YYYYMM)" --session="$(SESSION)" --role="$(ROLE)"

pack:
	WORKDIR="$(WORKDIR)" ./scripts/pack.sh --region="$(REGION)" --yyyymm="$(YYYYMM)" --session="$(SESSION)" --role="$(ROLE)" --format="$(FORMAT)"

pack-tar:
	WORKDIR="$(WORKDIR)" ./scripts/pack.sh --region="$(REGION)" --yyyymm="$(YYYYMM)" --session="$(SESSION)" --role="$(ROLE)" --format=tar

pack-zip:
	WORKDIR="$(WORKDIR)" ./scripts/pack.sh --region="$(REGION)" --yyyymm="$(YYYYMM)" --session="$(SESSION)" --role="$(ROLE)" --format=zip

prepare-import:
	role="$(ROLE)"; \
	if [ "$$role" = "both" ]; then role="base"; fi; \
	WORKDIR="$(WORKDIR)" ./scripts/prepare-import.sh --region="$(REGION)" --yyyymm="$(YYYYMM)" --session="$(SESSION)" --role="$$role" --format="$(IMPORT_FORMAT)"

prepare-import-all:
	WORKDIR="$(WORKDIR)" ./scripts/prepare-import.sh --region="$(REGION)" --yyyymm="$(YYYYMM)" --session="$(SESSION)" --role=both --format="$(IMPORT_FORMAT)"

clean:
	rm -rf "$(WORKDIR)/staging/$(SESSION)" \
	  "$(WORKDIR)/cache/import/$(SESSION)" \
	  "$(WORKDIR)/cache/pack/$(SESSION)" \
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
	  "$(WORKDIR)/outputs/$(SESSION).building.attribution.json"

all: build pack

release: build pack verify

release-tar: build pack-tar verify

release-zip: build pack-zip verify
