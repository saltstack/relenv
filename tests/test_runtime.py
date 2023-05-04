# Copyright 2023 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
#
import logging
import sys
from unittest.mock import patch

import relenv.runtime

log = logging.getLogger(__name__)


def test_wrap_sitecustomize():
    expected = sorted(["/foo/1", "/bar/2"])
    assert sorted(sys.path) != expected
    with patch.object(sys, "prefix", "/foo"), patch.object(
        sys, "base_prefix", "/bar"
    ), patch.object(sys, "path", ["/foo/1", "/bar/2", "/lib/3"]):
        assert sorted(sys.path) != expected
        relenv.runtime.wrapsitecustomize(lambda: True)()
        assert sorted(sys.path) == expected
    assert sorted(sys.path) != expected
