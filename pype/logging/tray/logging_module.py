import os
from Qt import QtWidgets

from pypeapp import Logger

from ..gui.app import LogsWindow

log = Logger().get_logger("LoggingModule", "logging")


class LoggingModule:
    def __init__(self, main_parent=None, parent=None):
        self.parent = parent

        self.window = LogsWindow()

    # Definition of Tray menu
    def tray_menu(self, parent_menu):
        # Menu for Tray App
        menu = QtWidgets.QMenu('Logging', parent_menu)
        # menu.setProperty('submenu', 'on')

        show_action = QtWidgets.QAction("Show Logs", menu)
        show_action.triggered.connect(self.on_show_logs)
        menu.addAction(show_action)

        parent_menu.addMenu(menu)

    def tray_start(self):
        pass

    def process_modules(self, modules):
        return

    def on_show_logs(self):
        self.window.show()
