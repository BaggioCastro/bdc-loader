#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_output_crs.py — Tests for core/output_crs.py.

Covers the projections offered at download time, the default pre-selected from
the QGIS project CRS, the filename tag that keeps one projection's download
from overwriting another's, and persistence of the last choice.

Run: python3 -m pytest bdc_loader_plugin/tests/test_output_crs.py -v
"""

import unittest
from unittest.mock import patch

from qgis.core import QgsCoordinateReferenceSystem

from bdc_loader_plugin.core import output_crs

_BDC_PROJ = (
    "+proj=aea +lat_0=-12 +lon_0=-54 +lat_1=-2 +lat_2=-22 +x_0=5000000 +y_0=10000000 +ellps=GRS80 +units=m +no_defs"
)


def _crs(authid="", proj="", wkt="", description=""):
    """A QgsCoordinateReferenceSystem stand-in with only the accessors the
    module reads populated."""
    crs = QgsCoordinateReferenceSystem(authid or proj)
    crs._authid = authid
    crs._proj = proj or authid
    crs._wkt = wkt
    crs._description = description
    return crs


class TestDefaultKey(unittest.TestCase):
    """The smart default: never silently reproject a project that is already
    on one of the two grids the plugin knows about."""

    def test_wgs84_project_defaults_to_wgs84(self):
        self.assertEqual(output_crs.default_key(_crs(authid="EPSG:4326")), output_crs.WGS84)

    def test_bdc_albers_project_defaults_to_native(self):
        self.assertEqual(output_crs.default_key(_crs(authid="EPSG:10857")), output_crs.NATIVE)

    def test_custom_bdc_albers_definition_also_defaults_to_native(self):
        """A QGIS install without EPSG:10857 carries the same grid as a custom
        PROJ definition; that must not be mistaken for an unrelated CRS."""
        self.assertEqual(output_crs.default_key(_crs(proj=_BDC_PROJ)), output_crs.NATIVE)

    def test_other_project_crs_defaults_to_the_project(self):
        self.assertEqual(output_crs.default_key(_crs(authid="EPSG:31983")), output_crs.PROJECT)

    def test_missing_project_crs_defaults_to_native(self):
        self.assertEqual(output_crs.default_key(None), output_crs.NATIVE)

    def test_reads_the_project_crs_when_none_is_passed(self):
        with patch.object(output_crs, "current_project_crs", return_value=_crs(authid="EPSG:4326")):
            self.assertEqual(output_crs.default_key(), output_crs.WGS84)


class TestBuildOptions(unittest.TestCase):
    def test_three_options_in_dialog_order(self):
        options = output_crs.build_options(_crs(authid="EPSG:31983", description="SIRGAS 2000 / UTM zone 23S"))

        self.assertEqual([o.key for o in options], [output_crs.NATIVE, output_crs.WGS84, output_crs.PROJECT])
        self.assertIn("BDC Albers", options[0].label)
        self.assertIn("EPSG:4326", options[1].label)
        self.assertIn("SIRGAS 2000 / UTM zone 23S", options[2].label)
        self.assertIn("EPSG:31983", options[2].label)

    def test_native_option_never_reprojects(self):
        options = output_crs.build_options(_crs(authid="EPSG:31983"))
        self.assertIsNone(options[0].warp_srs)
        self.assertEqual(options[0].tag, "")

    def test_project_option_carries_the_epsg_code_gdal_understands(self):
        options = output_crs.build_options(_crs(authid="EPSG:31983"))
        self.assertEqual(options[2].warp_srs, "EPSG:31983")
        self.assertEqual(options[2].tag, "epsg31983")

    def test_custom_project_crs_falls_back_to_wkt(self):
        """A QGIS custom CRS reports a USER: authid that means nothing to
        GDAL, so the option has to carry the definition itself."""
        wkt = 'PROJCS["BDC Albers",GEOGCS["SIRGAS 2000"]]'
        options = output_crs.build_options(_crs(authid="USER:100001", wkt=wkt))

        self.assertEqual(options[2].warp_srs, wkt)
        self.assertTrue(options[2].tag.startswith("crs"))
        self.assertNotEqual(options[2].tag, "")

    def test_project_option_disabled_without_a_usable_project_crs(self):
        options = output_crs.build_options(None)

        self.assertFalse(options[2].enabled)
        self.assertIsNone(options[2].warp_srs)
        self.assertTrue(options[0].enabled and options[1].enabled)

    def test_every_option_has_a_hint(self):
        for option in output_crs.build_options(_crs(authid="EPSG:4326")):
            self.assertTrue(option.hint, option.key)


class TestCrsTag(unittest.TestCase):
    """The tag lands in the downloaded filename, so it has to be stable,
    filesystem-safe, and empty for the native output."""

    def test_native_has_no_tag(self):
        self.assertEqual(output_crs.crs_tag(None), "")
        self.assertEqual(output_crs.crs_tag(""), "")

    def test_epsg_code_becomes_a_readable_tag(self):
        self.assertEqual(output_crs.crs_tag("EPSG:4326"), "epsg4326")

    def test_wkt_becomes_a_stable_hash(self):
        wkt = 'PROJCS["something long and full of []," "characters"]'
        first = output_crs.crs_tag(wkt)
        self.assertEqual(first, output_crs.crs_tag(wkt))
        self.assertTrue(first.isalnum())

    def test_different_definitions_get_different_tags(self):
        self.assertNotEqual(output_crs.crs_tag("EPSG:4326"), output_crs.crs_tag("EPSG:31983"))
        self.assertNotEqual(output_crs.crs_tag('PROJCS["a"]'), output_crs.crs_tag('PROJCS["b"]'))


class TestStoredOption(unittest.TestCase):
    def setUp(self):
        from bdc_loader_plugin.tests.qgis_mock import reset_state

        reset_state()

    def test_unset_settings_fall_back_to_the_smart_default(self):
        options = output_crs.build_options(_crs(authid="EPSG:4326"))

        option = output_crs.stored_option(options, crs=_crs(authid="EPSG:4326"))

        self.assertEqual(option.key, output_crs.WGS84)

    def test_stored_key_wins_over_the_default(self):
        options = output_crs.build_options(_crs(authid="EPSG:4326"))
        output_crs.save_option(options[0])

        option = output_crs.stored_option(options, crs=_crs(authid="EPSG:4326"))

        self.assertEqual(option.key, output_crs.NATIVE)

    def test_round_trip_through_settings(self):
        options = output_crs.build_options(_crs(authid="EPSG:31983"))
        output_crs.save_option(options[2])

        option = output_crs.stored_option(options, crs=_crs(authid="EPSG:31983"))

        self.assertEqual(option.key, output_crs.PROJECT)
        self.assertEqual(option.warp_srs, "EPSG:31983")

    def test_unknown_stored_key_falls_back_instead_of_failing(self):
        from qgis.core import QgsSettings

        QgsSettings().setValue(output_crs.OUTPUT_CRS_SETTING, "no-such-projection")
        options = output_crs.build_options(_crs(authid="EPSG:4326"))

        option = output_crs.stored_option(options, crs=_crs(authid="EPSG:4326"))

        self.assertEqual(option.key, output_crs.WGS84)

    def test_stored_project_choice_falls_back_when_the_project_has_no_crs(self):
        """A saved "project CRS" choice must not select a disabled option once
        the project it referred to is gone."""
        from qgis.core import QgsSettings

        QgsSettings().setValue(output_crs.OUTPUT_CRS_SETTING, output_crs.PROJECT)
        options = output_crs.build_options(None)

        option = output_crs.stored_option(options, crs=None)

        self.assertEqual(option.key, output_crs.NATIVE)
        self.assertTrue(option.enabled)


class TestCrsAccessorsAreDefensive(unittest.TestCase):
    """The download dialog must still open when a CRS object cannot answer."""

    def test_missing_accessor_degrades_to_empty(self):
        self.assertEqual(output_crs._crs_call(object(), "authid", "fallback"), "fallback")

    def test_raising_accessor_degrades_to_empty(self):
        class _Broken:
            def authid(self):
                raise RuntimeError("closed project")

        self.assertEqual(output_crs._crs_call(_Broken(), "authid", "fallback"), "fallback")

    def test_none_crs_is_handled(self):
        self.assertEqual(output_crs._crs_call(None, "authid", "fallback"), "fallback")
        self.assertIsNone(output_crs.warp_srs_for(None))
        self.assertFalse(output_crs.is_wgs84(None))
        self.assertFalse(output_crs.is_bdc_albers(None))

    def test_invalid_project_crs_reads_as_missing(self):
        invalid = QgsCoordinateReferenceSystem("")
        with patch("qgis.core.QgsProject.instance") as instance:
            instance.return_value.crs.return_value = invalid
            self.assertIsNone(output_crs.current_project_crs())


if __name__ == "__main__":
    unittest.main()
