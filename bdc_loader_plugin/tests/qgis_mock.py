"""
QGIS Mock Environment

Provides mock objects for all QGIS, PyQt5, osgeo (GDAL), and matplotlib
dependencies so that the plugin test suite can run without a real QGIS
installation.

Usage:
    Import this module BEFORE importing any plugin code:
        from bdc_loader_plugin.tests.qgis_mock import install_mocks
        install_mocks()
"""

import os
import sys
import tempfile
import threading
import types
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helper: create a fake module and register it in sys.modules
# ---------------------------------------------------------------------------
class _ScopedEnumMeta(type):
    """Resolve scoped enum access (``Qt.ItemDataRole.UserRole``) to the flat value (``Qt.UserRole``)."""

    def __getattr__(cls, name):
        if name[:1].isupper():
            return cls
        raise AttributeError(name)


def _make_module(name, attrs=None):
    mod = types.ModuleType(name)
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# ---------------------------------------------------------------------------
# PyQt5 mocks
# ---------------------------------------------------------------------------
def _install_pyqt5():
    """Install comprehensive PyQt5 mock modules."""

    # --- QtCore ---
    class _Qt(metaclass=_ScopedEnumMeta):
        AlignCenter = 0x0004
        AlignLeft = 0x0001
        AlignRight = 0x0002
        AlignTop = 0x0020
        AlignBottom = 0x0040
        AlignVCenter = 0x0080
        Horizontal = 0x1
        Vertical = 0x2
        ArrowCursor = 0
        CrossCursor = 2
        WaitCursor = 3
        ClosedHandCursor = 8
        OpenHandCursor = 9
        PointingHandCursor = 13
        NoPen = 0
        LeftDockWidgetArea = 0x1
        RightDockWidgetArea = 0x2
        BottomDockWidgetArea = 0x8
        TopDockWidgetArea = 0x4
        TopToolBarArea = 0x4
        Checked = 2
        Unchecked = 0
        ApplicationShortcut = 0
        WindowShortcut = 1
        UserRole = 0x0100
        ItemIsSelectable = 0x0001
        ItemIsEnabled = 0x0020
        Key_Escape = 0x01000000
        LeftButton = 0x0001
        OtherFocusReason = 7
        transparent = 0  # Qt.GlobalColor

    class _QDate:
        def __init__(self, y=2000, m=1, d=1):
            self._y, self._m, self._d = y, m, d

        def year(self):
            return self._y

        def month(self):
            return self._m

        def day(self):
            return self._d

        @classmethod
        def currentDate(cls):
            import datetime

            today = datetime.date.today()
            return cls(today.year, today.month, today.day)

        def daysTo(self, other):
            import datetime

            d1 = datetime.date(self._y, self._m, self._d)
            d2 = datetime.date(other._y, other._m, other._d)
            return (d2 - d1).days

        def addDays(self, n):
            import datetime

            d = datetime.date(self._y, self._m, self._d) + datetime.timedelta(days=n)
            return _QDate(d.year, d.month, d.day)

        def toString(self, fmt=""):
            return f"{self._d:02d}/{self._m:02d}/{self._y}"

    class _QVariant(metaclass=_ScopedEnumMeta):
        Int = 2
        Double = 6
        String = 10
        Bool = 1

    def _pyqtSignal(*args, **kwargs):
        """Return a mock signal descriptor."""
        return MagicMock()

    qtcore = _make_module(
        "PyQt5.QtCore",
        {
            "Qt": _Qt,
            "QDate": _QDate,
            "QVariant": _QVariant,
            "pyqtSignal": _pyqtSignal,
            "QCoreApplication": MagicMock(),
            "QTimer": MagicMock(),
            "QEvent": MagicMock(),
            "QThread": MagicMock(),
            "QObject": MagicMock(),
            "QSize": MagicMock(),
            "QPoint": MagicMock(),
            "QPointF": MagicMock(),
            "QRect": MagicMock(),
            "QRectF": MagicMock(),
            "QUrl": MagicMock(),
        },
    )

    # --- QtGui ---
    qtgui = _make_module(
        "PyQt5.QtGui",
        {
            "QPainter": MagicMock(),
            "QBrush": MagicMock(),
            "QColor": MagicMock(),
            "QPen": MagicMock(),
            "QFont": MagicMock(),
            "QFontMetrics": MagicMock(),
            "QPixmap": MagicMock(),
            "QIcon": MagicMock(),
            "QImage": MagicMock(),
            "QCursor": MagicMock(),
            "QKeySequence": MagicMock(),
            "QDesktopServices": MagicMock(),
            "QLinearGradient": MagicMock(),
            "QPolygonF": MagicMock(),
            "QPainterPath": MagicMock(),
            "QRegion": MagicMock(),
        },
    )

    # --- QtNetwork ---
    _make_module(
        "PyQt5.QtNetwork",
        {
            "QNetworkAccessManager": MagicMock(),
            "QNetworkRequest": MagicMock(),
            "QNetworkReply": MagicMock(),
        },
    )

    # --- QtWidgets ---
    class _FakeWidget(metaclass=_ScopedEnumMeta):
        def __init__(self, *a, **kw):
            pass

        def setLayout(self, *a):
            pass

        def show(self, *a):
            pass

        def close(self, *a):
            pass

        def raise_(self, *a):
            pass

        def activateWindow(self, *a):
            pass

        def setStyleSheet(self, *a):
            pass

        def setFixedHeight(self, *a):
            pass

        def setFixedWidth(self, *a):
            pass

        def setMinimumSize(self, *a):
            pass

        def setMinimumWidth(self, *a):
            pass

        def setMinimumHeight(self, *a):
            pass

        def setMaximumHeight(self, *a):
            pass

        def setSizePolicy(self, *a):
            pass

        def setCursor(self, *a):
            pass

        def findChildren(self, *a):
            return []

        def installEventFilter(self, *a):
            pass

        def setToolTip(self, *a):
            pass

        def setMouseTracking(self, *a):
            pass

        def update(self, *a):
            pass

        def width(self):
            return 400

        def height(self):
            return 300

        def setWindowTitle(self, *a):
            pass

        def setAlignment(self, *a):
            pass

        def setText(self, *a):
            pass

        def setObjectName(self, *a):
            pass

        def setMovable(self, *a):
            pass

        def setFloatable(self, *a):
            pass

        def setVisible(self, *a):
            pass

        def addWidget(self, *a):
            pass

        def addSeparator(self, *a):
            pass

        def addAction(self, *a):
            pass

        def deleteLater(self, *a):
            pass

    class _FakeSlider(_FakeWidget):
        TicksBelow = 1

        def __init__(self, orientation=1, *a, **kw):
            super().__init__(*a, **kw)
            self._orientation = orientation
            self._minimum = 0
            self._maximum = 99
            self._value = 0
            self._inverted = False
            self.valueChanged = MagicMock()

        def setRange(self, minimum, maximum):
            self._minimum = minimum
            self._maximum = maximum

        def minimum(self):
            return self._minimum

        def maximum(self):
            return self._maximum

        def setValue(self, value):
            self._value = value
            self.valueChanged.emit(value)

        def value(self):
            return self._value

        def orientation(self):
            return self._orientation

        def invertedAppearance(self):
            return self._inverted

        def mousePressEvent(self, event):
            pass

        def mouseMoveEvent(self, event):
            pass

        def mouseReleaseEvent(self, event):
            pass

        def __getattr__(self, _name):
            return MagicMock()

    class _FakeDialog(_FakeWidget):
        Accepted = 1
        Rejected = 0

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._result = _FakeDialog.Rejected

        def accept(self):
            self.done(_FakeDialog.Accepted)

        def reject(self):
            self.done(_FakeDialog.Rejected)

        def done(self, result):
            self._result = result

        def result(self):
            return self._result

        def exec(self):
            return self._result

        def exec_(self):
            return self._result

    class _FakeItemDelegate(metaclass=_ScopedEnumMeta):
        """Subclassable stand-in: CollectionBadgeDelegate derives from it, so a
        MagicMock (not a class) would not do."""

        def __init__(self, *a, **kw):
            pass

        def paint(self, *a, **kw):
            pass

        def sizeHint(self, *a, **kw):
            return MagicMock()

        def initStyleOption(self, *a, **kw):
            pass

    qtwidgets = _make_module(
        "PyQt5.QtWidgets",
        {
            "QWidget": _FakeWidget,
            "QDialog": _FakeDialog,
            "QStyledItemDelegate": _FakeItemDelegate,
            "QStyleOptionViewItem": MagicMock(),
            "QStyle": MagicMock(),
            "QStyleOptionSlider": MagicMock,
            "QDockWidget": _FakeWidget,
            "QMainWindow": _FakeWidget,
            "QVBoxLayout": MagicMock(),
            "QHBoxLayout": MagicMock(),
            "QFormLayout": MagicMock(),
            "QLabel": MagicMock(),
            "QPushButton": MagicMock(),
            "QAbstractButton": MagicMock(),
            "QAbstractSpinBox": MagicMock(),
            "QLineEdit": MagicMock(),
            "QComboBox": MagicMock(),
            "QListWidget": MagicMock(),
            "QListWidgetItem": MagicMock(),
            "QFileDialog": MagicMock(),
            "QProgressBar": MagicMock(),
            "QMessageBox": MagicMock(),
            "QInputDialog": MagicMock(),
            "QAbstractItemView": MagicMock(),
            "QGroupBox": MagicMock(),
            "QSpinBox": MagicMock(),
            "QDoubleSpinBox": MagicMock(),
            "QDateEdit": MagicMock(),
            "QRadioButton": MagicMock(),
            "QButtonGroup": MagicMock(),
            "QFrame": _FakeWidget,
            "QDialogButtonBox": MagicMock(),
            "QColorDialog": MagicMock(),
            "QCheckBox": MagicMock(),
            "QMenu": MagicMock(),
            "QAction": MagicMock(),
            "QSizePolicy": MagicMock(),
            "QApplication": MagicMock(),
            "QScrollArea": MagicMock(),
            "QTabWidget": MagicMock(),
            "QToolButton": MagicMock(),
            "QSlider": _FakeSlider,
            "QTextEdit": MagicMock(),
            "QStackedWidget": MagicMock(),
            "QGridLayout": MagicMock(),
            "QShortcut": MagicMock(),
            "QToolTip": MagicMock(),
            "QToolBar": _FakeWidget,
            "QPlainTextEdit": MagicMock(),
            "QTextBrowser": MagicMock(),
            "QDesktopWidget": MagicMock(),
            "QSplitter": MagicMock(),
            "QKeySequenceEdit": MagicMock(),
            "QHeaderView": MagicMock(),
            "QTreeWidget": MagicMock(),
            "QTreeWidgetItem": MagicMock(),
        },
    )

    # PyQt5 root
    _make_module(
        "PyQt5",
        {
            "QtCore": qtcore,
            "QtGui": qtgui,
            "QtWidgets": qtwidgets,
        },
    )


# ---------------------------------------------------------------------------
# QGIS mocks
# ---------------------------------------------------------------------------
def _fake_qgs_application():
    """MagicMock with a real string path for qgisUserDatabaseFilePath().

    Plain MagicMock() returns a child MagicMock here, and os.path.dirname()
    on that silently succeeds (via MagicMock's default __fspath__), producing
    a bogus relative path like "MagicMock/mock.qgisUserDatabaseFilePath()"
    that logger.py then happily creates on disk under the test's cwd. Give it
    a real path under the system temp dir so that can't happen.
    """
    app = MagicMock()
    fake_profile_dir = os.path.join(tempfile.gettempdir(), "bdc_loader_test_profile")
    app.qgisUserDatabaseFilePath.return_value = os.path.join(fake_profile_dir, "qgis.db")
    return app


def _install_qgis():
    """Install comprehensive qgis.* mock modules."""

    class _FakeQgsSettings:
        _store = {}

        def value(self, key, default=None, type=None):
            val = self._store.get(key, default)
            if type is not None and val is not None:
                try:
                    val = type(val)
                except (TypeError, ValueError):
                    val = default
            return val

        def setValue(self, key, value):
            self._store[key] = value

        def contains(self, key):
            return key in self._store

        def remove(self, key):
            self._store.pop(key, None)

        @classmethod
        def _reset(cls):
            cls._store.clear()

    class _FakeQgis:
        class MessageLevel:
            Info = 0
            Warning = 1
            Critical = 2

    class _FakeQgsMessageLog:
        _messages = []

        @classmethod
        def logMessage(cls, msg, tag="", level=0):
            cls._messages.append((msg, tag, level))

        @classmethod
        def _reset(cls):
            cls._messages.clear()

    class _FakeQgsPointXY:
        def __init__(self, x=0.0, y=0.0):
            self._x, self._y = x, y

        def x(self):
            return self._x

        def y(self):
            return self._y

    class _FakeQgsCoordinateReferenceSystem:
        def __init__(self, crs_str=""):
            self._crs = crs_str
            self._authid = crs_str if crs_str.startswith(("EPSG:", "USER:", "QGIS:", "CUSTOM:")) else ""

        def isValid(self):
            return bool(self._crs)

        @classmethod
        def fromProj(cls, proj_str):
            obj = cls(proj_str)
            obj._proj = proj_str
            obj._authid = ""
            return obj

        def toProj(self):
            return getattr(self, "_proj", self._crs)

        def toWkt(self):
            return getattr(self, "_wkt", "")

        def description(self):
            return getattr(self, "_description", "")

        def authid(self):
            return self._authid

        def saveAsUserCrs(self, name):
            return 100001

        def __eq__(self, other):
            if isinstance(other, _FakeQgsCoordinateReferenceSystem):
                return self._crs == other._crs
            return False

    class _FakeQgsFields:
        def __init__(self):
            self._fields = []

        def append(self, field):
            self._fields.append(field)

    class _FakeQgsField:
        def __init__(self, name="", field_type=None):
            self._name = name
            self._type = field_type

    class _FakeQgsFeature:
        def __init__(self):
            self._geom = None
            self._attrs = []

        def setGeometry(self, geom):
            self._geom = geom

        def setAttributes(self, attrs):
            self._attrs = attrs

    class _FakeQgsGeometry:
        @staticmethod
        def fromPointXY(pt):
            return _FakeQgsGeometry()

        @staticmethod
        def fromRect(rect):
            return _FakeQgsGeometry()

        def intersects(self, other):
            return True

        def boundingBox(self):
            return MagicMock(intersects=lambda r: True)

        def transform(self, xform):
            pass

    class _FakeQgsWkbTypes(metaclass=_ScopedEnumMeta):
        Point = 1

    class _FakeQgsVectorFileWriter:
        NoError = 0

        def __init__(self, *a, **kw):
            self._features = []

        def hasError(self):
            return 0

        def errorMessage(self):
            return ""

        def addFeature(self, feat):
            self._features.append(feat)

    class _FakeSignal:
        """Fake signal that supports connect/disconnect/emit."""

        def __init__(self):
            self._slots = []

        def connect(self, slot):
            self._slots.append(slot)

        def disconnect(self, slot=None):
            if slot:
                self._slots = [s for s in self._slots if s != slot]
            else:
                self._slots.clear()

        def emit(self, *args):
            for s in self._slots:
                s(*args)

    class _FakeQgsProject:
        _instance = None

        def __init__(self):
            self.layersAdded = _FakeSignal()
            self.layersRemoved = _FakeSignal()
            self._layers = {}
            self._crs = _FakeQgsCoordinateReferenceSystem("EPSG:4326")

        @classmethod
        def instance(cls):
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

        def setCrs(self, crs):
            self._crs = crs

        def crs(self):
            return self._crs

        def addMapLayer(self, layer, addToLegend=True):
            self._layers[getattr(layer, "_id", id(layer))] = layer

        def mapLayers(self):
            return self._layers

        def mapLayer(self, layer_id):
            return self._layers.get(layer_id)

        def mapLayersByName(self, name):
            return [l for l in self._layers.values() if getattr(l, "_name", "") == name]

        def transformContext(self):
            return MagicMock()

    class _FakeQgsRasterLayer:
        def __init__(self, *a, **kw):
            self._valid = True

        def isValid(self):
            return self._valid

    class _FakeQgsVectorLayer:
        def __init__(self, path=None, name="", *a, **kw):
            self._valid = True
            self._path = path
            self._name = name
            self._renderer = None

        def isValid(self):
            return self._valid

        def name(self):
            return self._name

        def setRenderer(self, renderer):
            self._renderer = renderer

        def renderer(self):
            return self._renderer

        def id(self):
            return f"fake_vlayer_{id(self)}"

    # qgis.core
    qgis_core = _make_module(
        "qgis.core",
        {
            "QgsSettings": _FakeQgsSettings,
            "Qgis": _FakeQgis,
            "QgsMessageLog": _FakeQgsMessageLog,
            "QgsPointXY": _FakeQgsPointXY,
            "QgsCoordinateReferenceSystem": _FakeQgsCoordinateReferenceSystem,
            "QgsFields": _FakeQgsFields,
            "QgsField": _FakeQgsField,
            "QgsFeature": _FakeQgsFeature,
            "QgsGeometry": _FakeQgsGeometry,
            "QgsWkbTypes": _FakeQgsWkbTypes,
            "QgsVectorFileWriter": _FakeQgsVectorFileWriter,
            "QgsProject": _FakeQgsProject,
            "QgsRasterLayer": _FakeQgsRasterLayer,
            "QgsVectorLayer": _FakeQgsVectorLayer,
            "QgsCoordinateTransform": MagicMock(),
            "QgsFeatureRequest": MagicMock(),
            "QgsPalLayerSettings": MagicMock(),
            "QgsTextFormat": MagicMock(),
            "QgsVectorLayerSimpleLabeling": MagicMock(),
            "QgsFillSymbol": MagicMock(),
            "QgsTextBufferSettings": MagicMock(),
            "QgsRectangle": MagicMock(),
            "QgsSingleSymbolRenderer": MagicMock(),
            "QgsInvertedPolygonRenderer": MagicMock(),
            "QgsRasterMinMaxOrigin": MagicMock(),
            "QgsContrastEnhancement": MagicMock(),
            "QgsPalettedRasterRenderer": MagicMock(),
            "QgsRasterTransparency": MagicMock(),
            "QgsStyle": MagicMock(),
            "QgsApplication": _fake_qgs_application(),
            "QgsCategorizedSymbolRenderer": MagicMock(),
            "QgsMarkerSymbol": MagicMock(),
            "QgsRendererCategory": MagicMock(),
        },
    )

    # qgis.gui
    class _FakeQgsMapTool:
        def __init__(self, canvas=None):
            pass

        def activate(self):
            pass

        def deactivate(self):
            pass

        def toMapCoordinates(self, pos):
            return _FakeQgsPointXY(0, 0)

    qgis_gui = _make_module(
        "qgis.gui",
        {
            "QgsMapTool": _FakeQgsMapTool,
            "QgsMapCanvas": MagicMock(),
            "QgsMapToolIdentifyFeature": MagicMock(),
            "QgsExtentGroupBox": MagicMock(),
            "QgsExtentWidget": MagicMock(),
            "QgsCollapsibleGroupBox": MagicMock(),
            "QgsRubberBand": MagicMock(),
        },
    )

    # qgis.PyQt (bridges to the PyQt5 we already mocked)
    qgis_pyqt = _make_module(
        "qgis.PyQt",
        {
            "QtWidgets": sys.modules["PyQt5.QtWidgets"],
            "QtCore": sys.modules["PyQt5.QtCore"],
            "QtGui": sys.modules["PyQt5.QtGui"],
        },
    )
    for name in [m for m in sys.modules if m.startswith("PyQt5.")]:
        sub = name.split(".", 1)[1]
        # The attribute and the sys.modules entry are one module: mock.patch
        # reaches "qgis.PyQt.QtWidgets.X" through the attribute on Python 3.10
        # and through sys.modules on 3.11+, and code imports it from sys.modules.
        setattr(qgis_pyqt, sub, _make_module(f"qgis.PyQt.{sub}", sys.modules[name].__dict__))

    # qgis.utils
    qgis_utils = _make_module(
        "qgis.utils",
        {
            "iface": MagicMock(),
        },
    )

    # qgis root
    _make_module(
        "qgis",
        {
            "core": qgis_core,
            "gui": qgis_gui,
            "PyQt": qgis_pyqt,
            "utils": qgis_utils,
        },
    )


# ---------------------------------------------------------------------------
# osgeo (GDAL) mocks
# ---------------------------------------------------------------------------
def _install_osgeo():
    """Install osgeo mock with GDAL and OSR."""

    class _FakeGDAL:
        GA_ReadOnly = 0
        GDT_Float32 = 6

        _config_options = {}

        @classmethod
        def SetConfigOption(cls, key, value):
            cls._config_options[key] = value

        @classmethod
        def GetConfigOption(cls, key, default=None):
            # Reads the same store SetConfigOption writes, so an unset key
            # returns the default.
            return cls._config_options.get(key, default)

        _thread_options = threading.local()
        _path_options = {}

        @classmethod
        def _local(cls):
            if not hasattr(cls._thread_options, "values"):
                cls._thread_options.values = {}
            return cls._thread_options.values

        @classmethod
        def SetThreadLocalConfigOption(cls, key, value):
            if value is None:
                cls._local().pop(key, None)
            else:
                cls._local()[key] = value

        @classmethod
        def GetThreadLocalConfigOption(cls, key, default=None):
            return cls._local().get(key, default)

        @classmethod
        def SetPathSpecificOption(cls, prefix, key, value):
            cls._path_options[(prefix, key)] = value

        @classmethod
        def UseExceptions(cls):
            pass

        @classmethod
        def BuildVRT(cls, vrt_path, hrefs, options=None):
            return None  # default: no dataset

        @classmethod
        def BuildVRTOptions(cls, **kwargs):
            return MagicMock()

        @classmethod
        def Open(cls, path, mode=0):
            return None

        @classmethod
        def Unlink(cls, path):
            pass

    class _FakeSRS:
        def __init__(self):
            self._epsg = None
            self._definition = None

        def ImportFromEPSG(self, code):
            self._epsg = code
            self._definition = f"EPSG:{code}"

        def ImportFromWkt(self, wkt):
            self._definition = wkt

        def SetFromUserInput(self, definition):
            self._definition = definition
            return 0

        def IsSame(self, other):
            return 1 if self._definition == getattr(other, "_definition", object()) else 0

        def SetAxisMappingStrategy(self, strategy):
            pass

    class _FakeOSR:
        OAMS_TRADITIONAL_GIS_ORDER = 0

        @staticmethod
        def SpatialReference():
            return _FakeSRS()

        @staticmethod
        def CoordinateTransformation(src, dst):
            ct = MagicMock()
            ct.TransformPoint = lambda lon, lat: (lon, lat, 0)
            return ct

    _make_module(
        "osgeo",
        {
            "gdal": _FakeGDAL,
            "osr": _FakeOSR,
            "ogr": MagicMock(),
        },
    )
    _make_module(
        "osgeo.gdal",
        {"__name__": "osgeo.gdal", **{k: getattr(_FakeGDAL, k) for k in dir(_FakeGDAL) if not k.startswith("__")}},
    )
    _make_module(
        "osgeo.osr",
        {"__name__": "osgeo.osr", **{k: getattr(_FakeOSR, k) for k in dir(_FakeOSR) if not k.startswith("__")}},
    )
    _make_module("osgeo.ogr", {"__name__": "osgeo.ogr"})

    # Make `from osgeo import gdal` work
    sys.modules["osgeo"].gdal = _FakeGDAL
    sys.modules["osgeo"].osr = _FakeOSR
    sys.modules["osgeo"].ogr = sys.modules["osgeo.ogr"]


# ---------------------------------------------------------------------------
# matplotlib mock
# ---------------------------------------------------------------------------
def _install_matplotlib():
    """Install matplotlib mock for chart modules."""
    _make_module("matplotlib", {})
    _make_module("matplotlib.figure", {"Figure": MagicMock()})
    _make_module("matplotlib.dates", {"num2date": MagicMock()})

    canvas_mock = MagicMock()
    _make_module("matplotlib.backends", {})
    _make_module(
        "matplotlib.backends.backend_qt5agg",
        {
            "FigureCanvasQTAgg": canvas_mock,
        },
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
_mocks_installed = False


def install_mocks():
    """
    Install all mock modules into sys.modules.
    Must be called BEFORE importing any plugin code.

    Idempotent: a repeated call is a no-op. conftest.py installs the mocks
    once before any test module is collected, but several test modules also
    call this at import so they can run standalone. Re-installing would build
    fresh mock classes and overwrite sys.modules entries (QgsMessageLog, the
    osgeo.gdal _FakeGDAL, ...) that production modules already bound by
    reference at import time, orphaning those references and breaking tests
    that run after the second install.
    """
    global _mocks_installed
    if _mocks_installed:
        return
    _install_pyqt5()
    _install_qgis()
    _install_osgeo()
    _install_matplotlib()
    _mocks_installed = True


def reset_state():
    """Reset mutable state in mock objects (call between tests if needed)."""
    if "qgis.core" in sys.modules:
        qgis_core = sys.modules["qgis.core"]
        if hasattr(qgis_core, "QgsSettings"):
            qgis_core.QgsSettings._reset()
        if hasattr(qgis_core, "QgsMessageLog"):
            qgis_core.QgsMessageLog._reset()
