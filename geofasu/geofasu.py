# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from .geofasu_dialog import geofasuDialog
from .postprocess_dialog import PostProcessDialog
import os



class geofasu:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor."""
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.plugin_name = "GEOFASU"  # Uppercase name everywhere
        self.menu = self.tr(f"&{self.plugin_name}")
        self.first_start = None

        # --- Load translator (if available) ---
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir, 'i18n', f'geofasu_{locale}.qm'
        )

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

    # =========================================================
    # Translation helper
    # =========================================================
    def tr(self, message):
        return QCoreApplication.translate(self.plugin_name, message)

    # =========================================================
    # Add menu / toolbar action
    # =========================================================
    def add_action(self, icon_path, text, callback,
                   enabled_flag=True,
                   add_to_menu=True,
                   add_to_toolbar=True,
                   status_tip=None,
                   whats_this=None,
                   parent=None):
        """Add toolbar/menu action."""

        icon = QIcon(icon_path)
        if icon.isNull():
            print(f"[{self.plugin_name}] Icon not found at: {icon_path}")

        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip:
            action.setStatusTip(status_tip)

        if whats_this:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)
        return action

    # =========================================================
    # GUI Initialization
    # =========================================================
    def initGui(self):
        """Create menu/toolbar entries."""

        # ⭐ PRE-PROCESS icon
        icon_pre = os.path.join(self.plugin_dir, 'pre_process.png')

        # ⭐ POST-PROCESS icon
        icon_post = os.path.join(self.plugin_dir, 'post_process.png')

        # 🔹 MAIN TOOL (PRE-PROCESS)
        self.add_action(
            icon_pre,
            text=self.tr("GEOFASU PRE-PROCESS"),
            callback=self.run,
            parent=self.iface.mainWindow()
        )

        # 🔹 SECOND TOOL (POST-PROCESS)
        self.add_action(
            icon_post,
            text=self.tr("GEOFASU POST-PROCESS"),
            callback=self.run_postprocess,
            parent=self.iface.mainWindow()
        )

        self.first_start = True

    # =========================================================
    # Cleanup on unload
    # =========================================================
    def unload(self):
        """Remove plugin menu/toolbar items."""

        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)

    # =========================================================
    # MAIN DIALOG
    # =========================================================
    def run(self):
        """Run the main GEOFASU dialog."""

        if self.first_start:
            self.first_start = False
            self.dlg = geofasuDialog()
            self.dlg.setWindowTitle(f"{self.plugin_name} — PRE-PROCESS")

        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

    # =========================================================
    # POST-PROCESS TOOL
    # =========================================================
    def run_postprocess(self):
        """Open POST-PROCESS dialog."""

        if not hasattr(self, 'post_dlg') or self.post_dlg is None:
            self.post_dlg = PostProcessDialog(self.iface.mainWindow())
            self.post_dlg.setWindowTitle(f"{self.plugin_name} — POST-PROCESS")

        self.post_dlg.show()
        self.post_dlg.raise_()
        self.post_dlg.activateWindow()