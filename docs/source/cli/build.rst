=========
``build``
=========

Relenv build is resposible for building Python and it's dependencies from
source. The build process also ensures Python is re-locatable. The directory
containg the python build can be moved around on the filesystem or to another
host machine of the same architecture.

.. code-block:: bash

    relenv build

Options
=======

.. argparse::
   :module: relenv.__main__
   :func: setup_cli
   :prog: relenv
   :path: build
