import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

import json
import os
from typing import Dict, Any

from ..backend.cron import list_user_jobs
from ..backend.salt_exporter import export_job_to_files, SaltConfig


CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "taskware")
CONFIG_PATH = os.path.join(CONFIG_DIR, "salt.json")


def _load_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg: Dict[str, Any]) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


class SaltSettingsDialog(Gtk.Dialog):
    def __init__(self, parent: Adw.ApplicationWindow):
        super().__init__(transient_for=parent, modal=True, use_header_bar=True)
        self.set_title("Salt Integration")
        self.set_default_size(520, 440)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.get_content_area().append(box)

        box.append(Gtk.Label(label="Salt Master (optional)", xalign=0))

        # Fields
        self._url = Gtk.Entry(placeholder_text="https://salt-master:8000")
        self._eauth = Gtk.Entry(placeholder_text="pam")
        self._username = Gtk.Entry(placeholder_text="saltuser")
        self._verify_tls = Gtk.CheckButton.new_with_label("Verify TLS certificates")
        self._token = Gtk.Entry(placeholder_text="(optional API token)")
        self._token.set_visibility(False)
        self._token.set_invisible_char("•")

        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        def row(label: str, w: Gtk.Widget, r: int):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            grid.attach(w, 1, r, 1, 1)
        row("Master URL", self._url, 0)
        row("Auth (eauth)", self._eauth, 1)
        row("Username", self._username, 2)
        row("Verify TLS", self._verify_tls, 3)
        row("API Token", self._token, 4)
        box.append(grid)

        # Targeting
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.append(Gtk.Label(label="Targeting", xalign=0))
        self._tgt_type_model = Gtk.StringList.new(["glob", "list", "grain", "nodegroup"])
        self._tgt_type = Gtk.DropDown(model=self._tgt_type_model)
        self._tgt_value = Gtk.Entry(placeholder_text="* (glob), or comma-separated list, or grain expr")
        tgrid = Gtk.Grid(column_spacing=8, row_spacing=6)
        def row_t(label: str, w: Gtk.Widget, r: int):
            tgrid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            tgrid.attach(w, 1, r, 1, 1)
        row_t("Type", self._tgt_type, 0)
        row_t("Value", self._tgt_value, 1)
        box.append(tgrid)

        # Actions
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._save_btn = Gtk.Button.new_with_label("Save Settings")
        self._export_btn = Gtk.Button.new_with_label("Generate SLS files…")
        btn_box.append(self._save_btn)
        btn_box.append(self._export_btn)
        box.append(btn_box)

        self._save_btn.connect("clicked", self._on_save)
        self._export_btn.connect("clicked", self._on_export)

        self._load()

    def _load(self) -> None:
        cfg = _load_config()
        self._url.set_text(str(cfg.get("master_url", "https://localhost:8000")))
        self._eauth.set_text(str(cfg.get("eauth", "pam")))
        self._username.set_text(str(cfg.get("username", "")))
        self._verify_tls.set_active(bool(cfg.get("verify_tls", True)))
        self._token.set_text(str(cfg.get("token", "")))
        # Targeting
        ttype = str(cfg.get("target_type", "glob"))
        try:
            self._tgt_type.set_selected(["glob","list","grain","nodegroup"].index(ttype))
        except Exception:
            self._tgt_type.set_selected(0)
        self._tgt_value.set_text(str(cfg.get("target", "*")))

    def _on_save(self, *_):
        cfg = {
            "master_url": self._url.get_text().strip() or "https://localhost:8000",
            "eauth": self._eauth.get_text().strip() or "pam",
            "username": self._username.get_text().strip(),
            "verify_tls": bool(self._verify_tls.get_active()),
            "token": self._token.get_text().strip(),
            "target_type": self._tgt_type_model.get_string(self._tgt_type.get_selected()) or "glob",
            "target": self._tgt_value.get_text().strip() or "*",
        }
        _save_config(cfg)
        parent = self.get_transient_for()
        cb = getattr(parent, "_toast", None)
        if callable(cb):
            try:
                cb("Saved")
            except Exception:
                pass

    def _on_export(self, *_):
        # Choose directory
        chooser = Gtk.FileChooserNative.new("Choose output directory", self.get_root(), Gtk.FileChooserAction.SELECT_FOLDER, "Select", "Cancel")
        resp = chooser.run()
        if resp != Gtk.ResponseType.ACCEPT:
            return
        folder = chooser.get_file()
        if not folder:
            return
        out_dir = folder.get_path() or os.getcwd()

        # Export all user jobs for now
        jobs = list_user_jobs()
        count = 0
        for j in jobs:
            try:
                export_job_to_files(j, out_dir)
                count += 1
            except Exception:
                pass
        parent = self.get_transient_for()
        cb = getattr(parent, "_toast", None)
        if callable(cb):
            try:
                cb(f"Exported {count} SLS files")
            except Exception:
                pass
