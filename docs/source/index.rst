.. Relenv landing page

Relenv - Build and use relocatable Python environments
=========================================================

The "standard" Python installation is not relocatable, nor is it 
easily transferrable to other operating systems in the same family.

Relenv solves that problem and more.  Written entirely in Python, 
it can build relocatable Python packages and use them to create environments 
that pin all Python interaction to the build of your choice.

Installation
============

TODO: During the first release of relenv, replace this with the suggested installation process.

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


Relenv has no public API, but you can find documentation for the internals of relenv :doc:`here <developer/index>`.

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
