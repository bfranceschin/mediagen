"""Shared test fixtures for mediagen tests."""

import os
import sys
from pathlib import Path

import pytest

# Add scripts/ to path so we can import mediagen as a module
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace directory mimicking ~/.hermes/workspace/mediagen/."""
    ws = tmp_path / "mediagen"
    ws.mkdir()
    (ws / "images" / "raw").mkdir(parents=True)
    (ws / "external").mkdir(parents=True)
    (ws / "logs").mkdir(parents=True)
    return ws


@pytest.fixture
def sample_image(tmp_path):
    """Create a minimal valid PNG file for testing edit mode."""
    import struct, zlib
    def make_png():
        header = b'\x89PNG\r\n\x1a\n'
        # IHDR
        ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)  # 1x1, 8bit RGB
        ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
        ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
        # IDAT
        raw = zlib.compress(b'\x00\xff\xff\xff')  # filter byte + 1 white pixel
        idat_crc = zlib.crc32(b'IDAT' + raw) & 0xffffffff
        idat = struct.pack('>I', len(raw)) + b'IDAT' + raw + struct.pack('>I', idat_crc)
        # IEND
        iend_crc = zlib.crc32(b'IEND') & 0xffffffff
        iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
        return header + ihdr + idat + iend

    img_path = tmp_path / "test_input.png"
    img_path.write_bytes(make_png())
    return img_path
