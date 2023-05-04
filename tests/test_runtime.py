# Copyright 2023 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
#
import logging
import os
import sys
from unittest.mock import patch

import relenv.runtime

log = logging.getLogger(__name__)


def test_wrap_sitecustomize():
    python_path_entries = ["/blah/blah", "/yada/yada"]
    expected = ["/foo/1", "/bar/2"] + python_path_entries
    assert sorted(sys.path) != expected
    with patch.object(sys, "prefix", "/foo"), patch.object(
        sys, "base_prefix", "/bar"
    ), patch.object(sys, "path", ["/foo/1", "/bar/2", "/lib/3"]), patch.dict(
        os.environ, PYTHONPATH=os.pathsep.join(python_path_entries)
    ):
        assert sys.path != expected
        relenv.runtime.wrapsitecustomize(lambda: True)()
        assert sys.path == expected
    assert sys.path != expected
