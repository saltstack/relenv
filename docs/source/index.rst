.. Relenv landing page

Relenv - Build and use relocatable Python environments
======================================================

The "standard" Python installation is not relocatable, nor is it
easily transferrable to other operating systems in the same family.

Relenv solves that problem and more.  Written entirely in Python,
it can build relocatable Python packages and use them to create environments
that pin all Python interaction to the build of your choice.

Installation
============

.. note::
   This is not accurate yet, currently the only install method is ``pip install git+https://github.com/saltstack/relative-environment-for-python.git``

You can install relenv like any other python package using pip.  Using a virtual environment is recommended.

.. code-block:: bash

   pip install relenv

Usage
=====

After installing relenv, you will have access to its CLI.  You can see all supported commands by running the following...

.. code-block:: bash

   relenv --help

Topics
======

.. toctree::
   :maxdepth: 2

   toolchain
   cli/index
   contributing
   developer/index


Relenv has no public API, but you can find documentation for the internals of relenv :doc:`here <developer/index>`.

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
