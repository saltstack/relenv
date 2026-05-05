# relenv: Windows onedir for Python 3.13+ is missing `pyconfig.h`

## Repository / branch

`saltstack/relenv`, current `main` (and all releases `v0.22.7`–`v0.22.8`).

## Symptom

Any C extension built against a relenv-produced Windows onedir for Python
3.13.x fails with:

```
D:\path\to\onedir\include\Python.h(14): fatal error C1083:
    Cannot open include file: 'pyconfig.h': No such file or directory
```

Reproduced on the Salt CI run that triggered this report:
<https://github.com/saltstack/salt/actions/runs/25307474474/job/74188090475?pr=69034>

The failures show up while pip tries to build wheels for `psutil`,
`timelib`, `markupsafe._speedups`, etc. against a Salt onedir that uses
relenv's `3.13.13-amd64-win.tar.xz` / `3.13.13-x86-win.tar.xz`.

## Direct evidence

`tar tJf 3.13.13-amd64-win.tar.xz | grep -i pyconfig` → no matches.
`tar tJf 3.12.13-amd64-win.tar.xz | grep -i pyconfig` → `Include/pyconfig.h`.

So the published 3.13.x Windows tarballs simply do not contain
`Include/pyconfig.h`. The 3.12.x and earlier tarballs do.

## Root cause

In `relenv/build/windows.py`, around the `build_python` step, the code
that populates `<prefix>/Include` is:

```python
shutil.copytree(
    src=str(dirs.source / "Include"),
    dst=str(dirs.prefix / "Include"),
    dirs_exist_ok=True,
)
if "3.13" not in env["RELENV_PY_MAJOR_VERSION"]:
    shutil.copy(
        src=str(dirs.source / "PC" / "pyconfig.h"),
        dst=str(dirs.prefix / "Include"),
    )
```

For Python ≤ 3.12 there is a checked-in `PC/pyconfig.h` in the CPython
source tree. The `shutil.copy` above places it next to `Python.h` in the
onedir — without it, `Python.h` cannot find the configuration macros.

In Python 3.13 the layout changed:

* `PC/pyconfig.h` was deleted from the source tree.
* `PC/pyconfig.h.in` is now a template.
* MSBuild generates the real `pyconfig.h` into the build output
  directory (`PCbuild\<arch>\pyconfig.h`).

Confirm via the upstream API:

```
gh api repos/python/cpython/contents/PC/pyconfig.h?ref=v3.13.13   # 404
gh api repos/python/cpython/contents/PC?ref=v3.13.13              # only pyconfig.h.in
```

Commit `842b42eb` ("Attempt to fix 3.13 windows build", 2024-10-21) added
the `if "3.13" not in ...` guard to stop the failing `shutil.copy(.../PC/pyconfig.h)`
on 3.13 — but never replaced it with logic that copies the *generated*
`pyconfig.h` out of the build directory. The result is a tarball with
`Python.h` but no `pyconfig.h`, which is unusable for compiling C
extensions.

CPython's own packaging script handles the same fork at
`PC/layout/main.py` (in 3.13.13):

```python
pc = ns.source / "PC"
if (pc / "pyconfig.h.in").is_file():
    yield "include/pyconfig.h", ns.build / "pyconfig.h"   # 3.13+
else:
    yield "include/pyconfig.h", pc / "pyconfig.h"         # ≤3.12
```

That's the model relenv should follow.

## Fix (proposed)

Replace the existing `if`-block in `relenv/build/windows.py` with one
that picks the source vs. build location based on whether `PC/pyconfig.h.in`
exists. Concretely:

```python
shutil.copytree(
    src=str(dirs.source / "Include"),
    dst=str(dirs.prefix / "Include"),
    dirs_exist_ok=True,
)

# Locate pyconfig.h. Python <= 3.12 ships a checked-in PC/pyconfig.h.
# Python 3.13+ replaced that with PC/pyconfig.h.in and MSBuild generates
# the real header into the build output directory. Mirror the logic in
# CPython's PC/layout/main.py.
pc_dir = dirs.source / "PC"
if (pc_dir / "pyconfig.h.in").is_file():
    pyconfig_src = build_dir / "pyconfig.h"
else:
    pyconfig_src = pc_dir / "pyconfig.h"

if not pyconfig_src.is_file():
    raise RuntimeError(
        f"Expected pyconfig.h at {pyconfig_src}; CPython build did not "
        "produce it. Check that the MSBuild step ran successfully."
    )

shutil.copy(src=str(pyconfig_src), dst=str(dirs.prefix / "Include"))
```

Notes for the implementing agent:

* `build_dir` is already in scope a few lines below — it is the variable
  used to locate `python3.lib` / `python<XY>.lib` / `*.pyd` / `*.dll`.
  Move the new code below the variable's definition or pass it in.
* The exact path inside the build output may need adjustment per arch
  (`PCbuild\amd64\pyconfig.h` vs `PCbuild\win32\pyconfig.h`). On
  inspection, MSBuild copies the final `pyconfig.h` to `$(BinaryOutputPath)`,
  and other relenv code (e.g. the `*.pyd`/`*.dll` glob and `python3.lib`
  copy) already references that same `build_dir`, so the same path is
  the right one. Verify by listing `build_dir` for both arches mid-build.
* Do **not** restore the old unconditional copy from `PC/pyconfig.h` —
  that path no longer exists on 3.13+ and will raise `FileNotFoundError`.
* Keep the `shutil.copytree(... / "Include", ...)` call as-is; the new
  copy still needs to land *after* it so the generated header overwrites
  any stale one inadvertently picked up.

## Verification

1. Build the affected onedirs locally:
   ```
   relenv build --arch amd64 --python 3.13.13
   relenv build --arch x86   --python 3.13.13
   relenv build --arch amd64 --python 3.12.13   # regression check
   ```
2. Confirm `Include/pyconfig.h` exists in each resulting `<prefix>` and
   in the `*.tar.xz` produced by the `relenv-finalize` step:
   ```
   tar tJf 3.13.13-amd64-win.tar.xz | grep -i pyconfig
   tar tJf 3.13.13-x86-win.tar.xz   | grep -i pyconfig
   tar tJf 3.12.13-amd64-win.tar.xz | grep -i pyconfig
   ```
   All three should print `Include/pyconfig.h`.
3. From the extracted onedir, build any C extension that includes
   `Python.h`:
   ```
   <onedir>\Scripts\python.exe -m pip install --no-binary :all: psutil
   ```
   This should succeed, which it currently does not on 3.13.

## Suggested test

Add a smoke check to relenv's CI that, for each Windows tarball produced,
asserts the presence of `Include/pyconfig.h`. A trivial post-build step:

```python
import tarfile, sys
with tarfile.open(sys.argv[1]) as tf:
    names = tf.getnames()
assert any(n.lower().endswith("include/pyconfig.h") for n in names), (
    f"{sys.argv[1]} is missing Include/pyconfig.h"
)
```

Run it against every `*-win.tar.xz` artifact. This would have caught the
regression introduced by `842b42eb` immediately.

## Release / consumer impact

* Salt's pyversion101 branch (Python 3.13.13) cannot produce a working
  Windows onedir with relenv `0.22.7` or `0.22.8`. Once a relenv release
  carrying this fix is cut (call it `0.22.9`), bump
  `cicd/shared-gh-workflows-context.yml` `relenv_version` in salt and
  re-run the onedir build job to confirm.
* No expected impact on Linux / macOS builds — the affected code path is
  Windows-only and the equivalent POSIX builds already ship a generated
  `pyconfig.h` correctly.

## Out of scope

* Same Salt CI run also shows a macOS arm64 onedir failure (`yaml.h
  not found` while building PyYAML's C speedups, and a `cmake_minimum_required`
  failure when pyzmq tries to build its bundled libzmq). Those are
  separate problems and are **not** addressed by this fix.
