# Mayflower

Mayflower creates re-producable and re-locatable python builds. The builds
created with Mayflower are re-producable in the sense that all binaries for the
builds are built from source. These builds are re-locatable meaning you can
move the root directory around on the filesystem.

## Linux Dependencies
- gcc
- make
- bison
- libtool

## Building on Linux

Running `python3 -m mayflower.build.linux --clean` will, if successful, create a python
environment to the `build/` directory. All of the dependencies needed for
Python are located in `build/lib`.

## Mac OS Dependencies
- developer tools

## Building on Mac OS

Run `python3 -m mayflower.build.darwin --clean`
