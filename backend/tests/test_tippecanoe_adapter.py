import subprocess
import tempfile
import unittest
from pathlib import Path
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

    @patch("huavd_map_build.production.south.adapter.process.tippecanoe.shutil.which")
    @patch("huavd_map_build.production.south.adapter.process.tippecanoe.subprocess.run")
    def test_converts_tippecanoe_mbtiles_to_pmtiles_atomically(self, run, which) -> None:
        which.side_effect = ["/tools/tippecanoe", "/tools/pmtiles"]

        def execute(command, **_kwargs):
            output = next((item.removeprefix("--output=") for item in command
                           if item.startswith("--output=")), None)
            if output is not None:
                Path(output).write_bytes(b"mbtiles")
            elif command[1] == "convert":
                Path(command[3]).write_bytes(b"pmtiles")
            return subprocess.CompletedProcess(command, 0)

        run.side_effect = execute
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "map.pmtiles"
            ProcessTippecanoeRunner().run((f"--output={target}", "-Z0"))
            self.assertEqual(b"pmtiles", target.read_bytes())
        self.assertEqual("/tools/tippecanoe", run.call_args_list[0].args[0][0])
        self.assertEqual(
            ["/tools/pmtiles", "convert"], run.call_args_list[1].args[0][:2]
        )
