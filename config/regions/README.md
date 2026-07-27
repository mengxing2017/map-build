# Region Polygon Files

This directory is reserved for Geofabrik `.poly` files used when a configured
sub-region has no direct `.osm.pbf` extract and must be derived from its parent
PBF with `osmium extract --strategy=smart`.

Naming must match `config/regions.yaml` fallback paths:

```text
config/regions/china-guangxi.poly
config/regions/china-guangdong.poly
config/regions/china-yunnan.poly
```

Use polygon files from Geofabrik region pages when available. If a direct
Geofabrik polygon is not available, generate one from an approved administrative
boundary source and record the source in the build manifest or changelog. Polygon
extracts are preferred over bbox extracts; bbox is only acceptable for PoC runs.

The build scripts do not download `.poly` files automatically. Place reviewed
files here before running an extract workflow.
