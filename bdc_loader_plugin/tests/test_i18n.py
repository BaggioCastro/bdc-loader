"""Interface language: the Portuguese table, the run-time patterns and the text swap on widgets."""

import re
import unittest
from unittest.mock import MagicMock

from bdc_loader_plugin import i18n
from bdc_loader_plugin.i18n_pt import TEXTS


class TestTranslate(unittest.TestCase):
    def test_english_passes_through_and_unknown_text_is_kept(self):
        self.assertEqual(i18n.tr("Search STAC", "en"), "Search STAC")
        self.assertEqual(i18n.tr("Search STAC", "pt"), "Buscar STAC")
        self.assertEqual(i18n.tr("S2-16D_V2_031020_20220914", "pt"), "S2-16D_V2_031020_20220914")
        self.assertEqual(i18n.tr("", "pt"), "")

    def test_run_time_texts_keep_their_numbers_and_names(self):
        cases = {
            "Period: 60 days (01/08/2022 / 30/09/2022)": "Período: 60 dias (01/08/2022 / 30/09/2022)",
            "5 layers added to the map, turned off (0.1 s, ~0.0 s per layer). 5 streamed from the BDC.": (
                "5 camadas adicionadas ao mapa, desligadas (0.1 s, ~0.0 s por camada). 5 lidas do BDC."
            ),
            "That is tile 030020. Click \u2715 to clear it, then select the amber one.": (
                "Esse é o tile 030020. Clique em \u2715 para limpar e selecione o tile âmbar."
            ),
            "Using Extent. To use Tiles or Vector File, close it or clear it (\u2715) first.": (
                "Usando Extensão. Para usar Tiles ou Arquivo vetorial, feche ou limpe (\u2715) antes."
            ),
            "Grid BDC_SM_V2 added to the map. Draw on Canvas is ready.": (
                "Grade BDC_SM_V2 adicionada ao mapa. Desenhar no mapa está pronto."
            ),
        }
        for english, portuguese in cases.items():
            self.assertEqual(i18n.tr(english, "pt"), portuguese)

    def test_layer_loading_steps_are_named_in_portuguese(self):
        cases = {
            "Reading image headers from the BDC: 12 s": "Lendo os cabeçalhos das imagens no BDC: 12 s",
            "Preparing layers for display (overview and contrast): 7/24 (5 s)": (
                "Preparando as camadas para exibição (overview e contraste): 7/24 (5 s)"
            ),
            "Preparing layers for display (overview and contrast): 7/24 (15 s), waiting for the BDC server": (
                "Preparando as camadas para exibição (overview e contraste): 7/24 (15 s), aguardando o servidor do BDC"
            ),
            "Preparing layers for display (contrast): 3/24 (2 s)": (
                "Preparando as camadas para exibição (contraste): 3/24 (2 s)"
            ),
            "Preparing layer %v/%m": "Preparando camada %v/%m",
            "Preparing for display %v/%m": "Preparando para exibição %v/%m",
            "Adding layer %v/%m": "Adicionando camada %v/%m",
            "Preparing layers: 3/24 (5 s, ~1.7 s per layer, ~35 s left)": (
                "Preparando as camadas: 3/24 (5 s, ~1.7 s por camada, faltam ~35 s)"
            ),
            "Preparing 1 crop (1 in parallel)...": "Preparando 1 recorte (1 em paralelo)...",
            "Preparing 24 layers (8 in parallel)...": "Preparando 24 camadas (8 em paralelo)...",
            "Adding 1 layer to the map...": "Adicionando 1 camada ao mapa...",
            "24 layers added to the map (11.6 s, ~0.5 s per layer).": (
                "24 camadas adicionadas ao mapa (11.6 s, ~0.5 s por camada)."
            ),
            "1 layer added to the map (2.0 s, ~2.0 s per layer). 1 from your downloads, 1 error.": (
                "1 camada adicionada ao mapa (2.0 s, ~2.0 s por camada). 1 dos seus downloads, 1 erro."
            ),
            "Loading cancelled: 5 layers added to the map (3.1 s, ~12.0 s per layer, slow server).": (
                "Carregamento cancelado: 5 camadas adicionadas ao mapa (3.1 s, ~12.0 s por camada, servidor lento)."
            ),
            "Loading cancelled: 5 of 24 layers ready (3.1 s). Adding them to the map...": (
                "Carregamento cancelado: 5 de 24 camadas prontas (3.1 s). Adicionando-as ao mapa..."
            ),
            "Loading layers failed: no layer was added to the map.": (
                "Falha no carregamento das camadas: nenhuma camada foi adicionada ao mapa."
            ),
            "1 of 2 layers has no valid pixel in this area (the image covers it only with its empty border, or the "
            "area has no data): A.": (
                "1 de 2 camadas não tem pixel válido nesta área (a imagem a cobre só com a borda vazia, ou a área não "
                "tem dado): A."
            ),
        }
        for english, portuguese in cases.items():
            self.assertEqual(i18n.tr(english, "pt"), portuguese)

    def test_process_messages_are_translated_in_the_singular_and_the_plural(self):
        cases = {
            # Search
            "Searching images (STAC)...": "Buscando imagens (STAC)...",
            "Searching images (STAC): 1 found": "Buscando imagens (STAC): 1 encontrada",
            "1 image found.": "1 imagem encontrada.",
            "24 images found.": "24 imagens encontradas.",
            "Listing 3 dates of 1 scene...": "Listando 3 datas de 1 cena...",
            "40 scenes grouped into 1 date.": "40 cenas agrupadas em 1 data.",
            "Search failed: timed out.": "Falha na busca: timed out.",
            "No images found. 1 scene covers the box around the vector features, but none crosses the checked "
            "features.": (
                "Nenhuma imagem encontrada. 1 cena cobre o retângulo em volta das feições, mas nenhuma cruza as feições "
                "marcadas."
            ),
            # Download
            "Estimating the size of 1 file...": "Estimando o tamanho de 1 arquivo...",
            "[2/5] Preparing to download 3 bands of S2_X...": "[2/5] Preparando o download de 3 bandas de S2_X...",
            "[2/5] Downloading 1 band of S2_X: 12.3 MB of 40.1 MB (5.2 MB/s, 1 file at a time)": (
                "[2/5] Baixando 1 banda de S2_X: 12.3 MB de 40.1 MB (5.2 MB/s, 1 arquivo ao mesmo tempo)"
            ),
            "Downloading the tiles of S2_X: 4.0 MB (2.0 MB/s, 6 files at a time)": (
                "Baixando os tiles de S2_X: 4.0 MB (2.0 MB/s, 6 arquivos ao mesmo tempo)"
            ),
            "[1/2] Downloading the area blocks of S2_X: 3.0 MB (1.5 MB/s)": (
                "[1/2] Baixando os blocos da área de S2_X: 3.0 MB (1.5 MB/s)"
            ),
            "Writing S2_X: 4 s": "Gravando S2_X: 4 s",
            "Download complete: /data/S2_X.": "Download concluído: /data/S2_X.",
            "Download failed: S2_X.": "Falha no download: S2_X.",
            "1 image downloaded, 1 already on disk, 2 failed.": "1 imagem baixada, 1 já no disco, 2 com falha.",
            "Download cancelled: 2 of 6 images processed, 2 images downloaded.": (
                "Download cancelado: 2 de 6 imagens processadas, 2 imagens baixadas."
            ),
            # Grid
            "Downloading grid BDC_SM_V2: 1.2 MB of 3.4 MB": "Baixando a grade BDC_SM_V2: 1.2 MB de 3.4 MB",
            "Grid download failed: HTTP 500.": "Falha no download da grade: HTTP 500.",
            "1 tile copied to the clipboard.": "1 tile copiado.",
            "3 tiles copied to the clipboard.": "3 tiles copiados.",
            # Time series
            "Searching images for 1 point (STAC)...": "Buscando imagens de 1 ponto (STAC)...",
            "Extracting time series (STAC): 4/10 files of 1 image, 2 points": (
                "Extraindo a série temporal (STAC): 4/10 arquivos de 1 imagem, 2 pontos"
            ),
            "Extracting time series (WTSS): 3/10": "Extraindo a série temporal (WTSS): 3/10",
            "Extracting time series (1 point already extracted, 2 points with new bands)...": (
                "Extraindo a série temporal (1 ponto já extraído, 2 pontos com bandas novas)..."
            ),
            "120 values extracted: 1 new point, 2 updated.": "120 valores extraídos: 1 ponto novo, 2 atualizados.",
            "1 value extracted: 2 new points. 1 pixel read failed after a retry; the series has gaps.": (
                "1 valor extraído: 2 pontos novos. 1 leitura de pixel falhou após nova tentativa; a série tem falhas."
            ),
            "Time series extraction failed: timeout.": "Falha na extração da série temporal: timeout.",
            "Time series extraction cancelled.": "Extração da série temporal cancelada.",
            "2 bands extracted, 1 band without data: red.": "2 bandas extraídas, 1 banda sem dados: red.",
            "1 point to extract.": "1 ponto a extrair.",
            "3 points loaded from pts.gpkg.": "3 pontos carregados de pts.gpkg.",
            "Point #3 removed; the history has 1 point.": "Ponto #3 removido; o histórico tem 1 ponto.",
            "1 collection loaded.": "1 coleção carregada.",
            # Chart image
            "Opening the image of 2024-01-01...": "Abrindo a imagem de 2024-01-01...",
            "Opening the image of 2024-01-01 failed: S2_X could not be built.": (
                "Falha ao abrir a imagem de 2024-01-01: não foi possível montar S2_X."
            ),
            "Layer S2_X added to the map.": "Camada S2_X adicionada ao mapa.",
            "1 feature exported to GeoPackage.": "1 feição exportada para GeoPackage.",
        }
        for english, portuguese in cases.items():
            self.assertEqual(i18n.tr(english, "pt"), portuguese)

    def test_both_lists_each_language_once(self):
        self.assertEqual(i18n.both("Clear"), ["Clear", "Limpar"])
        self.assertEqual(i18n.both("BDC_SM_V2"), ["BDC_SM_V2"])


class _Widget:
    """Just what the text swap reads and writes."""

    def __init__(self, text):
        self._text, self._props = text, {}

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text

    def property(self, name):
        return self._props.get(name)

    def setProperty(self, name, value):
        self._props[name] = value


class TestSwap(unittest.TestCase):
    def test_switching_back_and_forth_never_translates_a_translation(self):
        widget = _Widget("Load layers")
        for lang, shown in (("pt", "Carregar camadas"), ("pt", "Carregar camadas"), ("en", "Load layers")):
            i18n._swap(widget, "text", widget.text, widget.setText, lang)
            self.assertEqual(widget.text(), shown)

    def test_a_text_the_code_sets_later_becomes_the_english_one(self):
        widget = _Widget("Load layers")
        i18n._swap(widget, "text", widget.text, widget.setText, "pt")
        widget.setText("Clear")
        i18n._swap(widget, "text", widget.text, widget.setText, "pt")
        self.assertEqual(widget.text(), "Limpar")
        i18n._swap(widget, "text", widget.text, widget.setText, "en")
        self.assertEqual(widget.text(), "Clear")


class TestTextsSetLater(unittest.TestCase):
    def test_set_text_shows_the_translation_and_switches_back(self):
        from unittest.mock import patch

        widget = _Widget("")
        with patch.object(i18n, "language", return_value="pt"):
            i18n.set_text(widget, "History cleared.")
        self.assertEqual(widget.text(), "Histórico limpo.")
        i18n._swap(widget, "text", widget.text, widget.setText, "en")
        self.assertEqual(widget.text(), "History cleared.")

    def test_an_offline_status_is_translated_after_its_prefix(self):
        self.assertEqual(
            i18n.tr(i18n.OFFLINE_PREFIX + "Settings saved.", "pt"), i18n.OFFLINE_PREFIX + "Configurações salvas."
        )


class _Combo:
    """Just what the combo item swap reads and writes."""

    def __init__(self, texts):
        self._items = [{"text": t} for t in texts]
        self._index = 0

    def count(self):
        return len(self._items)

    def itemText(self, i):
        return self._items[i]["text"]

    def setItemText(self, i, text):
        self._items[i]["text"] = text

    def itemData(self, i, role):
        return self._items[i].get(role)

    def setItemData(self, i, value, role):
        self._items[i][role] = value

    def currentIndex(self):
        return self._index

    def currentText(self):
        return self._items[self._index]["text"]


class TestComboItems(unittest.TestCase):
    def test_items_switch_and_the_code_still_reads_english(self):
        combo = _Combo(["All types", ".vrt only"])
        combo._index = 1
        i18n._swap_combo_items(combo, "pt")
        self.assertEqual(combo.currentText(), "Só .vrt")
        self.assertEqual(i18n.english_text(combo), ".vrt only")
        i18n._swap_combo_items(combo, "en")
        self.assertEqual(combo.currentText(), ".vrt only")


class _Item:
    """Just what the list item swap reads and writes."""

    def __init__(self, text):
        self._text, self._data = text, {}

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text

    def data(self, role):
        return self._data.get(role)

    def setData(self, role, value):
        self._data[role] = value


class TestBandsAndLists(unittest.TestCase):
    def test_band_common_names_are_translated_and_codes_kept(self):
        self.assertEqual(i18n.tr("B02 (blue)", "pt"), "B02 (azul)")
        self.assertEqual(i18n.tr("BAND3 (red)", "pt"), "BAND3 (vermelho)")
        self.assertEqual(i18n.tr("B08 (nir)", "pt"), "B08 (nir)")
        self.assertEqual(i18n.tr("-- Select --", "pt"), "-- Selecione --")

    def test_list_items_switch_back_and_forth(self):
        item = _Item("B04 (red)")
        for lang, shown in (("pt", "B04 (vermelho)"), ("pt", "B04 (vermelho)"), ("en", "B04 (red)")):
            i18n._swap_item(item, lang)
            self.assertEqual(item.text(), shown)


class TestCoverage(unittest.TestCase):
    # Names that read the same in both languages.
    SAME = {"STAC Browser", "BDC Explorer", "Download", "Downloads", "Overviews", "Tiles", "WGS 84 (EPSG:4326)"}

    def test_every_literal_text_passed_to_tr_has_a_portuguese_version(self):
        import ast
        import os

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        missing = []
        for folder, _dirs, files in os.walk(root):
            if any(part in folder for part in ("tests", "lib", "__pycache__")):
                continue
            for name in files:
                if not name.endswith(".py") or name.startswith("i18n"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "tr" and node.args:
                        arg = node.args[0]
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            text = arg.value
                            if text not in self.SAME and i18n.tr(text, "pt") == text:
                                missing.append(f"{name}: {text[:60]}")
        self.assertEqual(missing, [])


class TestTourInPortuguese(unittest.TestCase):
    def setUp(self):
        from bdc_loader_plugin.ui import tour_steps

        self.ts = tour_steps
        self.steps = tour_steps.main_tour_steps(MagicMock(), MagicMock())

    def _texts(self, draw_button="Draw on Canvas"):
        # The Draw on Canvas button is named as the interface shows it.
        texts = [self.ts.GRID_OFFER_TEXT, self.ts.GRID_READY_TEXT, self.ts.DRAW_TEXT.format(draw_button)]
        for step in self.steps:
            texts += [step.section, step.title, step.map_body]
            if not callable(step.body):
                texts.append(step.body)
        return [t for t in texts if t]

    def test_every_tour_text_has_a_portuguese_version(self):
        for text in self._texts():
            self.assertTrue(text in TEXTS or i18n.tr(text, "pt") != text, text)

    def test_buttons_named_in_portuguese_are_the_ones_the_interface_shows(self):
        names = {value.strip().rstrip(":") for value in TEXTS.values()}
        kept = {"Sentinel-2 Cube 16D (S2-16D-2)", "BDC_SM_V2", "False Color (8,4,3)", "Tutorial circle", "RGB", "Multi"}
        for text in self._texts(i18n.tr("Draw on Canvas", "pt")):
            for name in re.findall(r"<b>(.+?)</b>", i18n.tr(text, "pt")):
                if name in kept or re.fullmatch(r"[\d/]+|&lt;|&gt;", name):
                    continue
                self.assertIn(name, names, f"{name!r} in {text!r}")


class TestDialogLanguage(unittest.TestCase):
    def test_the_language_applies_while_the_dialog_is_built_before_it_has_a_tour(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from bdc_loader_plugin.ui import main_dialog

        building = SimpleNamespace(_ts_panel=None, _timeline_toolbar=None, language_buttons={})
        with patch.object(main_dialog, "translate_tree") as translate:
            main_dialog.BDCLoaderDialog._apply_language(building)
        translate.assert_any_call(building, i18n.language())


if __name__ == "__main__":
    unittest.main()


def test_the_chart_overlay_shows_in_the_interface_language():
    from types import SimpleNamespace
    from unittest.mock import patch

    from bdc_loader_plugin.chart.dock import ChartDock

    overlay = _Widget("")
    overlay.setVisible = overlay.raise_ = lambda *a: None
    dock = SimpleNamespace(_loading_overlay=overlay, canvas_plot=None)
    with patch.object(i18n, "language", return_value="pt"):
        ChartDock.show_loading_overlay(dock, "Extracting RGB bands...")
        assert overlay.text() == "Extraindo as bandas RGB..."
        ChartDock.show_loading_overlay(dock, "Extracting time series...")
        assert overlay.text() == "Extraindo a série temporal..."
