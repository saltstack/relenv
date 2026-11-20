Runtime
=======

Overview
--------

A relenv distribution is a relocatable "onedir" — a self-contained CPython
tree that can be unpacked anywhere on disk and run from that location. The
stdlib bakes several absolute assumptions about the interpreter's layout at
build time (``sysconfig`` paths, OpenSSL module and certificate directories,
``distutils``/``pip`` install schemes, ``venv`` population), so a naive move
to a new location breaks pip installs, TLS verification, script shebangs,
Rust-backed extension builds, and child venvs. :mod:`relenv.runtime` runs at
interpreter startup and patches those assumptions in-process so the onedir
behaves correctly at its new location. This page documents how that startup
hook is wired up and what each step does.

Entry point: ``relenv.pth``
---------------------------

CPython's :mod:`site` module, which runs as part of interpreter
initialization, processes every ``.pth`` file it finds in
``site-packages/``. Lines starting with ``import`` are executed as Python.
The ``relenv.pth`` file dropped into the base interpreter's
``site-packages/`` is the one and only hook that gets the relenv runtime
loaded.

The ``.pth`` body is assembled by :mod:`relenv.build.common.install` — see
``relenv/build/common/install.py:44`` — and looks like:

.. code-block:: python

   import os; import sys; from importlib import util; from pathlib import Path;
   spec = util.spec_from_file_location(
       'relenv.runtime',
       str(Path(__file__).parent / 'site-packages' / 'relenv' / 'runtime.py')
   );
   mod = util.module_from_spec(spec);
   sys.modules['relenv.runtime'] = mod;
   spec.loader.exec_module(mod);
   mod.bootstrap();

A plain ``import relenv.runtime`` would be shorter, but it is deliberately
avoided. The comment block at ``relenv/runtime.py:64`` explains why: the
:class:`importlib.machinery.SourceFileLoader` form loads *this* relenv by
absolute path, so it cannot accidentally resolve to some other ``relenv``
package elsewhere on :data:`sys.path`, and it runs before
:func:`wrapsitecustomize` has had a chance to prune
:data:`sys.path` down to the onedir.

Once the module is loaded, :func:`bootstrap` is called.

``bootstrap()`` call chain
--------------------------

The body of :func:`bootstrap` at ``relenv/runtime.py:1231`` is short and
linear. Each line is a distinct fix-up:

1. ``warnings.filterwarnings(...)`` — suppress a known noisy
   ``ImportWarning`` emitted by ``importlib._bootstrap`` complaining about
   the meta-path hook's legacy ``find_module`` fallback. The warning is
   cosmetic.

2. ``sys.RELENV = relenv_root()`` — stash the onedir root on the ``sys``
   module as :attr:`sys.RELENV`. Every later wrapper that needs to resolve
   a path relative to the onedir reads it from here.
   :func:`relenv_root` walks up from ``__file__`` by a
   platform-specific number of parents
   (``relenv/runtime.py:157``): on Windows the layout is
   ``<root>/Lib/site-packages/relenv/``; on POSIX it is
   ``<root>/lib/pythonX.Y/site-packages/relenv/``.

3. :func:`setup_openssl` — configure OpenSSL. On POSIX the function
   invokes ``openssl version -m`` and ``openssl version -d`` on the
   system ``openssl`` binary to locate the system's modules directory
   and certificate directory, loads the FIPS provider from the system
   location if one is configured, then loads relenv's own ``default``
   and ``legacy`` providers from ``<root>/lib/ossl-modules``, and
   finally sets ``SSL_CERT_DIR`` / ``SSL_CERT_FILE`` to the system's
   certificate store when they are not already set. The FIPS-first
   load order is required for TLS to work correctly on FIPS hosts.

4. ``site.execsitecustomize = wrapsitecustomize(site.execsitecustomize)``
   — wrap :mod:`site`'s late customization hook (see
   ``relenv/runtime.py:1084``). The wrapper runs after the original
   fires and does two things: it rewrites :data:`sys.path` via
   ``common.sanitize_sys_path`` so entries outside the onedir are
   removed, and it sets ``site.ENABLE_USER_SITE = False`` to keep
   ``~/.local`` packages from leaking in. The ``sys.path`` munging is
   skipped when a :mod:`sitecustomize` whose file lives under a
   ``pip-build-env`` directory is detected, because pip's isolated
   build environments legitimately depend on their own ``sys.path``
   layout.

5. :func:`setup_crossroot` — if ``RELENV_CROSS`` is set
   (``relenv/runtime.py:1066``), reset :data:`sys.prefix`,
   :data:`sys.exec_prefix`, and :data:`sys.path` to point at the
   cross-build target root rather than the running interpreter's
   onedir. Used only during cross-builds; a no-op otherwise.

6. :func:`install_cargo_config` — on Linux, drop a ``config.toml`` into
   relenv's cargo home (``<data>/cargo/``) that pins the Rust linker to
   the relenv toolchain's ``<triplet>-gcc`` and bakes rpaths to
   ``<root>/lib`` into the ``RUSTFLAGS`` passed later from
   :func:`wrap_pip_build_wheel`. This is what lets
   ``pip install cryptography`` / ``pyo3`` / ``rpds-py`` and other
   Rust-backed wheels build and link against the toolchain rather than
   the host's system compiler. See ``relenv/runtime.py:879``. The
   function is also careful to only rewrite the file when the linker
   path has actually changed, so repeated bootstraps do not churn it.

7. :func:`wrap_venv` — monkey-patch
   :meth:`venv.EnvBuilder.post_setup` so that every child venv created
   by ``python -m venv`` carries its own ``relenv.pth`` pointing by
   absolute path at this installation's ``runtime.py``. This is
   gh-161; see :ref:`venv-children` below. The implementation
   (``relenv/runtime.py:1124``) is idempotent (guarded by
   ``EnvBuilder._relenv_wrapped``), skips pip's own ``pip-build-env``
   venvs for the same reason :func:`wrapsitecustomize` does, and
   swallows an :exc:`ImportError` if :mod:`venv` is missing from a
   stripped-down interpreter.

8. ``sys.meta_path = [importer] + sys.meta_path`` — install the
   module-level :data:`importer` as the highest-priority finder on
   :data:`sys.meta_path`. :data:`importer` is a :class:`RelenvImporter`
   constructed at module import time
   (``relenv/runtime.py:863``) with the full wrapper list described
   in the next section.

9. For Python 3.13 and newer, :func:`bootstrap` ends with an explicit
   ``wrap_sysconfig("sysconfig")`` call. In 3.13 :mod:`sysconfig`
   became a package rather than a module, and meta-path finders are
   not consulted for already-imported packages the way they are for
   modules, so the :class:`RelenvImporter` would never see the
   ``sysconfig`` import. The explicit call forces the wrapper on.

The ``RelenvImporter`` meta-path hook
-------------------------------------

The core of the runtime is :class:`RelenvImporter`
(``relenv/runtime.py:501``), a :pep:`451`-style finder registered at the
head of :data:`sys.meta_path`. Each wrapped module is described by a
:class:`Wrapper` entry — a tuple of ``(module name, wrapper function,
match mode)`` — and the finder's :meth:`find_spec` returns a loader
spec only for names that match a :class:`Wrapper`. Every other import
returns ``None``, so unrelated modules (the overwhelming majority) are
unaffected and incur only a dict lookup of overhead.

The full list of wrappers registered at ``relenv/runtime.py:863`` is:

===========================================  ===================================
Module intercepted                           Wrapper function
===========================================  ===================================
``sysconfig``                                :func:`wrap_sysconfig`
``pip._vendor.distlib.scripts``              :func:`wrap_pip_distlib_scripts`
``distutils.command.build_ext``              :func:`wrap_distutils_command`
``pip._internal.operations.install.wheel``   :func:`wrap_pip_install_wheel`
``pip._internal.operations.install.legacy``  :func:`wrap_pip_install_legacy`
``pip._internal.operations.build.wheel``     :func:`wrap_pip_build_wheel`
``pip._internal.commands.install``           :func:`wrap_cmd_install`
``pip._internal.locations``                  :func:`wrap_locations`
``pip._internal.cli.req_command``            :func:`wrap_req_command`
``pip._internal.req.req_install``            :func:`wrap_req_install`
===========================================  ===================================

Each wrapper imports the target module, swaps selected attributes for
wrapped versions, and returns the module. For example,
:func:`wrap_sysconfig` (``relenv/runtime.py:579``) replaces
:func:`sysconfig.get_config_var` with :func:`get_config_var_wrapper`.
The wrapper intercepts the ``BINDIR`` config var in particular
(``relenv/runtime.py:199``):

.. code-block:: python

   def wrapped(name):
       if name == "BINDIR":
           if os.environ.get("RELENV_PIP_DIR"):
               return relenv_root()
           return relenv_root() / "Scripts"
       return func(name)

so pip, which uses ``BINDIR`` to decide where to drop console_scripts,
sees ``<root>/Scripts`` under normal operation and ``<root>/`` when
``RELENV_PIP_DIR`` is set. :func:`wrap_sysconfig` is also idempotent:
:func:`functools.wraps` stamps ``__wrapped__`` on each layer, and the
function checks for that marker before wrapping so repeated calls to
:func:`bootstrap` — triggered, for instance, by
``importlib.reload(site)`` — do not stack layers (issue #321).

The other wrappers follow the same shape: :func:`wrap_pip_distlib_scripts`
rewrites script shebangs to a relative-path form via :func:`_build_shebang`;
:func:`wrap_pip_install_wheel` and :func:`wrap_pip_install_legacy` walk
freshly-installed native extensions and re-run :mod:`relenv.relocate` on
them so rpaths point back at ``<root>/lib`` (gated on ``RELENV_BUILDENV``);
:func:`wrap_pip_build_wheel` exports ``CARGO_HOME``, ``OPENSSL_DIR``, and
``RUSTFLAGS`` so PEP 517 wheel builds pick up the relenv toolchain; and the
``wrap_cmd_install`` / ``wrap_locations`` / ``wrap_req_command`` /
``wrap_req_install`` quartet together support ``pip install --target`` by
threading the target directory through pip's install plumbing.

Environment variables
---------------------

The runtime observes the following environment variables:

``RELENV_DEBUG``
    When truthy, :func:`debug` prints runtime diagnostic messages to
    stderr (``relenv/runtime.py:139``). Stderr is deliberate: several
    build tools parse the first line of stdout as structured data,
    and debug noise on stdout breaks them.

``RELENV_BUILDENV``
    When set, :func:`install_wheel_wrapper`
    (``relenv/runtime.py:361``) walks each freshly-installed wheel's
    ``RECORD`` and runs :func:`relenv.relocate.handle_elf` or
    :func:`relenv.relocate.handle_macho` on any ELF or Mach-O files,
    so native extensions installed via pip get rpaths pointing at
    ``<root>/lib``. Also used by :func:`get_config_vars_wrapper` and
    :func:`finalize_options_wrapper` to switch compiler flags and
    include directories to the relenv toolchain.

``RELENV_PIP_DIR``
    Switches ``sysconfig.get_config_var("BINDIR")`` from
    ``<root>/Scripts`` to ``<root>/`` and makes
    :func:`get_paths_wrapper` return the onedir root as the scripts
    scheme target. Needed by consumers (notably Salt) that expect
    pip to install console scripts directly at the relenv root.

``RELENV_CROSS``
    Path to a cross-build target root. When set,
    :func:`setup_crossroot` rewrites :data:`sys.prefix`,
    :data:`sys.exec_prefix`, and :data:`sys.path` to the cross root's
    standard library layout so the running interpreter can install
    into and introspect the cross target.

``HOST_PYTHON``
    Set by :func:`relenv.build.windows.populate_env` to
    :data:`sys.executable` during Windows builds. CPython's
    ``PCbuild\\find_python.bat`` consults ``HOST_PYTHON`` before
    searching for a ``py -X.Y`` bootstrap interpreter, which keeps
    the build from downloading a NuGet-hosted Python when the
    runner image's installed CPython versions age out.

``SSL_CERT_DIR``, ``SSL_CERT_FILE``
    Not strictly relenv-defined, but :func:`setup_openssl` will
    populate them from the system ``openssl`` binary's reported
    certificate directory when they are not already set in the
    environment. Pre-existing values are left alone.

``OPENSSL_MODULES``, ``CARGO_HOME``, ``OPENSSL_DIR``, ``RUSTFLAGS``
    :func:`setup_openssl` skips its provider-loading dance entirely
    when ``OPENSSL_MODULES`` is already set, and
    :func:`wrap_pip_build_wheel` uses :func:`set_env_if_not_set` to
    export ``CARGO_HOME``, ``OPENSSL_DIR``, and ``RUSTFLAGS`` for
    PEP 517 wheel builds — pre-existing values are preserved and a
    warning is emitted to stderr if they disagree with what relenv
    would have set.

.. _venv-children:

venv children (gh-161)
----------------------

Stdlib ``python -m venv <target>`` creates a child environment with its
own :data:`sys.prefix` and its own freshly-populated ``site-packages/``,
and does *not* copy any ``.pth`` files from the parent. Without
intervention, the child's interpreter never runs
``relenv.runtime.bootstrap()``: OpenSSL providers are loaded in the wrong
order, the :class:`RelenvImporter` is absent, sysconfig returns unpatched
paths, and the child's pip proceeds to drop binaries with wrong rpaths
and shebangs.

:func:`wrap_venv` closes the loop. It monkey-patches
:meth:`venv.EnvBuilder.post_setup` so that after CPython has finished
populating the child, relenv writes a ``relenv.pth`` into the child's
``site-packages/``. The ``.pth`` body is identical in shape to the one
in ``relenv/build/common/install.py``, except the path to ``runtime.py``
is baked in verbatim via :func:`repr` so Windows paths and exotic
characters round-trip safely. The absolute path matters: the child has
no ``relenv`` package of its own and cannot locate the base interpreter's
runtime by any other means.

Scope is deliberately limited to stdlib :mod:`venv`. ``virtualenv``,
``uv venv``, and ``poetry env`` each drive their own venv-creation paths
that do not route through :class:`venv.EnvBuilder`, and would need
parallel hooks to inherit the bootstrap. Follow-up tracked on gh-161.

API reference
-------------

.. automodule:: relenv.runtime
    :members:
