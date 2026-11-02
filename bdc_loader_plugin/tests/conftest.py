#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
conftest.py — Shared test configuration

Installs QGIS/PyQt5/GDAL/matplotlib mocks before any plugin imports.
pytest loads this automatically before collecting tests.
"""

import os
import sys

# Ensure workspace root is in path
_workspace_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _workspace_dir not in sys.path:
    sys.path.insert(0, _workspace_dir)


# Install mocks BEFORE any plugin imports
from bdc_loader_plugin.tests.qgis_mock import install_mocks

install_mocks()
