# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
Download utility class for fetching build dependencies.
"""
from __future__ import annotations

import hashlib
import logging
import os
import pathlib
import subprocess
import sys
from typing import Callable, Optional, Tuple, Union

from relenv.common import (
    RelenvException,
    ConfigurationError,
    ChecksumValidationError,
    download_url,
    get_download_location,
    runcmd,
)

# Type alias for path-like objects
PathLike = Union[str, os.PathLike[str]]

# Environment flag for CI/CD detection
CICD = "CI" in os.environ

log = logging.getLogger(__name__)


def verify_checksum(file: PathLike, checksum: Optional[str]) -> bool:
    """
    Verify the checksum of a file.

    Supports both SHA-1 (40 hex chars) and SHA-256 (64 hex chars) checksums.
    The hash algorithm is auto-detected based on checksum length.

    :param file: The path to the file to check.
    :type file: str
    :param checksum: The checksum to verify against (SHA-1 or SHA-256)
    :type checksum: str

    :raises RelenvException: If the checksum verification failed

    :return: True if it succeeded, or False if the checksum was None
    :rtype: bool
    """
    if checksum is None:
        log.error("Can't verify checksum because none was given")
        return False

    # Auto-detect hash type based on length
    # SHA-1: 40 hex chars, SHA-256: 64 hex chars
    if len(checksum) == 64:
        hash_algo = hashlib.sha256()
        hash_name = "sha256"
    elif len(checksum) == 40:
        hash_algo = hashlib.sha1()
        hash_name = "sha1"
    else:
        raise ChecksumValidationError(
            f"Invalid checksum length {len(checksum)}. Expected 40 (SHA-1) or 64 (SHA-256)"
        )

    with open(file, "rb") as fp:
        hash_algo.update(fp.read())
        file_checksum = hash_algo.hexdigest()
        if checksum != file_checksum:
            raise ChecksumValidationError(
                f"{hash_name} checksum verification failed. expected={checksum} found={file_checksum}"
            )
    return True


class Download:
    """
    A utility that holds information about content to be downloaded.

    :param name: The name of the download
    :type name: str
    :param url: The url of the download
    :type url: str
    :param signature: The signature of the download, defaults to None
    :type signature: str
    :param destination: The path to download the file to
    :type destination: str
    :param version: The version of the content to download
    :type version: str
    :param sha1: The sha1 sum of the download
    :type sha1: str

    """

    def __init__(
        self,
        name: str,
        url: str,
        fallback_url: Optional[str] = None,
        signature: Optional[str] = None,
        destination: PathLike = "",
        version: str = "",
        checksum: Optional[str] = None,
    ) -> None:
        self.name = name
        self.url_tpl = url
        self.fallback_url_tpl = fallback_url
        self.signature_tpl = signature
        self._destination: pathlib.Path = pathlib.Path()
        if destination:
            self._destination = pathlib.Path(destination)
        self.version = version
        self.checksum = checksum

    def copy(self) -> "Download":
        """Create a copy of this Download instance."""
        return Download(
            self.name,
            self.url_tpl,
            self.fallback_url_tpl,
            self.signature_tpl,
            self.destination,
            self.version,
            self.checksum,
        )

    @property
    def destination(self) -> pathlib.Path:
        """Get the destination directory path."""
        return self._destination

    @destination.setter
    def destination(self, value: Optional[PathLike]) -> None:
        """Set the destination directory path."""
        if value:
            self._destination = pathlib.Path(value)
        else:
            self._destination = pathlib.Path()

    @property
    def url(self) -> str:
        """Get the formatted download URL."""
        return self.url_tpl.format(version=self.version)

    @property
    def fallback_url(self) -> Optional[str]:
        """Get the formatted fallback URL if configured."""
        if self.fallback_url_tpl:
            return self.fallback_url_tpl.format(version=self.version)
        return None

    @property
    def signature_url(self) -> str:
        """Get the formatted signature URL."""
        if self.signature_tpl is None:
            raise ConfigurationError("Signature template not configured")
        return self.signature_tpl.format(version=self.version)

    @property
    def filepath(self) -> pathlib.Path:
        """Get the full file path where the download will be saved."""
        _, name = self.url.rsplit("/", 1)
        return self.destination / name

    @property
    def formatted_url(self) -> str:
        """Get the formatted URL (alias for url property)."""
        return self.url_tpl.format(version=self.version)

    def fetch_file(
        self, progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[str, bool]:
        """
        Download the file.

        :param progress_callback: Optional callback(downloaded_bytes, total_bytes)
        :type progress_callback: Optional[Callable[[int, int], None]]
        :return: The path to the downloaded content, and whether it was downloaded.
        :rtype: tuple(str, bool)
        """
        try:
            return (
                download_url(
                    self.url,
                    self.destination,
                    CICD,
                    progress_callback=progress_callback,
                ),
                True,
            )
        except Exception as exc:
            fallback = self.fallback_url
            if fallback:
                print(f"Download failed {self.url} ({exc}); trying fallback url")
                return (
                    download_url(
                        fallback,
                        self.destination,
                        CICD,
                        progress_callback=progress_callback,
                    ),
                    True,
                )
            raise

    def fetch_signature(self, version: Optional[str] = None) -> Tuple[str, bool]:
        """
        Download the file signature.

        :return: The path to the downloaded signature.
        :rtype: str
        """
        return download_url(self.signature_url, self.destination, CICD), True

    def exists(self) -> bool:
        """
        True when the artifact already exists on disk.

        :return: True when the artifact already exists on disk
        :rtype: bool
        """
        return self.filepath.exists()

    def valid_hash(self) -> None:
        """Validate the hash of the downloaded file (placeholder method)."""
        pass

    @staticmethod
    def validate_signature(archive: PathLike, signature: Optional[PathLike]) -> bool:
        """
        True when the archive's signature is valid.

        :param archive: The path to the archive to validate
        :type archive: str
        :param signature: The path to the signature to validate against
        :type signature: str

        :return: True if it validated properly, else False
        :rtype: bool
        """
        if signature is None:
            log.error("Can't check signature because none was given")
            return False
        try:
            runcmd(
                ["gpg", "--verify", signature, archive],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
            return True
        except RelenvException as exc:
            log.error("Signature validation failed on %s: %s", archive, exc)
            return False

    @staticmethod
    def validate_checksum(archive: PathLike, checksum: Optional[str]) -> bool:
        """
        True when when the archive matches the sha1 hash.

        :param archive: The path to the archive to validate
        :type archive: str
        :param checksum: The sha1 sum to validate against
        :type checksum: str
        :return: True if the sums matched, else False
        :rtype: bool
        """
        try:
            verify_checksum(archive, checksum)
            return True
        except RelenvException as exc:
            log.error("sha1 validation failed on %s: %s", archive, exc)
            return False

    def __call__(
        self,
        force_download: bool = False,
        show_ui: bool = False,
        exit_on_failure: bool = False,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """
        Downloads the url and validates the signature and sha1 sum.

        :param progress_callback: Optional callback(downloaded_bytes, total_bytes)
        :type progress_callback: Optional[Callable[[int, int], None]]
        :return: Whether or not validation succeeded
        :rtype: bool
        """
        os.makedirs(self.filepath.parent, exist_ok=True)

        downloaded = False
        if force_download:
            _, downloaded = self.fetch_file(progress_callback)
        else:
            file_is_valid = False
            dest = get_download_location(self.url, self.destination)
            if self.checksum and os.path.exists(dest):
                file_is_valid = self.validate_checksum(dest, self.checksum)
            if file_is_valid:
                log.debug("%s already downloaded, skipping.", self.url)
            else:
                _, downloaded = self.fetch_file(progress_callback)
        valid = True
        if downloaded:
            if self.signature_tpl is not None:
                sig, _ = self.fetch_signature()
                valid_sig = self.validate_signature(self.filepath, sig)
                valid = valid and valid_sig
            if self.checksum is not None:
                valid_checksum = self.validate_checksum(self.filepath, self.checksum)
                valid = valid and valid_checksum

            if not valid:
                log.warning("Checksum did not match %s: %s", self.name, self.checksum)
                if show_ui:
                    sys.stderr.write(
                        f"\nChecksum did not match {self.name}: {self.checksum}\n"
                    )
                    sys.stderr.flush()
        if exit_on_failure and not valid:
            sys.exit(1)
        return valid
