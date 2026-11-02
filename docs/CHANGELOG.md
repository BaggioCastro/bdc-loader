# Changelog

All notable changes to the **BDC Loader** plugin are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

## [1.0.0] - 2026-11-02

First public release.

### Added
- Search of the Brazil Data Cube STAC catalog by collection, period, cloud cover and area, given as BDC tiles,
  an extent drawn on the map or a vector file. The collections are listed from the catalog.
- Loading of the images of each date as QGIS layers read from the Cloud Optimized GeoTIFFs. The tiles of a
  date are mosaicked in a GDAL VRT, clipped to the search area and composed with the chosen bands.
- Download of scenes and of crops clipped to an extent or a polygon, in BDC Albers, WGS 84 or the project CRS.
- Time series of points from WTSS or read from the COGs, drawn as line charts and RGB scatter plots. A double
  click on a date of the chart opens the image of that date on the map. The series are exported as CSV or GeoPackage.
- Timeline toolbar that steps through the dates of the loaded layers.
- Offline mode: without a connection to the BDC, Search lists and loads the images already downloaded on the
  computer.
- BDC tile grids downloaded from the BDC and selected on the map canvas.
- Button that sets the QGIS project to SIRGAS 2000 / Brazil Albers (EPSG:10857).
- Interface in English and Brazilian Portuguese, switched by the flags in the header.
- Tutorial that walks through a complete case with the plugin's own buttons.
