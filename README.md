# Relenv

Relenv creates re-producable and re-locatable python builds. The builds
created with Relenv are re-producable in the sense that all binaries for the
builds are built from source. These builds are re-locatable meaning you can
move the root directory around on the filesystem.

# Installing Relenv

```
pip install git+https://github.com/saltstack/relative-environment-for-python.git
```


# Pre-built Relenv Python Environments

Relenv can use pre-build Relenv Python environments.

```
python3 -m relenv fetch
python3 -m relenv create foo
foo/bin/pip3 install myproject
```


# Building a Relenv Build

**Currently building assumes your building on x86_64**

## Linux Dependencies

- make
- bison
- perl
- patchelf

**Arch linux varients also require libxcrypt-compat**
> This should get fixed in the future.

## Building on Linux

When using Relenv to create builds on linux you first need a toolchain. You
can either build the toolchain or use a pre-built toolchain.

Using a pre-built toolchain.

```
python3 -m relenv toolchain download
```

Building a toolchain from scratch.

```
python3 -m relenv toolchain build
```

After installing the Relenv toolchain for the architecture you are targeting you build a Relenv Python build.

```
python3 -m relenv build --clean
```

## Mac OS Dependencies

- developer tools

## Building on Mac OS

Run `python3 -m relenv build --clean`


# How it Works

1. Build python from source.

2. Modify the rpath of all binaries so that shared libraries are loaded via
   relative paths.

3. Modify the shebangs of Python's scripts run Python using a relative path.

4. Install a small wrapper around Pip which makes sure the shebangs of
   installed scripst use the relative python. This wrapper will also limit the
   `PYTHONPATH` of scripts run to directories in our python environment.

# Using The Build

After a build completes succesfully you'll have a self contained python. It
should work just like any other python installation. The difference is this
python can be moved around on the filesystem or even to other machines.

```/bin/sh
python3 relenv create myproject
./myproject/bin/pip3 install myproject
zip myproject.zip myproject
```

The newly created `myproject` relenv environment can be sent to freind,
co-worker, or customer.


# Pre-Built Relenv Builds

Because Relenv's builds are re-producable, a build on OS version should end
up being exactly the same as one built on another OS or version. Therefore the
builds created by the CI/CD pipelines in this repository can be used in lue of
building yourself.
