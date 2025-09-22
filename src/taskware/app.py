import gi
# Require versions before importing modules
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio


class TaskwareApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="com.taskware.Taskware",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        Adw.init()

    def do_activate(self) -> None:
        # Reuse an existing window if available
        win = self.props.active_window
        if not win:
            from .windows.main_window import MainWindow

            win = MainWindow(application=self)
        win.present()


def main() -> int:
    app = TaskwareApplication()
    return app.run(None)
