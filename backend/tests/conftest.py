"""Opt-in typed Codex policy fixture; production clients remain failclosed."""
from pathlib import Path
import sys

# Trusted fixed repository scripts layout: repo/scripts on host, /scripts in API image.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from boundary_test_support import codex_host_policy, configured_codex_transport
