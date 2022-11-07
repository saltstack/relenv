# Copyright 2022 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
#
from unittest.mock import call, patch

import pytest

import relenv.common as common
import relenv.toolchain as toolchain


def test_fetch(tmp_path):
    archdir = tmp_path / "archdir"
    archive = str(tmp_path / "archive")
    with patch.object(toolchain, "get_triplet", return_value="a-fake-triplet"):
        with patch.object(toolchain, "get_toolchain", return_value=archdir):
            with patch.object(
                toolchain, "download_url", return_value=archive
            ) as dl_mock:
                with patch.object(toolchain, "extract_archive") as extract_mock:
                    toolchain.fetch("fake_arch", "fake_toolchain")
                    dl_mock.assert_called_once()
                    extract_mock.assert_called_with("fake_toolchain", archive)


def test_fetch_directory_exists(tmp_path):
    with patch.object(toolchain, "get_triplet", return_value="a-fake-triplet"):
        with patch.object(toolchain, "get_toolchain", return_value=tmp_path):
            with patch.object(toolchain, "download_url") as dl_mock:
                toolchain.fetch("fake_arch", "fake_toolchain")
                dl_mock.assert_not_called()


def test__configure_ctng(tmp_path):
    ctngdir = tmp_path / "ctngdir"
    ctngdir.mkdir()
    data_dir = tmp_path / "data"
    root_dir = tmp_path / "root_dir"
    with patch("relenv.common.DATA_DIR", data_dir):
        with patch.object(toolchain, "runcmd") as cmd_mock:
            dirs = common.WorkDirs(root=root_dir)
            toolchain._configure_ctng(ctngdir, dirs)
            calls = [call(["./configure", "--enable-local"]), call(["make"])]
            cmd_mock.assert_has_calls(calls)


def test_build(tmp_path):
    ctngdir = tmp_path / "ctngdir"
    ctngdir.mkdir()
    ctng = ctngdir / "ct-ng"
    data_dir = tmp_path / "data"
    root_dir = tmp_path / "root_dir"
    machine = "fake_machine"
    arch = "fake_arch"
    triplet = "a-fake-triplet"
    with patch("relenv.common.DATA_DIR", data_dir):
        with patch.object(toolchain, "get_triplet", return_value=triplet):
            with patch.object(toolchain, "runcmd") as cmd_mock:
                dirs = common.WorkDirs(root=root_dir)
                tc_config_dir = dirs.toolchain_config / machine
                tc_config_dir.mkdir(parents=True)
                (tc_config_dir / "{}-ct-ng.config".format(triplet)).write_text(
                    "some text"
                )
                dirs.toolchain.mkdir(parents=True)
                toolchain.build(arch, dirs, machine, ctngdir)
                assert (dirs.toolchain / ".config").read_text() == "some text"
                assert cmd_mock.call_count == 2
                assert cmd_mock.call_args_list[0].args[0] == [str(ctng), "source"]
                assert cmd_mock.call_args_list[1].args[0] == [str(ctng), "build"]


def test_build_directory_exists(tmp_path):
    ctngdir = tmp_path / "ctngdir"
    ctngdir.mkdir()
    data_dir = tmp_path / "data"
    root_dir = tmp_path / "root_dir"
    machine = "fake_machine"
    arch = "fake_arch"
    triplet = "a-fake-triplet"
    with patch("relenv.common.DATA_DIR", data_dir):
        with patch.object(toolchain, "get_triplet", return_value=triplet):
            with patch.object(toolchain, "runcmd") as cmd_mock:
                dirs = common.WorkDirs(root=root_dir)
                (dirs.toolchain / triplet).mkdir(parents=True)
                toolchain.build(arch, dirs, machine, ctngdir)
                cmd_mock.assert_not_called()


def test_build_config_doesnt_exist(tmp_path):
    ctngdir = tmp_path / "ctngdir"
    ctngdir.mkdir()
    data_dir = tmp_path / "data"
    root_dir = tmp_path / "root_dir"
    machine = "fake_machine"
    arch = "fake_arch"
    triplet = "a-fake-triplet"
    with patch("relenv.common.DATA_DIR", data_dir):
        with patch.object(toolchain, "get_triplet", return_value=triplet):
            with patch.object(toolchain, "runcmd") as cmd_mock:
                dirs = common.WorkDirs(root=root_dir)
                dirs.toolchain.mkdir(parents=True)
                with pytest.raises(SystemExit):
                    toolchain.build(arch, dirs, machine, ctngdir)
                cmd_mock.assert_not_called()
