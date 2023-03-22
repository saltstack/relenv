Additional Dependencies (Linux)
-------------------------------

Some python libraries do not provide wheels and require additional libraries to
install properly. You can handle installing these python packages in two ways.
You build them using system dependencies or you can install the needed
depenency libraries into a relenv environment.

The general procedure for installing python modules to use your system's
libraries is to install the required sytem packages which contain the header
files needed for the package. Then using your system's compiler configured with
the system include path and system librariy directory.

To install additional libraries into the relenv environment you will compile
the library from source using the relenv toolchain compiler. Relenv provides
the ``relenv buildenv`` to help simplify setting up your environment to use the
relenv toolchain.Link the library against relenv's library directory and
setting the rpath to relenvs' library directory. Then run ``relenv check`` to
check and potentially fix the binary's rpath, making it relative. Finally using
pip to install the intended python library.


Installing pycurl Using System Libraries
========================================

This is an example of installing pycurl using the system's libcurl on Debian Linux.

.. code-block:: bash

   relenv create myenv
   sudo apt-get install libcurl4-openssl-dev
   CC=/usr/bin/gcc CFLAGS="-I/usr/include" LDFLAGS="-L/usr/lib" myenv/bin/pip3 install pycurl --no-cache


Installing pygit2 Using System Libraries
========================================

This is an example of installing pygit2 using the system's libgit2 on Debian Linux.

.. code-block:: bash

   relenv create myenv
   sudo apt-get install libgit2-dev libssh2-1-dev
   CC=/usr/bin/gcc CFLAGS="-I/usr/include" LDFLAGS="-L/usr/lib" myenv/bin/pip3 install libgit2 --no-binary=":all:"



Installing python-ldap Using System Libraries
================================================

This is an example of installing python-ldap using the system's open-ldap on Debian Linux.

.. code-block:: bash

   relenv create myenv
   sudo apt-get install openldap-dev libsasl2-dev
   CC=/usr/bin/gcc LDFLAGS="-I/usr/include -L/usr/lib" CFLAGS="-I/usr/include" myenv/bin/pip3 install python-ldap



Building and Installing curl For pycurl
=======================================

In this example, we use ``relenv buildenv`` to setup our environment. Install
curl after building it from source. Run ``relenv check`` to fix the rpaths,
making them relative. Then installing pycurl using the relenv's pip.

.. code-block:: bash

   relenv create myenv
   # C extensions require a toolchain on linux
   relenv fetch toolchain
   # Load some useful build variables into the environment
   eval $(myenv/bin/relenv buildenv)
   wget https://curl.se/download/curl-8.0.1.tar.gz
   tar xgf curl-8.0.1.tar.gz
   cd curl-8.0.1
   # Configure curl using the build environment.
   ./configure --prefix=$RELENV_PATH --with-openssl=$RELENV_PATH
   make
   make install
   cd ..
   # Install pycurl, adjust the path so pycurl can find the curl-config executable
   PATH="${RELENV_PATH}/bin:${PATH}" myenv/bin/pip3 install pycurl



Building and Installing libgit2 for pygit2
==========================================

In this example we use Cmake to build and install libssh2 and libgit2,
pre-requsits for pygit2.

.. code-block:: bash

   relenv create myenv
   # C extensions require a toolchain on linux
   relenv fetch toolchain
   # Load some useful build variables into the environment
   eval $(myenv/bin/relenv buildenv)

   # Build and install libssh2
   wget https://www.libssh2.org/download/libssh2-1.10.0.tar.gz
   tar xvf libssh2-1.10.0.tar.gz
   cd libssh2-1.10.0
   mkdir bin
   cd bin
   cmake .. \
     -DENABLE_ZLIB_COMPRESSION=ON \
     -DOPENSSL_ROOT_DIR="$RELENV_PATH" \
     -DBUILD_SHARED_LIBS=ON \
     -DBUILD_EXAMPLES=OFF \
     -DBUILD_TESTING=OFF \
     -DCMAKE_INSTALL_PREFIX="$RELENV_PATH"
   cmake --build .
   cmake --build . --target install

   cd ../..

   # Build and install libssh2 (version 0.5.x for pygit2)
   wget https://github.com/libgit2/libgit2/archive/refs/tags/v0.5.2.tar.gz
   tar xvf v0.5.2.tar.gz
   cd libgit2-0.5.2
   mkdir build
   cd build
   cmake ..  \
     -DOPENSSL_ROOT_DIR="$RELENV_PATH" \
     -DBUILD_CLI=OFF \
     -DBUILD_TESTS=OFF \
     -DUSE_SSH=ON \
     -DCMAKE_INSTALL_PREFIX="$RELENV_PATH"
   cmake --build .
   cmake --build . --target install
   cd ../..

   # Run relenv check
   myenv/bin/relenv check

   myenv/bin/pip3 install pygit2 --no-binary=":all:"



Building and Installing open-ldap For python-ldap
=================================================

In this example, we use ``relenv buildenv`` to setup our environment. Build and
install sasl and open-ldap. Run ``relenv check`` to fix the rpaths, making them
relative. Then install python-ldap using the relenv's pip.

.. code-block:: bash

   relenv create myenv
   # C extensions require a toolchain on linux
   relenv fetch toolchain
   # Load some useful build variables into the environment
   eval $(myenv/bin/relenv buildenv)

   # Build and Install sasl
   wget https://github.com/cyrusimap/cyrus-sasl/releases/download/cyrus-sasl-2.1.28/cyrus-sasl-2.1.28.tar.gz
   tar xvf cyrus-sasl-2.1.28.tar.gz
   cd cyrus-sasl-2.1.28
   ./configure --prefix=$RELENV_PATH
   make
   make install
   cd ..

   # Build and Install Open LDAP
   wget https://www.openldap.org/software/download/OpenLDAP/openldap-release/openldap-2.5.14.tgz
   tar xvf openldap-2.5.14.tgz
   cd openldap-2.5.14
   ./configure --prefix=$RELENV_PATH
   make
   make install
   cd ..

   # Fix any non-relative rpaths
   myenv/bin/relenv check

   myenv/bin/pip3 install python-ldap



