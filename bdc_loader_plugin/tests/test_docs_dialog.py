"""Tests for the documentation dialog link hierarchy and header affordances."""

from bdc_loader_plugin.ui.docs_dialog import BDC_DATA_CUBES_URL, BDC_EXPLORER_URL, INPE_DATA_URL, _build_html
from bdc_loader_plugin.ui.main_styles import _BDC_PROJ_BUTTON_STYLE, _DOCS_BUTTON_STYLE


def test_docs_dialog_prioritizes_official_inpe_data_portals():
    """The two official INPE data pages must lead the documentation content."""
    html = _build_html()

    general_data_position = html.index(INPE_DATA_URL)
    data_cubes_position = html.index(BDC_DATA_CUBES_URL)
    technical_reference_position = html.index("Optional Technical References")

    assert general_data_position < technical_reference_position
    assert data_cubes_position < technical_reference_position
    assert "Explore INPE Geospatial Data" in html
    assert "Brazil Data Cube Products" in html


def test_docs_dialog_uses_current_bdc_explorer_and_keeps_optional_references():
    """Direct access must use the current INPE Explorer while retaining legacy guides."""
    html = _build_html()

    assert BDC_EXPLORER_URL in html
    assert "http://brazildatacube.dpi.inpe.br/portal/explore" not in html
    assert "Optional API Guides &amp; Notebooks" in html
    assert "https://brazil-data-cube.github.io/specifications/bdc-grid.html" in html


def test_header_docs_and_projection_buttons_have_hover_feedback():
    """Header actions must visibly react to pointer hover and press."""
    assert "QPushButton:hover" in _DOCS_BUTTON_STYLE
    assert "#8e44ad" in _DOCS_BUTTON_STYLE
    assert "QPushButton:pressed" in _DOCS_BUTTON_STYLE

    assert "QPushButton:hover" in _BDC_PROJ_BUTTON_STYLE
    assert "#43a047" in _BDC_PROJ_BUTTON_STYLE
    assert "QPushButton:pressed" in _BDC_PROJ_BUTTON_STYLE
