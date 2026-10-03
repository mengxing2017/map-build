import subprocess
import unittest
from unittest.mock import patch

from huavd_map_build.production.south.adapter.process.osmium_export import (
    OsmiumExportRunner,
)


class OsmiumExportRunnerTest(unittest.TestCase):
    @patch("huavd_map_build.production.south.adapter.process.osmium_export.subprocess.run")
    @patch("huavd_map_build.production.south.adapter.process.osmium_export.shutil.which")
    def test_keep_untagged_is_an_explicit_optional_argument(self, which, run) -> None:
        which.return_value = "/tools/osmium"
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        OsmiumExportRunner().export("input.pbf", "output.jsonseq", "config.json", True)
        arguments = run.call_args.args[0]
        self.assertEqual(
            [
                "/tools/osmium", "export", "--keep-untagged", "-c", "config.json",
                "-f", "geojsonseq", "-O", "-o", "output.jsonseq", "input.pbf",
            ],
            arguments,
        )
        self.assertNotIn("shell", run.call_args.kwargs)
