
Toolchains
##########

Relenv uses toolchains to compile Python (and it's dependencies) on Linux platforms. These toolchains consist of GCC, Binutils, and GLibc and are built using `crosstool-ng`_. Relenv's toolchains are pre-built. Users of Relenv will only need a toolchain when installing C extensions which need to re-main portable accross multiple Linux OSes. When working with pure python applications users should not need to concern themselves with toolchains.


Building Toolchains
===================


Building toolchains is a farily expensive and lengthy process. It's recommended that you have 16GB of RAM and 40GB of free disk space. The example below is using Centos Stream 8.


.. code-block:: bash

   sudo yum -y groupinstall "Development Tools"
   sudo yum -y --enablerepo=powertools install vim python3 texinfo help2man ncurses-devel


Running Relenv's toolchain build command will do the following

* Download crosstool-ng
* Configure and compile crosstool-ng
* Use Relenv's crosstool config files to compile the requests architectures

.. code-block:: bash

   git clone git@github.com:saltstack/relenv.git
   cd relenv
   python3 -m relenv toolchain build --arch=x86_64 --arch=aarch64


.. _crosstool-ng: https://crosstool-ng.github.io/


Pre-Built Toolchains
====================

Under most circumstances using a pre-built toolchain is preffered over building the toolchain yourself.


.. code-block:: bash

   python3 -m relenv toolchain fetch --arch=x86_64

