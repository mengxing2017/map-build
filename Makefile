WORKDIR        ?= /tmp/huavd-map-build
REGION         ?= china/guangxi
YYYYMM         ?= $(shell date -u +%Y%m)
SESSION        ?= $(shell echo $(REGION) | tr '/' '-')-$(YYYYMM)
REGION_BASENAME ?= $(notdir $(REGION))
INPUT          ?= mirror/$(REGION_BASENAME)-latest.osm.pbf
ROLE           ?= both
FORMAT         ?= both
HUAVD_MAP_BUILD_MACHINE_HOME ?= /opt/huavd-map-build

.PHONY: init init-workdir install-config init-build-machine-workdir install-build-machine-config setup doctor fetch build verify pack pack-tar pack-zip clean all release release-tar release-zip

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
	WORKDIR="$(WORKDIR)" ./scripts/build.sh --input="$(INPUT)" --region="$(REGION)" --yyyymm="$(YYYYMM)" --role="$(ROLE)"

verify:
	WORKDIR="$(WORKDIR)" ./scripts/verify.sh --region="$(REGION)" --yyyymm="$(YYYYMM)" --session="$(SESSION)" --role="$(ROLE)"

pack:
	WORKDIR="$(WORKDIR)" ./scripts/pack.sh --session="$(SESSION)" --role="$(ROLE)" --format="$(FORMAT)"

pack-tar:
	WORKDIR="$(WORKDIR)" ./scripts/pack.sh --session="$(SESSION)" --role="$(ROLE)" --format=tar

pack-zip:
	WORKDIR="$(WORKDIR)" ./scripts/pack.sh --session="$(SESSION)" --role="$(ROLE)" --format=zip

clean:
	rm -rf "$(WORKDIR)/staging/$(SESSION)" \
	  "$(WORKDIR)/cache/pack/$(SESSION)" \
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
