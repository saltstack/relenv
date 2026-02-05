The config.h file was removed from XZ-Utils starting with version 5.5.0.
XZ-Utils switched to CMake and removed Visual Studio project files and
pre-generated headers/sources.

We include the following files from XZ 5.4.7 to maintain compatibility with
Python's MSBuild-based build system on Windows (PCbuild/liblzma.vcxproj):

- config.h (src/common/config.h)
- crc32_table.c (src/liblzma/check/crc32_table.c)
- crc64_table.c (src/liblzma/check/crc64_table.c)

These files are copied into the extracted XZ source directory during the
Windows build process if they are missing.
