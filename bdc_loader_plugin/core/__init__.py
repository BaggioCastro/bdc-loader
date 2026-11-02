"""
Core Package

Business logic handlers for the BDC Loader QGIS Plugin:
- CatalogManager: STAC collection and band management
- SearchEngine: STAC search and result building
- ResultFilter: Tile, cloud, date, and download filtering
- GridManager: Grid download and tile selection
- ShapefileHandler: Shapefile/GPKG spatial operations
- DownloadManager: COG file download with progress
- VrtGenerator: VRT generation and QGIS layer loading
- TSCollectionManager: Time series collection loading and filtering
- TSBandManager: Band resolution, vegetation indices, RGB combo logic
- TSPointManager: Point picking, coordinates, vector loading
- TSLayerManager: Temporary point layer on map canvas
- TSHistoryManager: Extraction history management
- TSExtractionEngine: STAC search and time-series extraction
- TSVisualization: Chart dock, plotting, VRT loading, exports
"""
