# Copyright 2022-2023 VMware, Inc.
# SPDX-License-Identifier: Apache-2

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import pathlib
import sys

# Modify sys.path for sphinx-autodoc
docs_basepath = pathlib.Path(__file__).parent.parent.resolve()
addtl_paths = [
    pathlib.Path(".."),
]
for addtl_path in addtl_paths:
    sys.path.insert(0, str((docs_basepath / addtl_path).resolve()))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "Relenv"
copyright = "2022 VMWare, Inc."
author = "Daniel A. Wozniak"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinxarg.ext",
    "sphinx_mdinclude",
]


templates_path = ["_templates"]
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "furo"
html_static_path = ["_static"]
