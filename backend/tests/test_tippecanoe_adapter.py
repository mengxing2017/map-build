import subprocess
import unittest
from unittest.mock import patch

from huavd_map_build.production.south.adapter.process.tippecanoe import (
    ProcessTippecanoeRunner,
)


class ProcessTippecanoeRunnerTest(unittest.TestCase):
    @patch("huavd_map_build.production.south.adapter.process.tippecanoe.subprocess.run")
    @patch("huavd_map_build.production.south.adapter.process.tippecanoe.shutil.which")
    def test_executes_argument_vector_without_shell(self, which, run) -> None:
        which.return_value = "/tools/tippecanoe"
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        ProcessTippecanoeRunner().run(("-Z0", "-L", "road:/tmp/road.geojsonseq"))
        self.assertEqual(
            ["/tools/tippecanoe", "-Z0", "-L", "road:/tmp/road.geojsonseq"],
            run.call_args.args[0],
        )
        self.assertNotIn("shell", run.call_args.kwargs)
