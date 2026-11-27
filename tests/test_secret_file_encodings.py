# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_secret_file_encodings.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""A secret file saved by an editor of Windows with a byte order mark holds the same secret; a file in another encoding is refused, never guessed."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hydra_umc_dev_server.cli import _read_api_token
from hydra_umc_dev_server.scenario_ingest import _read_secret

SAMPLE = "sample-0123456789-abcdefghij-0123456789"


class SecretFileEncodingTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.bom = Path(folder.name, "bom.token")
        self.bom.write_bytes(b"\xef\xbb\xbf" + SAMPLE.encode("ascii") + b"\r\n")  # what Notepad calls "UTF-8 with BOM"
        self.utf16 = Path(folder.name, "utf16.token")
        self.utf16.write_bytes((SAMPLE + "\r\n").encode("utf-16"))  # what `>` of Windows PowerShell writes

    def test_an_ingest_secret_ignores_a_byte_order_mark(self) -> None:
        self.assertEqual(_read_secret(str(self.bom)), SAMPLE)

    def test_an_ingest_secret_does_not_use_another_encoding(self) -> None:
        self.assertEqual(_read_secret(str(self.utf16)), None)

    def test_the_api_token_ignores_a_byte_order_mark(self) -> None:
        self.assertEqual(_read_api_token(SimpleNamespace(token_file=str(self.bom))), SAMPLE)

    def test_the_api_token_refuses_another_encoding(self) -> None:
        with self.assertRaises(ValueError):
            _read_api_token(SimpleNamespace(token_file=str(self.utf16)))


if __name__ == "__main__":
    unittest.main()
