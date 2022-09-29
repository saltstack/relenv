#!/usr/bin/env python3

from setuptools import setup

if __name__ == "__main__":
    setup(
        package_data={
            # XXX make this a separate package
            #'mayflower': ['_build/*.tar.xz', '_toolchain/*tar.xz']
        },
        include_package_data=True,
    )
