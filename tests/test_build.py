import sys

import pytest

from mayflower.build.common import Builder
from mayflower.common import MODULE_DIR


@pytest.mark.skipif(sys.platform != "linux", reason="Only valid on linux")
def test_builder_defaults_linux():
    builder = Builder()
    assert builder.arch == "x86_64"
    assert builder.triplet == "x86_64-linux-gnu"
    assert builder.prefix == MODULE_DIR / "_build" / "x86_64-linux-gnu"
    assert builder.sources == MODULE_DIR / "_src"
    assert builder.downloads == MODULE_DIR / "_download"
    assert builder.toolchains == MODULE_DIR / "_toolchain"
    assert builder.toolchain == MODULE_DIR / "_toolchain" / "x86_64-linux-gnu"
    assert callable(builder.build_default)
    assert callable(builder.populate_env)
    assert builder.no_download == False
    assert builder.recipies == {}
