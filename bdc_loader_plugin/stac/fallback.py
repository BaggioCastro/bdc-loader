"""
STAC Fallback Configuration

Provides hardcoded configurations for STAC collections, bands, grids, and RGB presets.
Used as a fallback when the BDC STAC API is unreachable or responds without sufficient metadata.

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

from datetime import datetime, timedelta

# Date this fallback data was last synced from the live BDC STAC API.
# If the plugin detects the fallback is older than 180 days, it will log a warning.
FALLBACK_UPDATED = "2026-04-15"


def _dynamic_end_date():
    """Returns a temporal end date 6 months into the future, avoiding expiration."""
    return (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d")


FALLBACK_BAND_INFO = {
    "S2-16D-2": {
        "B01": {"common_name": "coastal", "wavelength": "443 nm", "resolution": "10m"},
        "B02": {"common_name": "blue", "wavelength": "492 nm", "resolution": "10m"},
        "B03": {"common_name": "green", "wavelength": "560 nm", "resolution": "10m"},
        "B04": {"common_name": "red", "wavelength": "665 nm", "resolution": "10m"},
        "B05": {"common_name": "rededge1", "wavelength": "704 nm", "resolution": "10m"},
        "B06": {"common_name": "rededge2", "wavelength": "740 nm", "resolution": "10m"},
        "B07": {"common_name": "rededge3", "wavelength": "783 nm", "resolution": "10m"},
        "B08": {"common_name": "nir", "wavelength": "833 nm", "resolution": "10m"},
        "B8A": {"common_name": "nir08", "wavelength": "865 nm", "resolution": "10m"},
        "B09": {"common_name": "nir09", "wavelength": "945 nm", "resolution": "10m"},
        "B11": {"common_name": "swir16", "wavelength": "1614 nm", "resolution": "10m"},
        "B12": {"common_name": "swir22", "wavelength": "2202 nm", "resolution": "10m"},
        "NDVI": {"common_name": "ndvi", "wavelength": "-", "resolution": "10m"},
        "EVI": {"common_name": "evi", "wavelength": "-", "resolution": "10m"},
        "NBR": {"common_name": "nbr", "wavelength": "-", "resolution": "10m"},
        "SCL": {"common_name": "quality", "wavelength": "-", "resolution": "10m"},
    },
    "S2_L2A-1": {
        "B01": {"common_name": "coastal", "wavelength": "443 nm", "resolution": "60m"},
        "B02": {"common_name": "blue", "wavelength": "492 nm", "resolution": "10m"},
        "B03": {"common_name": "green", "wavelength": "560 nm", "resolution": "10m"},
        "B04": {"common_name": "red", "wavelength": "665 nm", "resolution": "10m"},
        "B05": {"common_name": "rededge1", "wavelength": "704 nm", "resolution": "20m"},
        "B06": {"common_name": "rededge2", "wavelength": "740 nm", "resolution": "20m"},
        "B07": {"common_name": "rededge3", "wavelength": "783 nm", "resolution": "20m"},
        "B08": {"common_name": "nir", "wavelength": "833 nm", "resolution": "10m"},
        "B8A": {"common_name": "nir08", "wavelength": "865 nm", "resolution": "20m"},
        "B09": {"common_name": "nir09", "wavelength": "945 nm", "resolution": "60m"},
        "B11": {"common_name": "swir16", "wavelength": "1614 nm", "resolution": "20m"},
        "B12": {"common_name": "swir22", "wavelength": "2202 nm", "resolution": "20m"},
        "TCI": {"common_name": "rgb", "wavelength": "-", "resolution": "10m"},
        "SCL": {"common_name": "quality", "wavelength": "-", "resolution": "20m"},
    },
    "LANDSAT-16D-1": {
        "coastal": {"common_name": "coastal", "wavelength": "440 nm", "resolution": "30m"},
        "blue": {"common_name": "blue", "wavelength": "480 nm", "resolution": "30m"},
        "green": {"common_name": "green", "wavelength": "560 nm", "resolution": "30m"},
        "red": {"common_name": "red", "wavelength": "650 nm", "resolution": "30m"},
        "nir08": {"common_name": "nir08", "wavelength": "870 nm", "resolution": "30m"},
        "swir16": {"common_name": "swir16", "wavelength": "1610 nm", "resolution": "30m"},
        "swir22": {"common_name": "swir22", "wavelength": "2200 nm", "resolution": "30m"},
        "NDVI": {"common_name": "ndvi", "wavelength": "-", "resolution": "30m"},
        "EVI": {"common_name": "evi", "wavelength": "-", "resolution": "30m"},
    },
    "landsat-2": {
        "coastal": {"common_name": "coastal", "wavelength": "440 nm", "resolution": "30m"},
        "blue": {"common_name": "blue", "wavelength": "480 nm", "resolution": "30m"},
        "green": {"common_name": "green", "wavelength": "560 nm", "resolution": "30m"},
        "red": {"common_name": "red", "wavelength": "650 nm", "resolution": "30m"},
        "nir08": {"common_name": "nir08", "wavelength": "870 nm", "resolution": "30m"},
        "swir16": {"common_name": "swir16", "wavelength": "1610 nm", "resolution": "30m"},
        "swir22": {"common_name": "swir22", "wavelength": "2200 nm", "resolution": "30m"},
        "lwir": {"common_name": "lwir", "wavelength": "11450 nm", "resolution": "30m"},
        "lwir11": {"common_name": "lwir11", "wavelength": "10900 nm", "resolution": "30m"},
    },
    "CBERS4-WFI-16D-2": {
        "BAND13": {"common_name": "blue", "wavelength": "485 nm", "resolution": "64m"},
        "BAND14": {"common_name": "green", "wavelength": "555 nm", "resolution": "64m"},
        "BAND15": {"common_name": "red", "wavelength": "660 nm", "resolution": "64m"},
        "BAND16": {"common_name": "nir", "wavelength": "830 nm", "resolution": "64m"},
        "NDVI": {"common_name": "ndvi", "wavelength": "-", "resolution": "64m"},
        "EVI": {"common_name": "evi", "wavelength": "-", "resolution": "64m"},
    },
    "CBERS-WFI-8D-1": {
        "BAND13": {"common_name": "blue", "wavelength": "485 nm", "resolution": "64m"},
        "BAND14": {"common_name": "green", "wavelength": "555 nm", "resolution": "64m"},
        "BAND15": {"common_name": "red", "wavelength": "660 nm", "resolution": "64m"},
        "BAND16": {"common_name": "nir", "wavelength": "830 nm", "resolution": "64m"},
        "NDVI": {"common_name": "ndvi", "wavelength": "-", "resolution": "64m"},
        "EVI": {"common_name": "evi", "wavelength": "-", "resolution": "64m"},
    },
    "CBERS4-MUX-2M-1": {
        "BAND5": {"common_name": "blue", "wavelength": "485 nm", "resolution": "20m"},
        "BAND6": {"common_name": "green", "wavelength": "555 nm", "resolution": "20m"},
        "BAND7": {"common_name": "red", "wavelength": "660 nm", "resolution": "20m"},
        "BAND8": {"common_name": "nir", "wavelength": "830 nm", "resolution": "20m"},
        "NDVI": {"common_name": "ndvi", "wavelength": "-", "resolution": "20m"},
        "EVI": {"common_name": "evi", "wavelength": "-", "resolution": "20m"},
    },
    "AMZ1-WFI-L4-SR-1": {
        "BAND1": {"common_name": "blue", "wavelength": "485 nm", "resolution": "64m"},
        "BAND2": {"common_name": "green", "wavelength": "555 nm", "resolution": "64m"},
        "BAND3": {"common_name": "red", "wavelength": "660 nm", "resolution": "64m"},
        "BAND4": {"common_name": "nir", "wavelength": "830 nm", "resolution": "64m"},
    },
    "mod13q1-6.1": {
        "NDVI": {"common_name": "ndvi", "wavelength": "-", "resolution": "250m"},
        "EVI": {"common_name": "evi", "wavelength": "-", "resolution": "250m"},
        "NIR_reflectance": {"common_name": "nir", "wavelength": "858 nm", "resolution": "250m"},
        "red_reflectance": {"common_name": "red", "wavelength": "645 nm", "resolution": "250m"},
        "blue_reflectance": {"common_name": "blue", "wavelength": "469 nm", "resolution": "500m"},
        "MIR_reflectance": {"common_name": "swir", "wavelength": "2130 nm", "resolution": "500m"},
    },
}


def _build_fallback_collections():
    """Build fallback collections with dynamic temporal end dates."""
    end = _dynamic_end_date()
    return {
        "Sentinel-2 Cube 16D (S2-16D-2)": {
            "id": "S2-16D-2",
            "temporal": ("2017-01-01", end),
            "bands": [
                "B02",
                "B03",
                "B04",
                "B05",
                "B06",
                "B07",
                "B08",
                "B8A",
                "B09",
                "B11",
                "B12",
                "NDVI",
                "EVI",
                "NBR",
            ],
            "grid": "BDC_SM_V2",
            "type": "cube",
            "resolution": "10m",
            "compositing": "LCF 16 days",
            "platform": "Sentinel-2A/2B",
            "doc_url": "https://brazil-data-cube.github.io/products.html",
        },
        "Sentinel-2 Scenes (S2_L2A-1)": {
            "id": "S2_L2A-1",
            "temporal": ("2018-01-02", end),
            "bands": ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B11", "B12", "TCI", "SCL"],
            "grid": "MGRS",
            "type": "collection",
            "resolution": "10-60m",
            "compositing": "Individual scenes",
            "platform": "Sentinel-2A/2B",
            "doc_url": "https://brazil-data-cube.github.io/products.html",
        },
        "Landsat Cube 16D (LANDSAT-16D-1)": {
            "id": "LANDSAT-16D-1",
            "temporal": ("1990-01-01", end),
            "bands": ["blue", "green", "red", "nir08", "swir16", "swir22", "coastal", "NDVI", "EVI"],
            "grid": "BDC_MD_V2",
            "type": "cube",
            "resolution": "30m",
            "compositing": "LCF 16 days",
            "platform": "Landsat 4-9",
            "doc_url": "https://brazil-data-cube.github.io/products.html",
        },
        "Landsat Scenes (landsat-2)": {
            "id": "landsat-2",
            "temporal": ("1990-01-01", end),
            "bands": ["blue", "green", "red", "nir08", "swir16", "swir22", "coastal", "lwir", "lwir11"],
            "grid": "WRS2",
            "type": "collection",
            "resolution": "30m",
            "compositing": "Individual scenes",
            "platform": "Landsat 4-9",
            "doc_url": "https://brazil-data-cube.github.io/products.html",
        },
        "CBERS-4 WFI Cube 16D (CBERS4-WFI-16D-2)": {
            "id": "CBERS4-WFI-16D-2",
            "temporal": ("2016-01-01", end),
            "bands": ["BAND13", "BAND14", "BAND15", "BAND16", "NDVI", "EVI"],
            "grid": "BDC_LG_V2",
            "type": "cube",
            "resolution": "64m",
            "compositing": "LCF 16 days",
            "platform": "CBERS-4",
            "doc_url": "https://brazil-data-cube.github.io/products.html",
        },
        "CBERS-4/4A WFI Cube 8D (CBERS-WFI-8D-1)": {
            "id": "CBERS-WFI-8D-1",
            "temporal": ("2020-01-01", end),
            "bands": ["BAND13", "BAND14", "BAND15", "BAND16", "NDVI", "EVI"],
            "grid": "BDC_LG_V2",
            "type": "cube",
            "resolution": "64m",
            "compositing": "LCF 8 days",
            "platform": "CBERS-4 + CBERS-4A",
            "doc_url": "https://brazil-data-cube.github.io/products.html",
        },
        "CBERS-4 MUX Cube 2M (CBERS4-MUX-2M-1)": {
            "id": "CBERS4-MUX-2M-1",
            "temporal": ("2016-01-01", end),
            "bands": ["BAND5", "BAND6", "BAND7", "BAND8", "NDVI", "EVI"],
            "grid": "BDC_MD_V2",
            "type": "cube",
            "resolution": "20m",
            "compositing": "LCF 2 months",
            "platform": "CBERS-4",
            "doc_url": "https://brazil-data-cube.github.io/products.html",
        },
        "AMAZONIA-1 WFI SR (AMZ1-WFI-L4-SR-1)": {
            "id": "AMZ1-WFI-L4-SR-1",
            "temporal": ("2024-01-01", end),
            "bands": ["BAND1", "BAND2", "BAND3", "BAND4"],
            "grid": "BDC_LG_V2",
            "type": "collection",
            "resolution": "64m",
            "compositing": "Individual scenes",
            "platform": "AMAZONIA-1",
            "doc_url": "https://brazil-data-cube.github.io/products.html",
        },
        "MODIS NDVI 16D (mod13q1-6.1)": {
            "id": "mod13q1-6.1",
            "temporal": ("2000-01-01", end),
            "bands": ["NDVI", "EVI", "NIR_reflectance", "red_reflectance", "blue_reflectance", "MIR_reflectance"],
            "grid": "BDC_SM_V2",
            "type": "cube",
            "resolution": "250m",
            "compositing": "LCF 16 days",
            "platform": "Terra/Aqua",
            "doc_url": "https://brazil-data-cube.github.io/products.html",
        },
    }


# Module-level constant built once at import time
FALLBACK_COLLECTIONS = _build_fallback_collections()

FALLBACK_GRID_URLS = {
    "BDC_LG_V2": "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows?service=WFS&request=GetFeature&outputFormat=shape-zip&typeName=bdc_catalog:BDC_LG_V2",
    "BDC_MD_V2": "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows?service=WFS&request=GetFeature&outputFormat=shape-zip&typeName=bdc_catalog:BDC_MD_V2",
    "BDC_SM_V2": "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows?service=WFS&request=GetFeature&outputFormat=shape-zip&typeName=bdc_catalog:BDC_SM_V2",
    "BDC_MD_MOZ": "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows?service=WFS&request=GetFeature&outputFormat=shape-zip&typeName=bdc_catalog:BDC_MD_MOZ",
    "MUX_GRID": "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows?service=WFS&request=GetFeature&outputFormat=shape-zip&typeName=bdc_catalog:MUX_GRID&bbox=-75,-35,-28,6,EPSG:4326",
    "MGRS": "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows?service=WFS&request=GetFeature&outputFormat=shape-zip&typeName=bdc_catalog:MGRS&bbox=-75,-35,-28,6,EPSG:4326",
    "STG": "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows?service=WFS&request=GetFeature&outputFormat=shape-zip&typeName=bdc_catalog:STG&bbox=-75,-35,-28,6,EPSG:4326",
    "WRS2": "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows?service=WFS&request=GetFeature&outputFormat=shape-zip&typeName=bdc_catalog:WRS2&bbox=-75,-35,-28,6,EPSG:4326",
    "grid_amazonia_1_wfi": "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows?service=WFS&request=GetFeature&outputFormat=shape-zip&typeName=bdc_catalog:grid_amazonia_1_wfi&bbox=-75,-35,-28,6,EPSG:4326",
    "grid_cbers4a_wfi": "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows?service=WFS&request=GetFeature&outputFormat=shape-zip&typeName=bdc_catalog:grid_cbers4a_wfi&bbox=-75,-35,-28,6,EPSG:4326",
    "cbers4a_mux": "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows?service=WFS&request=GetFeature&outputFormat=shape-zip&typeName=bdc_catalog:cbers4a_mux&bbox=-75,-35,-28,6,EPSG:4326",
    "grid_cbers2": "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows?service=WFS&request=GetFeature&outputFormat=shape-zip&typeName=bdc_catalog:grid_cbers2&bbox=-75,-35,-28,6,EPSG:4326",
    "glad_ard_tile_system": "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows?service=WFS&request=GetFeature&outputFormat=shape-zip&typeName=bdc_catalog:glad_ard_tile_system&bbox=-75,-35,-28,6,EPSG:4326",
}

# WFS base URL for remote grid loading (no download needed)
BDC_GEOSERVER_WFS = "https://data.inpe.br/bdc/geoserver/bdc_catalog/ows"


def bdc_grid_wfs_uri(grid_name):
    """QGIS WFS data source of a BDC catalogue grid; only tiles in view are requested."""
    return (
        f"url={BDC_GEOSERVER_WFS} "
        f"typename=bdc_catalog:{grid_name} "
        f"srsname=EPSG:4326 "
        f"restrictToRequestBBOX=1 "
        f"version=auto"
    )


# Brazil approximate bounding box (with slight margin)
BRAZIL_BBOX = [-75.0, -35.0, -28.0, 6.0]

FALLBACK_RGB_PRESETS = {
    "Sentinel-2 Cube 16D (S2-16D-2)": {
        "True Color (4,3,2)": ["B04", "B03", "B02"],
        "False Color (8,4,3)": ["B08", "B04", "B03"],
        "SWIR (12,8A,4)": ["B12", "B8A", "B04"],
        "Agriculture (11,8,2)": ["B11", "B08", "B02"],
        "Vegetation (8,6,4)": ["B08", "B06", "B04"],
    },
    "Sentinel-2 Scenes (S2_L2A-1)": {
        "TCI (native RGB)": ["TCI"],
        "True Color (4,3,2)": ["B04", "B03", "B02"],
        "False Color (8,4,3)": ["B08", "B04", "B03"],
        "SWIR (12,8A,4)": ["B12", "B8A", "B04"],
        "Agriculture (11,8,2)": ["B11", "B08", "B02"],
        "Vegetation (8,6,4)": ["B08", "B06", "B04"],
    },
    "Landsat Cube 16D (LANDSAT-16D-1)": {
        "True Color": ["red", "green", "blue"],
        "False Color": ["nir08", "red", "green"],
        "SWIR": ["swir16", "nir08", "red"],
    },
    "Landsat Scenes (landsat-2)": {
        "True Color": ["red", "green", "blue"],
        "False Color": ["nir08", "red", "green"],
        "SWIR": ["swir16", "nir08", "red"],
    },
    "CBERS-4 WFI Cube 16D (CBERS4-WFI-16D-2)": {
        "True Color (15,14,13)": ["BAND15", "BAND14", "BAND13"],
        "False Color (16,15,14)": ["BAND16", "BAND15", "BAND14"],
    },
    "CBERS-4/4A WFI Cube 8D (CBERS-WFI-8D-1)": {
        "True Color (15,14,13)": ["BAND15", "BAND14", "BAND13"],
        "False Color (16,15,14)": ["BAND16", "BAND15", "BAND14"],
    },
    "CBERS-4 MUX Cube 2M (CBERS4-MUX-2M-1)": {
        "True Color (7,6,5)": ["BAND7", "BAND6", "BAND5"],
        "False Color (8,7,6)": ["BAND8", "BAND7", "BAND6"],
    },
    "AMAZONIA-1 WFI SR (AMZ1-WFI-L4-SR-1)": {
        "True Color (3,2,1)": ["BAND3", "BAND2", "BAND1"],
        "False Color (4,3,2)": ["BAND4", "BAND3", "BAND2"],
    },
    "MODIS NDVI 16D (mod13q1-6.1)": {
        "False Color (NIR,Red,Blue)": ["NIR_reflectance", "red_reflectance", "blue_reflectance"],
        "NDVI Focus": ["NDVI", "EVI", "red_reflectance"],
    },
}

ID_TO_DISPLAY_NAME = {v["id"]: k for k, v in FALLBACK_COLLECTIONS.items()}
