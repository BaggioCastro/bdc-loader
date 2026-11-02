# Modified for BDC Loader: imports of pystac and pystac_client made relative (vendor_imports.py).
__all__ = [
    "merge_common_properties",
    "migrate_to_latest",
    "STACVersionRange",
    "identify_stac_object",
    "identify_stac_object_type",
]
from ...pystac.serialization.identify import (
    STACVersionRange,
    identify_stac_object,
    identify_stac_object_type,
)
from ...pystac.serialization.common_properties import merge_common_properties
from ...pystac.serialization.migrate import migrate_to_latest
