from .common import *
from .linux import build_openssl, build_xz, build_sqlite, build_python

build = Builder(populate_env=populate_env)

build.add(
    "OpenSSL",
    "https://www.openssl.org/source/openssl-1.1.1n.tar.gz",
    "2aad5635f9bb338bc2c6b7d19cbc9676",
    build_func=build_openssl,
)

build.add(
    "XZ",
    "http://tukaani.org/xz/xz-5.2.3.tar.gz",
    'ef68674fb47a8b8e741b34e429d86e9d',
)

build.add(
    name="SQLite",
    url="https://sqlite.org/2022/sqlite-autoconf-3370200.tar.gz",
    checksum='683cc5312ee74e71079c14d24b7a6d27',
    build_func=build_sqlite,
)

build.add(
    "Python",
    "https://www.python.org/ftp/python/3.10.6/Python-3.10.6.tar.xz",
    None,
    build_func=build_python,
    wait_on=[
        "OpenSSL",
        "XZ",
        "SQLite",
    ]
)


if __name__ == "__main__":
    run_build(build)
