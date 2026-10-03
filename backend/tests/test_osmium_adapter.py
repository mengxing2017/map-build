import subprocess
import unittest
from unittest.mock import patch

from huavd_map_build.production.south.adapter.process.osmium import (
    OsmiumTagsFilterRunner,
)


class OsmiumTagsFilterRunnerTest(unittest.TestCase):
    @patch("huavd_map_build.production.south.adapter.process.osmium.subprocess.run")
    @patch("huavd_map_build.production.south.adapter.process.osmium.shutil.which")
    def test_passes_filters_as_individual_arguments(self, which, run) -> None:
        which.return_value = "/tools/osmium"
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        OsmiumTagsFilterRunner().filter(
            "/input/source.osm.pbf",
            "/output/road.osm.pbf",
            ("w/highway", "r/type=route"),
        )
        arguments = run.call_args.args[0]
        self.assertEqual(
            [
                "/tools/osmium", "tags-filter", "-O", "-o",
                "/output/road.osm.pbf", "/input/source.osm.pbf",
                "w/highway", "r/type=route",
            ],
            arguments,
        )
        self.assertNotIn("shell", run.call_args.kwargs)
