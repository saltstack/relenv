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
