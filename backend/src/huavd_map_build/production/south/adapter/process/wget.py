from __future__ import annotations

import os
import subprocess

from huavd_map_build.production.domain.fetch import FetchToolError


class WgetDownloader:
    def download(self, url: str, destination: str, limit_rate: str | None) -> None:
        arguments = ["wget", "--timestamping"]
        if limit_rate is not None:
            arguments.append(f"--limit-rate={limit_rate}")
        arguments.extend(["-P", destination, url])
        allowed = ("HOME", "LANG", "LC_ALL", "PATH", "SSL_CERT_FILE", "SSL_CERT_DIR")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        try:
            result = subprocess.run(
                arguments,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as error:
            raise FetchToolError(f"failed to start wget: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()
            message = detail[-1] if detail else f"exit {result.returncode}"
            raise FetchToolError(f"wget failed for {url}: {message}")
