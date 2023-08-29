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
