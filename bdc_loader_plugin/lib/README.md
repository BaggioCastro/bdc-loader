# Vendored packages

| Package | Version | License | Copyright |
|---|---|---|---|
| pystac | 1.3.0 | Apache License 2.0 (`pystac/LICENSE`) | 2019, 2020, 2021 the authors |
| pystac-client | 0.3.2 | Apache License 2.0 (`pystac_client/LICENSE`) | 2021 Jon Duckworth |

The plugin imports them as `bdc_loader_plugin.lib.pystac` and
`bdc_loader_plugin.lib.pystac_client`. It does not add this folder to
`sys.path`, so a pystac installed by QGIS or by another plugin and this copy
never replace each other.

## Changes to the original files

`vendor_imports.py`, at the root of the repository, rewrote the absolute
imports of `pystac` and `pystac_client` inside these packages as relative
imports. Each file it changed starts with the line
`# Modified for BDC Loader: imports of pystac and pystac_client made relative (vendor_imports.py).`
Nothing else in the packages was changed.

## What they need from QGIS

pystac and pystac-client import `requests` and `python-dateutil`. The plugin
does not ship them: the Windows QGIS packages of OSGeo4W list both as
requirements, and the CI runs the plugin in the QGIS of conda-forge on Linux,
Windows and macOS and in the qgis/qgis 3.22 Docker image, which have both.
