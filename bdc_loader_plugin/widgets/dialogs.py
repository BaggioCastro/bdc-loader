"""
Dialogs

Reusable dialog windows for the BDC Loader Plugin.
Includes the Collection Filter Dialog, History Settings Dialog, the
Download Options Dialog (file format, output projection and folder) and the
Composition Dialog (bands and name of a user composition).

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from ..i18n import TRANSLATE_ITEMS, set_text
from .collection_badge import (
    BADGE_ROLE,
    GRID_BADGE_ROLE,
    TYPE_BADGE_ROLE,
    CollectionBadgeDelegate,
    badge_for_collection,
    grid_badge_for_collection,
    type_badge_for_collection,
)


class CollectionFilterDialog(QDialog):
    """
    A dialog window to check/uncheck visible STAC collections.

    Attributes:
        list_widget (QListWidget): The list widget holding collection items.
        _items (dict): A mapping of collection IDs to their corresponding list items.
    """

    def __init__(self, collections_dict, visible_ids, parent=None):
        """
        Initializes the dialog.

        Args:
            collections_dict (dict): Dictionary of available collections.
            visible_ids (set): Set of collection IDs that are currently visible.
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.setWindowTitle("Filter Collections")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)

        btn_row = QHBoxLayout()
        select_all = QPushButton("Select All")
        select_all.clicked.connect(lambda: self._set_all(True))
        deselect_all = QPushButton("Deselect All")
        deselect_all.clicked.connect(lambda: self._set_all(False))

        help_btn = QPushButton("?")
        help_btn.setFixedSize(24, 24)
        help_btn.setToolTip("What is this dialog and what do the badges mean?")
        help_btn.setStyleSheet(
            "QPushButton { font-weight: bold; border-radius: 12px; background-color: #2980b9; color: white; border: none; font-size: 13px; }"
            "QPushButton:hover { background-color: #3498db; }"
        )
        help_btn.clicked.connect(self._show_help_info)

        btn_row.addWidget(select_all)
        btn_row.addWidget(deselect_all)
        btn_row.addStretch()
        btn_row.addWidget(help_btn)
        layout.addLayout(btn_row)

        self.list_widget = QListWidget()
        self.list_widget.setItemDelegate(CollectionBadgeDelegate(self.list_widget))
        self._items = {}

        for name, config in sorted(collections_dict.items(), key=lambda entry: entry[0].casefold()):
            cid = config.get("id", name)
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if cid in visible_ids else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, cid)

            badge = badge_for_collection(config)
            if badge:
                item.setData(BADGE_ROLE, badge)

            t_badge = type_badge_for_collection(config)
            if t_badge:
                item.setData(TYPE_BADGE_ROLE, t_badge)

            g_badge = grid_badge_for_collection(config)
            if g_badge:
                item.setData(GRID_BADGE_ROLE, g_badge)

            self.list_widget.addItem(item)
            self._items[cid] = item

        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, checked: bool):
        """Checks or unchecks all list items."""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(state)

    def _show_help_info(self):
        """Displays help explanation for the collection filter dialog and badges."""
        msg = QMessageBox(self)
        msg.setWindowTitle("Filter Collections Help")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText("<b>Filter Collections & Badges Explanation</b>")
        msg.setInformativeText(
            "<p><b>What does this dialog do?</b><br/>"
            "This dialog allows you to customize which STAC collections appear in the main dropdown list. "
            "Uncheck any collection you do not use to simplify navigation.</p>"
            "<p><b>Collection Badges:</b></p>"
            "<ul>"
            "<li><b>[CUBE] / [MOSAIC] / [SCENE]:</b> Category type of the STAC dataset.</li>"
            "<li><span style='color: #1e8449;'><b>[COG]:</b></span> Cloud-Optimized GeoTIFF — streams fast over network via internal overviews.</li>"
            "<li><span style='color: #b9770e;'><b>[GEOTIFF]:</b></span> Standard GeoTIFF — does not have pyramids; best suited for local download.</li>"
            "<li><span style='color: #707b7c;'><b>[NO GRID]:</b></span> Collections without a fixed tile grid (e.g. Amazonia-1) — search via Extent (BBOX) or Shapefile.</li>"
            "</ul>"
        )
        msg.exec()

    def get_visible_ids(self) -> set:
        """
        Retrieves the IDs of the collections selected by the user.

        Returns:
            set: A set containing the selected collection IDs.
        """
        visible = set()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                visible.add(item.data(Qt.ItemDataRole.UserRole))
        return visible


class DownloadOptionsDialog(QDialog):
    """Confirmation dialog shown when a download starts.

    It asks how the files are delivered and in which projection:

    - one GeoTIFF per band (what analysis packages such as sits read), with an
      option to name the files the way sits parses a local cube;
    - one GeoTIFF per band plus a VRT that stacks them, so the bands open as a
      single layer without duplicating data;
    - one multiband GeoTIFF, for viewing or sending to someone.

    The projection radio buttons come from core.output_crs, which also decides
    which one starts selected; an option the current project cannot supply
    arrives disabled and is shown grayed out rather than hidden. With a single
    band the three formats write the same file, so only the first is offered.

    ``destination_for(option, fmt, sits, folder)`` returns the text of the
    destination line, which follows every change; ``folder`` is the download
    folder, which the user may change here.
    """

    _FORMAT_LABELS = (
        ("per_band", "One GeoTIFF per band", "Separate files, as analysis packages such as sits expect."),
        (
            "per_band_vrt",
            "One GeoTIFF per band + VRT",
            "Separate files plus a small VRT that opens them as one layer in QGIS.",
        ),
        ("multiband", "One multiband GeoTIFF", "A single file with every band, for viewing or sharing."),
    )

    def __init__(
        self,
        message,
        options,
        selected_key,
        destination_for=None,
        parent=None,
        selected_format="per_band",
        sits_names=False,
        band_count=3,
        folder=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Download")
        self.setMinimumWidth(480)

        self._options = list(options)
        self._destination_for = destination_for
        self._buttons = {}
        self._format_buttons = {}
        self._folder = folder

        layout = QVBoxLayout(self)

        header = QLabel(message)
        header.setWordWrap(True)
        layout.addWidget(header)

        # Built before the radio buttons: checking one emits toggled, whose
        # handler writes into this label.
        self.destination_label = QLabel("")
        self.destination_label.setWordWrap(True)
        self.destination_label.setStyleSheet("font-size: 9px; color: #666;")

        layout.addWidget(self._build_format_group(sits_names, band_count))
        if band_count < 2:
            selected_format = "per_band"
        layout.addWidget(self._build_crs_group())

        self._select_key(selected_key)
        self._select_format(selected_format)

        if folder is not None:
            layout.addLayout(self._build_folder_row())
            self._update_folder_label()

        layout.addWidget(self.destination_label)

        self.remember_check = QCheckBox("Don't ask me again")
        self.remember_check.setToolTip("Later downloads reuse these settings without asking.")
        layout.addWidget(self.remember_check)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_format_toggled()

    def _build_format_group(self, sits_names, band_count):
        """File layout radio buttons, with the sits naming option under per-band files.

        With one band every layout writes the same file, so only per-band stays enabled.
        """
        format_group = QGroupBox("Files")
        format_layout = QVBoxLayout(format_group)
        self._format_group = QButtonGroup(self)
        self.sits_check = QCheckBox("Name the files for the sits package")
        self.sits_check.setToolTip(
            "Files go to downloads/<collection>/sits/ named <collection>_<projection>_<tile>_<band>_<date>.tif, "
            "which sits_cube() reads as a local cube with its default parse_info."
        )
        self.sits_check.setChecked(bool(sits_names))
        for key, label, hint in self._FORMAT_LABELS:
            radio = QRadioButton(label)
            radio.setToolTip(hint)
            radio.toggled.connect(self._on_format_toggled)
            self._format_group.addButton(radio)
            format_layout.addWidget(radio)
            self._format_buttons[key] = radio
            if key == "per_band":
                sits_row = QHBoxLayout()
                sits_row.setContentsMargins(22, 0, 0, 0)
                sits_row.addWidget(self.sits_check)
                format_layout.addLayout(sits_row)
        if band_count < 2:
            for key in ("per_band_vrt", "multiband"):
                self._format_buttons[key].setEnabled(False)
                self._format_buttons[key].setToolTip("With one band every format writes the same single file.")
        self.sits_check.toggled.connect(self._update_destination_label)
        return format_group

    def _build_crs_group(self):
        """One radio button per output projection option."""
        crs_group = QGroupBox("Output projection")
        crs_layout = QVBoxLayout(crs_group)
        self._button_group = QButtonGroup(self)
        for option in self._options:
            radio = QRadioButton(option.label)
            radio.setEnabled(option.enabled)
            if option.hint:
                radio.setToolTip(option.hint)
            radio.toggled.connect(self._update_destination_label)
            self._button_group.addButton(radio)
            crs_layout.addWidget(radio)
            self._buttons[option.key] = radio
        return crs_group

    def _build_folder_row(self):
        """Download folder label with its Change folder button."""
        folder_row = QHBoxLayout()
        self.folder_label = QLabel("")
        self.folder_label.setWordWrap(True)
        folder_row.addWidget(self.folder_label, 1)
        change_btn = QPushButton("Change folder...")
        change_btn.clicked.connect(self._choose_folder)
        folder_row.addWidget(change_btn)
        return folder_row

    def _select_key(self, key):
        """Check the radio button for *key*, falling back to the first enabled
        option when that key is unavailable."""
        radio = self._buttons.get(key)
        if radio is not None and radio.isEnabled():
            radio.setChecked(True)
            return
        for option in self._options:
            if option.enabled:
                self._buttons[option.key].setChecked(True)
                return

    def _select_format(self, key):
        radio = self._format_buttons.get(key)
        if radio is None or not radio.isEnabled():
            radio = self._format_buttons["per_band"]
        radio.setChecked(True)

    def _on_format_toggled(self, *_args):
        self.sits_check.setEnabled(self.selected_format() == "per_band")
        self._update_destination_label()

    def _choose_folder(self):
        from qgis.PyQt.QtWidgets import QFileDialog

        chosen = QFileDialog.getExistingDirectory(self, "Choose download folder", self._folder or "")
        if chosen:
            self._folder = chosen
            self._update_folder_label()
            self._update_destination_label()

    def _update_folder_label(self):
        set_text(self.folder_label, f"Folder: {self._folder}")

    def _update_destination_label(self, *_args):
        """Show the files the current choices would write."""
        if not self._destination_for:
            return
        option = self.selected_option()
        if option is None:
            return
        self.destination_label.setText(
            self._destination_for(option, self.selected_format(), self.sits_names(), self._folder)
        )

    def selected_option(self):
        """Return the chosen OutputCrsOption, or None if nothing is checked."""
        for option in self._options:
            radio = self._buttons.get(option.key)
            if radio is not None and radio.isChecked():
                return option
        return None

    def selected_format(self):
        """ "per_band", "per_band_vrt" or "multiband"."""
        for key, radio in self._format_buttons.items():
            if radio.isChecked():
                return key
        return "per_band"

    def sits_names(self) -> bool:
        """True when per-band files should be named for the sits package."""
        return self.selected_format() == "per_band" and bool(self.sits_check.isChecked())

    def folder(self):
        """Download folder, possibly changed in this dialog."""
        return self._folder

    def remember_choice(self) -> bool:
        """True when later downloads should skip this dialog."""
        return bool(self.remember_check.isChecked())


class HistorySettingsDialog(QDialog):
    """
    Dialog for configuring the visual appearance of history points on the map.
    """

    def __init__(self, settings, parent=None):
        """
        Initializes the dialog.

        Args:
            settings (dict): The current settings dictionary.
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.setWindowTitle("History Map Settings")
        self.setMinimumWidth(320)
        self._settings = dict(settings)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._build_point_rows(form)
        layout.addLayout(form)
        self._build_vrt_group(layout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_point_rows(self, form):
        """Point size, color, color mode, map visibility and labels."""
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(1.0, 10.0)
        self.size_spin.setSingleStep(0.5)
        self.size_spin.setValue(self._settings.get("point_size", 2.8))
        self.size_spin.setDecimals(1)
        form.addRow("Point Size:", self.size_spin)

        # Point color
        self._point_color = QColor(self._settings.get("point_color", "#e74c3c"))
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(60, 22)
        self._update_color_btn()
        self.color_btn.clicked.connect(self._pick_color)
        form.addRow("Point Color:", self.color_btn)

        # Color mode
        self.color_mode_combo = QComboBox()
        self.color_mode_combo.addItem("Single Color", "single")
        self.color_mode_combo.addItem("Random Colors", "random")
        self.color_mode_combo.addItem("Classified (random per point)", "classified")
        self.color_mode_combo.setProperty(TRANSLATE_ITEMS, True)
        current_mode = self._settings.get("color_mode", "single")
        idx = self.color_mode_combo.findData(current_mode)
        if idx >= 0:
            self.color_mode_combo.setCurrentIndex(idx)
        form.addRow("Color Mode:", self.color_mode_combo)

        # Map visibility
        self.visible_check = QCheckBox("Show points on map")
        self.visible_check.setChecked(self._settings.get("visible", True))
        form.addRow(self.visible_check)

        # Map labels
        self.labels_check = QCheckBox("Show labels")
        self.labels_check.setChecked(self._settings.get("show_labels", False))
        form.addRow(self.labels_check)

    def _build_vrt_group(self, layout):
        """Bands of the image a chart click loads: RGB or a single band."""
        vrt_group = QGroupBox("VRT Composition (Chart Click)")
        vrt_lay = QFormLayout(vrt_group)

        self.vrt_mode_combo = QComboBox()
        self.vrt_mode_combo.addItem("RGB (3 bands)", "rgb")
        self.vrt_mode_combo.addItem("Single Band", "single")
        current_vrt_mode = self._settings.get("vrt_mode", "rgb")
        idx_vrt = self.vrt_mode_combo.findData(current_vrt_mode)
        if idx_vrt >= 0:
            self.vrt_mode_combo.setCurrentIndex(idx_vrt)
        vrt_lay.addRow("VRT Mode:", self.vrt_mode_combo)

        self.vrt_r_edit = QLineEdit(self._settings.get("vrt_r_band", ""))
        self.vrt_r_edit.setPlaceholderText("Ex: B04, red")
        vrt_lay.addRow("Band R:", self.vrt_r_edit)

        self.vrt_g_edit = QLineEdit(self._settings.get("vrt_g_band", ""))
        self.vrt_g_edit.setPlaceholderText("Ex: B03, green")
        vrt_lay.addRow("Band G:", self.vrt_g_edit)

        self.vrt_b_edit = QLineEdit(self._settings.get("vrt_b_band", ""))
        self.vrt_b_edit.setPlaceholderText("Ex: B02, blue")
        vrt_lay.addRow("Band B:", self.vrt_b_edit)

        self.vrt_single_edit = QLineEdit(self._settings.get("vrt_single_band", ""))
        self.vrt_single_edit.setPlaceholderText("Ex: NDVI, EVI, B08")
        vrt_lay.addRow("Single Band:", self.vrt_single_edit)

        note = QLabel("Leave empty to use chart bands (R/G/B combos)")
        note.setStyleSheet("font-size: 9px; color: #666; font-style: italic;")
        note.setWordWrap(True)
        vrt_lay.addRow(note)

        layout.addWidget(vrt_group)

    def _update_color_btn(self):
        """Updates the background color of the color picker button."""
        self.color_btn.setStyleSheet(
            f"background-color: {self._point_color.name()}; border: 1px solid #999; border-radius: 3px;"
        )

    def _pick_color(self):
        """Opens a QColorDialog for the user to select a color."""
        color = QColorDialog.getColor(self._point_color, self, "Point Color")
        if color.isValid():
            self._point_color = color
            self._update_color_btn()

    def get_settings(self) -> dict:
        """
        Retrieves the configured settings directly from the UI inputs.

        Returns:
            dict: The settings dictionary.
        """
        return {
            "point_size": self.size_spin.value(),
            "point_color": self._point_color.name(),
            "color_mode": self.color_mode_combo.currentData(),
            "visible": self.visible_check.isChecked(),
            "show_labels": self.labels_check.isChecked(),
            "vrt_mode": self.vrt_mode_combo.currentData(),
            "vrt_r_band": self.vrt_r_edit.text().strip(),
            "vrt_g_band": self.vrt_g_edit.text().strip(),
            "vrt_b_band": self.vrt_b_edit.text().strip(),
            "vrt_single_band": self.vrt_single_edit.text().strip(),
        }


def composition_problem(name, bands, built_in_names):
    """Return why a composition cannot be saved, or "" when it can.

    ``bands`` holds one band (single band) or three bands (red, green, blue).
    Names are compared without case, so "true color" cannot shadow "True Color".
    """
    name = (name or "").strip()
    if not name:
        return "Enter a name for the composition."
    if name.startswith("--"):
        return 'A name cannot start with "--".'
    if name.casefold() in {str(n).casefold() for n in built_in_names}:
        return f'"{name}" is a built-in composition. Choose another name.'
    if len(bands) not in (1, 3) or not all(bands):
        return "Choose a band for every channel."
    if len(bands) == 3 and len(set(bands)) != 3:
        return "Red, green and blue must be three different bands."
    return ""


def saved_name_match(name, saved):
    """Return the saved composition name equal to ``name`` ignoring case, or None."""
    key = (name or "").strip().casefold()
    return next((saved_name for saved_name in saved if saved_name.casefold() == key), None)


class CompositionDialog(QDialog):
    """Create a user composition from the bands the collection offers.

    Bands are chosen from lists filled with the available bands, so a
    composition can only name bands that exist. The name is checked while it
    is typed; Save stays disabled until the composition is valid, and the
    message line says when an existing composition of the user is replaced.
    """

    _ERROR_COLOR = "#c62828"
    _WARNING_COLOR = "#a15c00"

    def __init__(self, bands, built_in, saved, initial=None, collection_label="", parent=None):
        """
        Args:
            bands (list): (band id, label) pairs of the available bands.
            built_in (dict): built-in compositions, {name: [bands]}; their names cannot be taken.
            saved (dict): the user's compositions for this collection, {name: [bands]}.
            initial (list, optional): bands to start with (1 or 3).
            collection_label (str, optional): collection shown in the header.
        """
        super().__init__(parent)
        self.setWindowTitle("New composition")
        self.setMinimumWidth(380)
        self._built_in = dict(built_in)
        self._saved = dict(saved)
        self._name_edited = False

        layout = QVBoxLayout(self)
        if collection_label:
            header = QLabel(f"Collection: <b>{collection_label}</b>")
            header.setWordWrap(True)
            layout.addWidget(header)

        mode_box = QGroupBox("Type")
        mode_layout = QHBoxLayout(mode_box)
        self.rgb_radio = QRadioButton("RGB (3 bands)")
        self.single_radio = QRadioButton("Single band")
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.rgb_radio)
        self._mode_group.addButton(self.single_radio)
        mode_layout.addWidget(self.rgb_radio)
        mode_layout.addWidget(self.single_radio)
        mode_layout.addStretch()
        layout.addWidget(mode_box)

        form = QFormLayout()
        self._channel_labels = []
        self.channel_combos = []
        for channel in ("Red:", "Green:", "Blue:"):
            combo = QComboBox()
            for band, label in bands:
                combo.addItem(label, band)
            combo.currentIndexChanged.connect(self._refresh)
            label_widget = QLabel(channel)
            form.addRow(label_widget, combo)
            self._channel_labels.append(label_widget)
            self.channel_combos.append(combo)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Composition name")
        self.name_edit.textEdited.connect(self._on_name_edited)
        self.name_edit.textChanged.connect(self._refresh)
        form.addRow("Name:", self.name_edit)
        layout.addLayout(form)

        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        self.message_label.setMinimumHeight(self.message_label.fontMetrics().lineSpacing() * 2)
        layout.addWidget(self.message_label)
        layout.addStretch()

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        initial = [band for band in (initial or []) if self._index_of(band) >= 0]
        if len(initial) == 1:
            self.single_radio.setChecked(True)
            self._select(0, initial[0])
        else:
            self.rgb_radio.setChecked(True)
            for channel, band in enumerate(initial[:3] if len(initial) == 3 else self._default_rgb(bands)):
                self._select(channel, band)
        self.rgb_radio.toggled.connect(self._refresh)
        self._refresh()

    @staticmethod
    def _default_rgb(bands):
        """Pick the bands named red, green and blue, else the first three."""
        by_common = {}
        for band, label in bands:
            common = label[label.find("(") + 1 : -1].casefold() if label.endswith(")") else band.casefold()
            by_common.setdefault(common, band)
        if all(c in by_common for c in ("red", "green", "blue")):
            return [by_common["red"], by_common["green"], by_common["blue"]]
        return [band for band, _ in bands[:3]]

    def _index_of(self, band):
        return self.channel_combos[0].findData(band)

    def _select(self, channel, band):
        idx = self.channel_combos[channel].findData(band)
        if idx >= 0:
            self.channel_combos[channel].setCurrentIndex(idx)

    def _on_name_edited(self, _text):
        self._name_edited = True

    def bands(self):
        """Bands of the composition: [band] or [red, green, blue]."""
        count = 3 if self.rgb_radio.isChecked() else 1
        return [self.channel_combos[i].currentData() for i in range(count)]

    def name(self):
        """Name typed by the user, without surrounding spaces."""
        return self.name_edit.text().strip()

    def replaced_name(self):
        """Saved composition this one replaces (same name ignoring case), or None."""
        return saved_name_match(self.name(), self._saved)

    def _refresh(self, *_args):
        rgb = self.rgb_radio.isChecked()
        self._channel_labels[0].setText("Red:" if rgb else "Band:")
        for i in (1, 2):
            self._channel_labels[i].setVisible(rgb)
            self.channel_combos[i].setVisible(rgb)

        bands = self.bands()
        if not self._name_edited:
            self.name_edit.blockSignals(True)
            set_text(self.name_edit, f"Custom ({','.join(b for b in bands if b)})")
            self.name_edit.blockSignals(False)

        problem = composition_problem(self.name(), bands, self._built_in)
        replaced = None if problem else self.replaced_name()
        if problem:
            self._show_message(problem, self._ERROR_COLOR)
        elif replaced:
            self._show_message(
                f'Replaces your composition "{replaced}" ({", ".join(self._saved[replaced])}).', self._WARNING_COLOR
            )
        elif self._same_bands(bands):
            self._show_message(f'Same bands as "{self._same_bands(bands)}".', self._WARNING_COLOR)
        else:
            self._show_message(f"Bands: {', '.join(bands)}", "")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(not problem)

    def _same_bands(self, bands):
        """Name of an existing composition with exactly these bands, or ""."""
        for name, values in {**self._built_in, **self._saved}.items():
            if list(values) == list(bands):
                return name
        return ""

    def _show_message(self, text, color):
        self.message_label.setText(text)
        self.message_label.setStyleSheet(f"color: {color};" if color else "")
