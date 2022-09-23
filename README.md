# Mayflower

Mayflower creates re-producable and re-locatable python builds. The builds
created with Mayflower are re-producable in the sense that all binaries for the
builds are built from source. These builds are re-locatable meaning you can
move the root directory around on the filesystem.

# Installing Mayflower

```
pip install git+https://github.com/dwoz/Mayflower.git
```


# Pre-built Mayflower Python Environments

Mayflower can use pre-build Mayflower Python environments.

```
python3 -m mayflower fetch
python3 -m mayflower create foo
foo/bin/pip3 install myproject
```


# Building a Mayflower Build

**Currently building assumes your building on x86_64**

## Linux Dependencies

- make
- bison
- perl
- patchelf

**Arch linux varients also require libxcrypt-compat**
> This should get fixed in the future.

## Building on Linux

When using Mayflower to create builds on linux you first need a toolchain. You
can either build the toolchain or use a pre-built toolchain.

Using a pre-built toolchain.

```
python3 -m mayflower toolchain download
```

Building a toolchain from scratch.

```
python3 -m mayflower toolchain build
```

After installing the Mayflower toolchain for the architecture you are targeting you build a Mayflower Python build.

```
python3 -m mayflower build --clean
```

## Mac OS Dependencies

- developer tools

## Building on Mac OS

Run `python3 -m mayflower build --clean`


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
# cp -R ./build ./mycoolbuild
# mycoolbuild/bin/pip3 install mycoolpython
# tar cJf mycoolbuild.tar.xz mycoolbuild
```



# Pre-Built Mayflower Builds

Because Mayflower's builds are re-producable, a build on OS version should end
up being exactly the same as one built on another OS or version. Therefore the
builds created by the CI/CD pipelines in this repository can be used in lue of
building yourself.
