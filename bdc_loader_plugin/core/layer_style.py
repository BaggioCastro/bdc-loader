"""Raster layers for loaded VRTs: opened without QGIS's default stretch sampling, then styled with the precomputed range, a class palette or a transparent zero fill."""

from qgis.core import (
    Qgis,
    QgsContrastEnhancement,
    QgsPalettedRasterRenderer,
    QgsRasterLayer,
    QgsRasterTransparency,
    QgsSettings,
    QgsStyle,
)
from qgis.PyQt.QtGui import QColor

from ..logger import info as _log_info
from ..logger import warning as _log_warning
from .render_ranges import estimate_vrt_render_ranges


def _render_ranges(vrt_path, render_ranges_cache):
    """Display range of a VRT; GDAL only, so safe to run in a worker thread.

    The range comes from the precomputed cache when there is one (membership,
    not truthiness, so a remote VRT with no usable range is never sampled
    again); otherwise the source is sampled here.
    """
    if vrt_path in render_ranges_cache:
        return render_ranges_cache[vrt_path]
    return estimate_vrt_render_ranges(vrt_path)


# QGIS settings for the stretch a new raster layer computes for itself.
_DEFAULT_LIMITS_KEYS = tuple(
    f"/Raster/defaultContrastEnhancementLimits/{kind}"
    for kind in ("singleBand", "multiBandSingleByte", "multiBandMultiByte")
)


def _new_raster_layer(vrt_path, layer_name, own_stretch=False):
    """Raster layer for ``vrt_path``; UI thread only.

    A layer built in a worker thread builds its CRS there, and QGIS can drop
    that CRS when the thread ends: a BDC Albers layer was left without a
    CRS, and a UTM one made every later transform from its EPSG code return
    the input unchanged, so the layer drew nothing outside its own CRS.

    With ``own_stretch`` the caller applies its sampled stretch afterwards,
    so QGIS's default stretch is switched off while the layer is built: it
    reads a sample of the raster, which over /vsicurl/ costs several remote
    reads for a large scene. The user's settings are put back as they were.
    """
    options = QgsRasterLayer.LayerOptions()
    options.loadDefaultStyle = False
    if not own_stretch:
        return QgsRasterLayer(vrt_path, layer_name, "gdal", options)
    settings = QgsSettings()
    saved = {key: (settings.contains(key), settings.value(key)) for key in _DEFAULT_LIMITS_KEYS}
    try:
        for key in _DEFAULT_LIMITS_KEYS:
            settings.setValue(key, "None")
        return QgsRasterLayer(vrt_path, layer_name, "gdal", options)
    finally:
        for key, (present, value) in saved.items():
            if present:
                settings.setValue(key, value)
            else:
                settings.remove(key)


def _class_colors(count):
    """``count`` distinct colors along the Spectral ramp (hues when it is missing)."""
    ramp = None
    try:
        ramp = QgsStyle.defaultStyle().colorRamp("Spectral")
    except Exception:
        ramp = None
    colors = []
    for i in range(count):
        position = i / (count - 1) if count > 1 else 0.5
        colors.append(ramp.color(position) if ramp is not None else QColor.fromHsvF(position * 0.8, 0.7, 0.9))
    return colors


def _apply_class_palette(layer, classes):
    """Draw a class band whose color table is a gray ramp with one color per class."""
    entries = [
        QgsPalettedRasterRenderer.Class(value, color, str(value))
        for value, color in zip(classes, _class_colors(len(classes)))
    ]
    layer.setRenderer(QgsPalettedRasterRenderer(layer.dataProvider(), 1, entries))


def _integer_types():
    """16- and 32-bit integer types: reflectance products where 0 in every
    band is fill. 8-bit "visual" composites are left out, since black water
    is a genuine (0, 0, 0) there."""
    names = ("UInt16", "Int16", "UInt32", "Int32")
    enum = getattr(Qgis, "DataType", None)
    return {getattr(enum, name) for name in names if enum is not None and hasattr(enum, name)}


def _black_pixel():
    """A fully transparent (0, 0, 0) entry, for QGIS 3.22 to 4.x."""
    pixel_type = QgsRasterTransparency.TransparentThreeValuePixel
    try:
        return pixel_type(0, 0, 0, 0.0)  # red, green, blue, opacity (QGIS >= 3.32)
    except TypeError:
        pixel = pixel_type()
        pixel.red = pixel.green = pixel.blue = 0
        pixel.percentTransparent = 100
        return pixel


def _hide_zero_fill(layer):
    """Draw pixels whose three displayed bands are all 0 as transparent.

    Reflectance scenes served without a nodata value (S2_L2A-1) fill the
    area outside their imagery with 0, which QGIS otherwise draws as opaque
    black. Only pixels that are 0 in all three bands are hidden, never a
    single band at 0 (water can read 0 in SWIR and NIR), and only for 16-
    and 32-bit integers (see _integer_types). Single bands are left alone.
    """
    count = layer.bandCount()
    renderer = layer.renderer()
    if count < 3 or renderer is None or renderer.type() != "multibandcolor":
        return False
    provider = layer.dataProvider()
    integers = _integer_types()
    for band in range(1, count + 1):
        if provider.sourceHasNoDataValue(band) or provider.dataType(band) not in integers:
            return False
    # Edit the renderer's own transparency in place: setRasterTransparency()
    # deletes the current object first, so it cannot be handed back to it.
    transparency = renderer.rasterTransparency()
    if transparency is None:
        renderer.setRasterTransparency(QgsRasterTransparency())
        transparency = renderer.rasterTransparency()
    transparency.setTransparentThreeValuePixelList([_black_pixel()])
    return True


def _style_raster_layer(layer, vrt_path, layer_name, render_ranges):
    """Check ``layer`` and apply its sampled contrast stretch (UI thread)."""
    if layer is None or not layer.isValid():
        _log_warning(f"Invalid raster layer: {layer_name} ({vrt_path})")
        return None
    classes = getattr(render_ranges, "classes", None)
    if classes and layer.bandCount() == 1:
        try:
            _apply_class_palette(layer, classes)
            _log_info(f"Raster layer drawn with {len(classes)} class colors: {layer_name}")
            return layer
        except Exception as exc:
            _log_warning(f"Could not color the classes of {layer_name}: {exc}")
    if render_ranges:
        try:
            renderer = layer.renderer()
            used_bands = list(renderer.usesBands()) if renderer is not None else []
            if any(band_no not in render_ranges for band_no in used_bands):
                # Built without QGIS's stretch (see _new_raster_layer); a band
                # the sample missed gets the default one back.
                layer.setDefaultContrastEnhancement()
                renderer = layer.renderer()
            provider = layer.dataProvider()

            def _contrast_enhancement(band_no):
                render_range = render_ranges.get(band_no)
                if render_range is None:
                    return None
                enhancement = QgsContrastEnhancement(provider.dataType(band_no))
                enhancement.setMinimumValue(render_range[0])
                enhancement.setMaximumValue(render_range[1])
                enhancement.setContrastEnhancementAlgorithm(
                    QgsContrastEnhancement.ContrastEnhancementAlgorithm.StretchToMinimumMaximum
                )
                return enhancement

            applied = False
            if len(used_bands) == 1 and hasattr(renderer, "setContrastEnhancement"):
                band_no = used_bands[0]
                enhancement = _contrast_enhancement(band_no)
                if enhancement is not None:
                    renderer.setContrastEnhancement(enhancement)
                    applied = True
            elif renderer is not None:
                channel_methods = (
                    ("redBand", "setRedContrastEnhancement"),
                    ("greenBand", "setGreenContrastEnhancement"),
                    ("blueBand", "setBlueContrastEnhancement"),
                )
                for band_method, enhancement_method in channel_methods:
                    if not hasattr(renderer, band_method) or not hasattr(renderer, enhancement_method):
                        continue
                    enhancement = _contrast_enhancement(getattr(renderer, band_method)())
                    if enhancement is not None:
                        getattr(renderer, enhancement_method)(enhancement)
                        applied = True

            if applied:
                layer.triggerRepaint()
                _log_info(f"Raster layer configured with sampled stretch {render_ranges}: {layer_name}")
        except Exception as exc:
            _log_warning(f"Could not configure sampled layer renderer: {exc}")

    try:
        _hide_zero_fill(layer)
    except Exception as exc:
        _log_warning(f"Could not hide the 0 fill of {layer_name}: {exc}")
    return layer
