from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile


@contextmanager
def local_extract_repository(root):
    """Keep synthetic local-extract/z19 configuration out of the public catalog."""
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        shutil.copytree(root / "config", target / "config")
        for name in ("scripts", "backend", ".venv", ".devbox"):
            (target / name).symlink_to(root / name, target_is_directory=True)
        regions = target / "config/regions.yaml"
        regions.write_text(regions.read_text() + REGION, encoding="utf-8")
        tiles = target / "config/tippecanoe.yaml"
        tiles.write_text(tiles.read_text().replace("high_density:\n", "high_density:\n" + OVERRIDE), encoding="utf-8")
        bake = target / "config/bake.yaml"
        bake.write_text(bake.read_text().replace("high_density:\n", "high_density:\n" + BAKE_OVERRIDE), encoding="utf-8")
        yield target


REGION = '\n  - id: "china/guangxi/test-extract"\n    slug: "china-guangxi-test-extract"\n    display_name: "Test Extract"\n    display_name_zh: "测试区域"\n    priority: "local-extract"\n    direct_tippecanoe: true\n    geofabrik:\n      pbf_url: null\n      md5_url: null\n      basename: "test-local.osm.pbf"\n      parent_region: "china/guangxi"\n    huavd:\n      region_id: "cn-450305-base"\n      source_id: "osm-china-guangxi-test-extract"\n      mapping_status: "defined"\n      asset_role: "base-vector"\n      source_type: "osm-pbf"\n      style_id: "osm-dev"\n      package_version_template: "{yyyymmdd}.{role}-z19"\n'
OVERRIDE = '  - region_match: "china/guangxi/test-extract"\n    roles: [base]\n    max_zoom: 19\n    layer_zoom_profile: "standard-z19"\n    extend_zooms_if_still_dropping: false\n'

BAKE_OVERRIDE = '  - region_match: "china/guangxi/test-extract"\n    max_zoom: 19\n    native_parallel_jobs: 2\n    max_tiles: 40000\n'
