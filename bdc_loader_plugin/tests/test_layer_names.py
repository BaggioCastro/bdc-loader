"""Short layer and group names that keep a hidden machine key."""

from bdc_loader_plugin.core import layer_style
from bdc_loader_plugin.core.layer_names import (
    KEY_PROPERTY,
    area_group_display,
    area_layer_display,
    find_group,
    layer_key,
    set_display_name,
)
from bdc_loader_plugin.tests.pipeline_patch import patch_pipeline


class _Node:
    def __init__(self, name, children=(), group=True):
        self._name = name
        self._props = {}
        self._children = list(children)
        if group:
            self.addGroup = lambda *_a: None

    def name(self):
        return self._name

    def setName(self, name):
        self._name = name

    def customProperty(self, key, default=None):
        return self._props.get(key, default)

    def setCustomProperty(self, key, value):
        self._props[key] = value

    def children(self):
        return self._children

    def findGroup(self, name):
        pending = list(self._children)
        while pending:
            node = pending.pop(0)
            if hasattr(node, "addGroup") and node.name() == name:
                return node
            pending.extend(node.children())
        return None


def test_display_name_keeps_the_key():
    layer = _Node("landsat-2_crop-50.051W-16.598S-49.881W-16.429S_2026-07-23_red-green-blue", group=False)
    key = layer.name()
    set_display_name(layer, key, "2026-07-23 · red, green, blue")

    assert layer.name() == "2026-07-23 · red, green, blue"
    assert layer.customProperty(KEY_PROPERTY) == key
    assert layer_key(layer) == key


def test_layer_without_key_is_known_by_its_name():
    assert layer_key(_Node("S2-16D-2_023017_2024-01-01_B04", group=False)) == "S2-16D-2_023017_2024-01-01_B04"


def test_find_group_by_key_after_rename():
    group = _Node("landsat-2 / crop-50.051W-16.598S-49.881W-16.429S")
    set_display_name(group, group.name(), "landsat-2 / Crop 50.051W 16.598S to 49.881W 16.429S")
    root = _Node("root", [_Node("other"), _Node("parent", [group])])

    assert find_group(root, "landsat-2 / crop-50.051W-16.598S-49.881W-16.429S") is group
    assert find_group(root, "missing") is None


def test_group_named_like_another_key_is_not_taken():
    impostor = _Node("S2-16D-2 / 023017")
    impostor.setCustomProperty(KEY_PROPERTY, "S2-16D-2 / something-else")
    real = _Node("x")
    set_display_name(real, "S2-16D-2 / 023017", "x")
    root = _Node("root", [impostor, real])

    assert find_group(root, "S2-16D-2 / 023017") is real


def test_display_texts():
    assert (
        area_layer_display("S2-16D-2", "crop", "2023-07-12", ["B04", "B03", "B02"])
        == "S2-16D-2_crop_20230712_B04-B03-B02"
    )
    assert (
        area_layer_display("S2-16D-2", "Basaltos do Paran\u00e1", "2023-07-12", ["B04", "B03", "B02"])
        == "S2-16D-2_Basaltos-do-Parana_20230712_B04-B03-B02"
    )
    assert (
        area_group_display("landsat-2", "crop-x", [-50.051, -16.598, -49.881, -16.429])
        == "landsat-2 / crop 50.051W 16.598S to 49.881W 16.429S"
    )
    assert area_group_display("S2-16D-2", "ecoregions.shp-Basaltos", feature_name="Basaltos do Paran\u00e1") == (
        "S2-16D-2 / Basaltos do Paran\u00e1"
    )
    assert area_group_display("S2-16D-2", "MGRS-23LKC") == "S2-16D-2 / MGRS-23LKC"


def test_source_note_counts_disk_and_server(tmp_path):
    from bdc_loader_plugin.core.vrt_generator import _source_notes

    remote = tmp_path / "remote.vrt"
    remote.write_text("<SourceFilename>/vsicurl/https://example/a.tif</SourceFilename>")
    local = tmp_path / "local_downloaded.vrt"
    local.write_text("<SourceFilename>/data/a.tif</SourceFilename>")
    paths = [(str(remote), "a", "g"), (str(local), "b", "g"), (str(tmp_path / "c.tif"), "c", "g")]

    assert _source_notes(paths) == ["2 from your downloads", "1 streamed from the BDC"]
    assert _source_notes([]) == []


def test_ranges_are_sampled_in_workers_and_layers_built_on_the_ui_thread():
    import threading
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    import bdc_loader_plugin.core.vrt_generator as module

    main = threading.get_ident()
    built_in = []
    sampled_in = []

    class _FakeLayer:
        LayerOptions = staticmethod(lambda: SimpleNamespace(loadDefaultStyle=True))

        def __init__(self, path, name, provider, options):
            built_in.append(threading.get_ident())
            self.path = path
            assert options.loadDefaultStyle is False

        def isValid(self):
            return True

    def _sample(vrt_path):
        sampled_in.append(threading.get_ident())
        return {}

    owner = SimpleNamespace(_render_ranges_cache={}, progress_bar=MagicMock())
    with (
        patch.object(layer_style, "QgsRasterLayer", _FakeLayer),
        patch.object(layer_style, "estimate_vrt_render_ranges", side_effect=_sample),
        patch_pipeline("QCoreApplication") as qcore,
    ):
        result = module.VrtGenerator._open_raster_layers(owner, [("/a.vrt", "a"), ("/b.vrt", "b")])

    assert list(result) == ["/a.vrt", "/b.vrt"]
    assert [layer.path for layer in result.values()] == ["/a.vrt", "/b.vrt"]
    # A layer built in a worker can lose its CRS when the thread ends.
    assert built_in == [main, main]
    assert len(sampled_in) == 2 and main not in sampled_in
    assert qcore.processEvents.called


def _populate(n_features, project_layer=False, selected=0):
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    import bdc_loader_plugin.core.shapefile as module

    class _Item:
        def __init__(self, name):
            self.state = None

        def flags(self):
            return MagicMock()  # combined with the (fake) Qt flag enum

        def setFlags(self, _flags):
            pass

        def setCheckState(self, state):
            self.state = state

        def setData(self, *_args):
            pass

    class _Feature:
        def __init__(self, fid):
            self._fid = fid

        def id(self):
            return self._fid

        def geometry(self):
            return SimpleNamespace(isNull=lambda: False, isEmpty=lambda: False)

        def __getitem__(self, _key):
            return f"f{self._fid}"

    items = []
    vlayer = MagicMock()
    vlayer.getFeatures.return_value = [_Feature(i) for i in range(n_features)]
    vlayer.getSelectedFeatures.return_value = [_Feature(i) for i in range(selected)]
    vlayer.selectedFeatureCount.return_value = selected
    handler = module.ShapefileHandler.__new__(module.ShapefileHandler)
    handler._shape_vector_layer = vlayer
    handler._shape_project_layer = vlayer if project_layer else None
    handler.shape_attr_combo = SimpleNamespace(currentData=lambda: "name")
    handler.shape_feature_list = SimpleNamespace(clear=lambda: None, addItem=items.append)
    handler.shape_info_label = MagicMock()
    with patch.object(module, "QListWidgetItem", _Item):
        handler._populate_shape_features()
    checked = sum(1 for item in items if item.state == module.Qt.CheckState.Checked)
    return checked, len(items), handler.shape_info_label.setText.call_args.args[0]


def test_a_file_with_many_features_starts_with_none_checked():
    checked, total, info = _populate(60)
    assert (checked, total) == (0, 60)
    assert info == "60 features: check the ones to use"


def test_a_small_file_starts_with_all_checked():
    assert _populate(10)[:2] == (10, 10)


def test_features_selected_on_a_project_layer_are_the_ones_listed():
    checked, total, _info = _populate(60, project_layer=True, selected=3)
    assert (checked, total) == (3, 3)


def test_cancelled_preview_reads_nothing_more():
    from types import SimpleNamespace
    from unittest.mock import patch

    import bdc_loader_plugin.core.crop_preview as cp

    items = [SimpleNamespace(assets={b: SimpleNamespace(href=f"http://x/{b}.tif") for b in ("r", "g", "b")})]
    with patch.object(cp, "_read") as read:
        result = cp.render_preview(items, ["r", "g", "b"], [0, 0, 1, 1], cancel_check=lambda: True)
    assert result is None
    read.assert_not_called()


def test_a_band_the_preview_cannot_read_is_logged():
    from types import SimpleNamespace
    from unittest.mock import patch

    import bdc_loader_plugin.core.crop_preview as cp

    items = [SimpleNamespace(assets={b: SimpleNamespace(href=f"http://x/{b}.tif") for b in ("r", "g", "b")})]
    with (
        patch.object(cp, "_read", side_effect=OSError("HTTP 500")),
        patch.object(cp, "_log_warning") as warn,
    ):
        cp.render_preview(items, ["r", "g", "b"], [0, 0, 1, 1])
    assert warn.call_count == 3
    assert "HTTP 500" in warn.call_args[0][0]


def test_card_cancels_its_pending_thumbnail_and_asks_again_later():
    from bdc_loader_plugin.ui.result_widgets import ResultItemWidget

    card = ResultItemWidget.__new__(ResultItemWidget)
    card._thumb_job = None
    card._thumbnail_loading = True
    card._thumbnail_loaded = False
    job = card._start_thumb_job()

    card.cancel_thumbnail()

    assert job.wanted is False
    assert card._thumb_job is None
    assert (card._thumbnail_loading, card._thumbnail_loaded) == (False, False)
    card.cancel_thumbnail()  # nothing pending: no error


def test_default_stretch_is_off_only_while_a_sampled_layer_is_built():
    from types import SimpleNamespace
    from unittest.mock import patch

    import bdc_loader_plugin.core.vrt_generator as module

    settings = module.QgsSettings()
    key = layer_style._DEFAULT_LIMITS_KEYS[0]
    settings.setValue(key, "CumulativeCut")
    other = layer_style._DEFAULT_LIMITS_KEYS[1]
    settings.remove(other)
    seen = {}

    class _FakeLayer:
        LayerOptions = staticmethod(lambda: SimpleNamespace(loadDefaultStyle=True))

        def __init__(self, path, name, provider, options):
            seen[path] = (settings.value(key), settings.value(other))

    with patch.object(layer_style, "QgsRasterLayer", _FakeLayer):
        layer_style._new_raster_layer("/own.vrt", "a", own_stretch=True)
        layer_style._new_raster_layer("/default.vrt", "b")

    assert seen["/own.vrt"] == ("None", "None")
    assert seen["/default.vrt"] == ("CumulativeCut", None)
    # The user's settings are back as they were, including the absent key.
    assert settings.value(key) == "CumulativeCut"
    assert not settings.contains(other)


def _fill_layer(count, dtype, nodata=False, renderer_type="multibandcolor"):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    provider = SimpleNamespace(sourceHasNoDataValue=lambda band: nodata, dataType=lambda band: dtype)
    renderer = MagicMock()
    renderer.type.return_value = renderer_type
    layer = SimpleNamespace(dataProvider=lambda: provider, bandCount=lambda: count, renderer=lambda: renderer)
    return layer, renderer


def test_only_all_zero_rgb_pixels_are_hidden():
    from unittest.mock import patch

    with patch.object(layer_style, "_integer_types", return_value={"Byte", "UInt16"}):
        layer, renderer = _fill_layer(3, "UInt16")
        assert layer_style._hide_zero_fill(layer) is True
        transparency = renderer.rasterTransparency.return_value
        (pixels,), _ = transparency.setTransparentThreeValuePixelList.call_args
        assert len(pixels) == 1
        # The renderer's own object is edited; passing it back would delete it.
        renderer.setRasterTransparency.assert_not_called()
        for args in (
            (3, "UInt16", True),
            (1, "Byte", False),
            (3, "Float32", False),
            (3, "Byte", False, "singlebandgray"),
        ):
            layer, renderer = _fill_layer(*args)
            assert layer_style._hide_zero_fill(layer) is False
            renderer.rasterTransparency.return_value.setTransparentThreeValuePixelList.assert_not_called()
