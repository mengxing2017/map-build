# HUAVD Map Build Backend

This directory contains the Python implementation of the map build pipeline.
It follows bounded contexts and ports/adapters. The Makefile uses Python for
single-region vector builds and raster roles; remaining overview, derived-map,
DEM, packaging, and compatibility paths may still delegate to shell scripts.

Run the first migration slice without installing the package:

```bash
PYTHONPATH=backend/src python3 -m huavd_map_build catalog validate
PYTHONPATH=backend/src python3 -m huavd_map_build build plan \
  --region china/guangxi --yyyymmdd 20260818 --role both
PYTHONPATH=backend/src python3 -m huavd_map_build build raster-bake \
  --region china/guangxi --yyyymmdd 20260818 \
  --workdir /tmp/huavd-map-build --no-publish
PYTHONPATH=backend/src python3 -m unittest discover -s backend/tests -v
```
