0.22.2
======

* Remove RPATH from shared libraries that do not link to any other libraries in
  our environment.
* Ensure we always return a proper and consistang default python version for
  create, fetch, build commands.


0.22.1
======

* Fix RELENV_DATA environment variable regression (commit 19c7050)
* Fix 3.13 sysconfig (commit 209ad7e)
* Update Python versions: 3.13.11, 3.13.10, 3.13.9, 3.9.25 (commit dc8a37f)
* Update dependencies: sqlite 3.51.1.0, libxcrypt 4.5.2 (commit dc8a37f)
* Fix failing unit tests (commit 0e36899)


0.22.0
======

* Minor Version Support for relenv create (commit 3582abc)
* Dependency Version Management (commit 7965c3b)
* Full mypy --strict Compliance (commits 6f78084, d6f2edb, f95c43c, c3934e4, 592b9de)
* Build UI Improvements (commit 567ce62)
* Updated expat for all Python versions (commit 7620fec)
* Ensure python-versions.json is shipped in whl file


0.21.2
======

* We refresh the ensurepip bundle during every build so new runtimes ship with pip 25.2 and setuptools 80.9.0.
* Windows builds now pull newer SQLite (3.50.4.0) and XZ (5.6.2) sources, copy in a missing XZ config file, and tweak SBOM metadata; the libexpat update is prepared but only runs on older maintenance releases.
* Our downloader helpers log more clearly, know about more archive formats, and retry cleanly on transient errors.
* pip’s changing install API is handled by runtime wrappers that adapt to all of the current signatures.
* Linux verification tests install pip 25.2/25.3 before building setuptools to make sure that flow keeps working.


0.21.1
======

* Fix issue determinion micro version from minor


0.21.0
======

* Update to recent python versions: 3.12.12, 3.11.14, 3.10.19 and 3.9.24.


0.20.10
=======

* Fix github release pipeline.


0.20.9
======

* Fix github release pipeline.


0.20.8
======

* Fix github release pipeline.


0.20.7
======

* Update LZMA to 5.8.2 (#240)
* Update ncurses to 6.5 (#242)
* Update openssl to 3.5.4 (#245)
* Fix shebang creating to work with pip >=25.2 (#247)
* Fix python source hash checking (#249)


0.20.6
======

* Revert relenv's cargo home from temp directory back to relenv's data
  directory.
* Update Openssl FIPS module to 3.1.2


0.20.5
======

* Update gdbm from 1.25 to 1.26
* Update libffi from 3.5.1 to 3.5.2
* Update readline from 8.2.13 to 8.3
* Update sqlite from 3.50.2 to 3.50.4


0.20.4
======

* Fix relenv fetch default version
* Remove repo.saltproject.io from fetch locations


0.20.3
======

* Ensure relenv data directory always exists


0.20.2
======

* Extract ppbt toolchain to relenv data directory so it can be re-used accross
  environments.


0.20.1
======

* Fix rogue print statment.


0.20.0
======

* Use ppbt python package for toolchain. The relenv toolchain command has been
  deprecated. Please pip install relenv[toolchain] instead.
* Ensure we do not link to /usr/local when building macos builds
* Verify pip installations do not link to /usr/local on macos


0.19.4
======

* Upgrade sqlite to address CVE-2025-29087
* Update sqlite to 3500200
* Update libffi to 3.5.1
* Update python 3.13 to 3.13.5


0.19.3
======

* Upgrade sqlite to address CVE-2025-29087
* Fix editable pip (pip -e) installation


0.19.2
======

* Remove static libraries from lib directory


0.19.1
======

* Remove ppbt from install requirements.


0.19.0
======

* Update python 3.10 to 3.10.17:
  https://www.python.org/downloads/release/python-31017/
* Update python 3.13 to 3.13.3
* Update libxcrypt to 4.4.38
* Update libffi to 3.4.8
* Update gdbm to 1.25
* Include libstdc++ in relenv lib
* Update environment with buildenv when RELENV_BUILDENV environment is set.
* Include libstdc++ in relenv's lib directory instead of passing
  -static-libstdc++
* Clean up duplicate options in sysconfig data.
* Work with setuptools >= 72.2.0
* Default to positition indipendent code gen
* Add --download-only option to build


0.18.2
======

* Invalid release should have been 0.19.0


0.18.1
======

* Update openssl to 3.2.4
* Update libffi to 3.4.7
* Update python 3.10 to 3.10.16
* Update python 3.11 to 3.11.11
* Update python 3.12 to 3.12.19
* Update python 3.13 to 3.13.2
* Fix zlib download mirrors for toolchain builds
* Fix missing `_toolchain` and `_scripts` directory


0.18.0
======

* Relenv no longer relies on legacy infurstrucutre for ci/cd
* Relenv python builds are no stored and downloaded from github rather than
  legacy infurstructure


0.17.4
======

* Add python 3.13.0
* Update python 3.12 to 3.13.7


0.17.3
======

* Upgrade python versions: 3.10.15, 3.11.10, 3.12.5


0.17.2
======

* Fix github release publishing in workflows


0.17.1
======

* Upgrade openssl to 3.2.3
* Add enable md2 flag to openssl compilation
* Fix pip install --target with pip version 24.2


0.17.0
======

* Upgrade python 3.11 to 3.11.9
* Upgrade python 3.12 to 3.12.4
* Upgrade openssl to 3.2.2
* Upgrade XZ to 5.6.2
* Upgrade SQLite to 3460000
* Use sha1 for download checksums intead of md5


0.16.1
======

* Fix pip build requirements install when used with --target
* Fix docs builds


0.16.0
======

* Upgrade Python 3.10 to 3.10.14
* Upgrade Python 3.11 to 3.11.8
* Upgrade dependencies: openssl, sqlite, libffi and  zlib.
* Add python 3.12.2
* Add `--no-pretty` option to build command to allow build output to stdout.
* Add '--log-level' option to build command.
* Minor test improvements.


0.15.1
======

* Fix debugpy support.


0.15.0
======

* Upgrade openssl to 3.1.5
* Upgrade python 3.11 to 3.11.7
* Fix pip installation of namespaced packages when using --target
* Fix path sanitization when relenv is in symlinked directory


0.14.2
======

* Fix pipeline to upload arm builsds for macos.


0.14.1
======

* Fix packaging version wart.


0.14.0
======

* Update python 3.11 to 3.11.6
* Update openssl to address CVE-2023-5363.
* Update sqlite
* Fix bug in openssl setup when openssl binary can't be found.
* Add programatic access to buildenv
* Fix buildenv's path to toolchain's sysroot
* Add M1 mac support.


0.13.12
=======

* Update openssl (CVE-2023-4807) and sqlite to newest versions.


0.13.11
=======

* Add regression test for system fips module usage
* Fix fips module usage on photon os.


0.13.10
=======

* Add a build-id for downstream rpm packaging


0.13.9
======

* Revert with-dbg flag on python builds.


0.13.8
======

* Fix wart in python-config's shebang cuasing syntax error.


0.13.7
======

* Load relenv's openssl legacy provider before setting modules dir to system
  location for the system's fips provider.


0.13.6
======

* Do not set openssl modules directory on windows since were still on 1.1.x
* Fix load module deprecations warnings
* Ignore load module imporet warnings for now


0.13.5
======

* Bump to Python 3.10.13 and 3.11.5 due to CVE-2023-40217 and CVE-2023-41105
* Include debug symbols to enable gdb debugging
* Set openssl module locations via c api rather than environment variable
* Default to the system's openssl modules directory
* Bump dependency versions


0.13.4
======

* Fix pip installing multiple packages with scripts to a target directory
* Finish bootstrap before importing hashlib so our openssl modules will be found.


0.13.3
======

* Upgrade openssl to 3.1.2


0.13.2
======

* Always use relenv's openssl modules directory


0.13.1
======

* Determine openssl modules directory at runtime


0.13.0
======

* Tests and fixes for installing m2crypto
* Fix pipelines to upload to repo.saltstack.io
* Ship with openssl 3.1.1 on linux and darwin for FIPS compatability
* Update openssl and python minior version to address CVEs


0.12.3
======

* Preserve ignore installed option when using pip with a target.


0.12.2
======

* Fix path comparison bug on win32


0.12.1
======

* Be more robust when getting system python config


0.12.0
======

* Add support building on M1 mac
* Fix wart in relenv create's help message
* Look in path for system python
* Provide sane defaults for pip when no system python is found
* Fix shebangs when using pip --target to install packages
* Fix uninstalling packages installed with pip --target


0.11.2
======

* Fetch files from repo.saltproject.io first.


0.11.1
======

* Import all relenv modules using a reletive path when relenv.runtime is
  imported.


0.11.0
======

* Use a pth file instead of sitecustomize for relenv runtime
* Fix errors in documentation
* Default to using system libraries, act more like virtualenv
* Source relenv buildenv instead of eval
* Upgrade XZ and SQLite
* Upgrade minor python versions (3.10.11 and 3.11.3)


0.10.1
======

* Fix bug in runtime.bootstrap on linux when no toolchain exists


0.10.0
======

* Add buildenv to support building of additional libraries
* Add check to support installation of additional libraries
* Add examples of building libgit2, open-ldap and libcurl


0.9.0
=====

* Add support for rust c extensions
* Add sys.RELENV attribute to runtime bootstrap
* Fix ImportWarning thrown by RelenvImporter
* Refactor RelenvImporter


0.8.2
=====

* Fix SHEBANG when installing scripts to root


0.8.1
=====

* Fix bug in crypt module's rpath


0.8.0
=====

* Better fix for rpaths of pip installed C extensions
* Fetch current version not 'latest'
* Add libxcrypt to linux builds
* Shellcheck script shebangs


0.7.0
=====

* Update to python 3.10.10
* Remove C-python test suite from build
* Fix rpath on pip installed C moudles


0.6.0
=====

* Add python 3.11.2
* Upgrade linux python depenencies
* Add version check script


0.5.0
=====

* Add '--version' option to cli
* Support symlinks on OSes without coreutils installed


0.4.10
======

* Update windows python to 3.10.x


0.4.9
=====

* Make shebangs in Python's modules relative.


0.4.8
=====

* Statically link aarch64 toolchains for portability


0.4.7
=====

* Wrap build_ext finalize_options method to add relenv include directory
* Add tests that installs m2crypto on linux


0.4.6
=====

* Script shebangs now work when symlinked


0.4.5
=====

* Build newest python release
* Do not define SSL_CERT_FILE when file does not exit
* Only define ssl environment variables if not already set


0.4.4
=====

* Fix scripts relative to launcher_dir on windows using RELENV_PIP_DIR
* Add flake8 for linting


0.4.3
=====

* Fix arch flag when fetching builds
* Cleanup changelog syntax
* Add test for virtual environments based on relenv environments


0.4.2
=====

* General code clean up based on pylint results
* Fix virtualenvs created from relenvs
* The fetch and toolchain always show download urls and destinations
* Fix oldest supported Mac OS version (10.5)
* Docs improvements


0.4.1
=====

* Work around issue on Mac where Python is linking to /usr/local
  [Issue #46](https://github.com/saltstack/relative-environment-for-python/issues/46)


0.4.0
=====

* Fix issue where relenv runtime was being imported from user site packages
* Added test to install salt with USE_STATIC_PACAKGES environment set
* Switch CI/CD to use saltstack hosted runners
* General code cleanup


0.3.0
=====

* The toolchain command defaults to the build box architecture
* Build macos on catalinia for now


0.2.1
=====

* Fix 'RELENV_PIP_DIR' environment variable on python <= 3.10 (Windows)


0.2.0
=====

* Skip downloads that exist and are valid.
* Inlude changelog in documentation.
* Better help when no sub-command given.
* Add some debuging or relocate module.


0.1.0
=====

* Multiple fixes for cross compilation support.


0.0.3
=====

* Build pipeline improvements.


0.0.2
=====

* Fetch defaults to the latest version of pre-built Python build.
* Build and test pipeline improvements
* Add package description


0.0.1
=====

* Initial release of Relenv. Build relocatable python builds for Linux, Macos and Windows.
