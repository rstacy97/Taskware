import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GObject, GLib
import time
from datetime import datetime, timezone

from ..backend.cron import list_user_jobs, add_user_job, set_user_job_enabled, delete_user_job, update_user_job
from .add_job_dialog import AddJobDialog
from .salt_settings_dialog import SaltSettingsDialog


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.set_title("Taskware")
        self.set_default_size(960, 640)

        # Root layout: Toast overlay -> VBox -> HeaderBar + content
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)
        self._root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # Allow content to occupy full window area
        self._root_box.set_hexpand(True)
        self._root_box.set_vexpand(True)
        self._toast_overlay.set_child(self._root_box)

        # Install simple CSS for timestamp coloring/sizing
        css = Gtk.CssProvider()
        css.load_from_data(b"""
        .taskware-timestamp {
          font-weight: 600;
          font-size: 1.05em;
        }
        .taskware-success { color: #2ecc71; }
        .taskware-error { color: #e74c3c; }
        .taskware-dim { color: alpha(currentColor, 0.5); }
        """)
        try:
            display = Gdk.Display.get_default()  # type: ignore[attr-defined]
        except Exception:
            display = None
        try:
            # GTK 4: add provider for display via Gtk.StyleContext
            from gi.repository import Gdk as _Gdk  # type: ignore
            ctx_add = Gtk.StyleContext.add_provider_for_display  # type: ignore[attr-defined]
            ctx_add(_Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)  # type: ignore
        except Exception:
            # Fallback: ignore if provider cannot be installed (styles just won't apply)
            pass

        # Helper to format timestamps
        self._ts_format = "%m/%d/%Y %I:%M:%S %p"

        header = Adw.HeaderBar()
        # AdwWindow (Adw.ApplicationWindow) does not support set_titlebar; pack into content box
        self._root_box.append(header)

        # View switcher
        self._stack = Gtk.Stack()
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self._stack)

        # Add button (now enabled)
        # Action and accelerator for Add
        add_action = Gio.SimpleAction.new("add", None)
        add_action.connect("activate", lambda *_: self._on_add_clicked())
        self.add_action(add_action)
        app = self.get_application()
        if app:
            app.set_accels_for_action("win.add", ["<Primary>n"])  # Ctrl+N

        self._add_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        self._add_btn.set_tooltip_text("Add new job (Ctrl+N)")
        self._add_btn.set_sensitive(True)
        # Bind button to action
        if hasattr(self._add_btn, "set_action_name"):
            self._add_btn.set_action_name("win.add")
        else:
            self._add_btn.connect("clicked", self._on_add_clicked)

        # Place the switcher in the title area and add button at end
        if hasattr(header, "set_title_widget"):
            header.set_title_widget(switcher)
        else:
            header.pack_start(switcher)
        # Refresh action/button
        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", lambda *_: self._on_refresh_clicked())
        self.add_action(refresh_action)
        app = self.get_application()
        if app:
            app.set_accels_for_action("win.refresh", ["<Primary>r"])  # Ctrl+R

        self._refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self._refresh_btn.set_tooltip_text("Refresh (Ctrl+R)")
        if hasattr(self._refresh_btn, "set_action_name"):
            self._refresh_btn.set_action_name("win.refresh")
        else:
            self._refresh_btn.connect("clicked", self._on_refresh_clicked)

        # Settings (gear) button for integrations (e.g., Salt). Keeps UI uncluttered
        self._settings_btn = Gtk.Button.new_from_icon_name("emblem-system-symbolic")
        self._settings_btn.set_tooltip_text("Settings & Integrations")
        self._settings_btn.connect("clicked", self._on_settings_clicked)

        header.pack_end(self._settings_btn)
        header.pack_end(self._refresh_btn)
        header.pack_end(self._add_btn)

        # Build pages (User Jobs only)
        user_jobs_page = self._build_user_jobs_page()
        self._stack.add_titled(user_jobs_page, "user_jobs", "User Jobs")

        self._root_box.append(self._stack)
        # Ensure a visible child is selected
        self._stack.set_visible_child_name("user_jobs")
        # Periodic auto-refresh: every 30 seconds
        GLib.timeout_add_seconds(30, self._on_tick_refresh)

    def _build_user_jobs_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        box.set_hexpand(True)
        box.set_vexpand(True)

        # Store and view for user jobs
        self._user_store = Gio.ListStore(item_type=JobRow)

        # List view + factory
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_setup)
        factory.connect("bind", self._on_bind)
        selection = Gtk.NoSelection(model=self._user_store)
        self._user_list_view = Gtk.ListView(model=selection, factory=factory)
        self._user_list_view.set_hexpand(True)
        self._user_list_view.set_vexpand(True)
        self._user_scroller = Gtk.ScrolledWindow()
        self._user_scroller.set_hexpand(True)
        self._user_scroller.set_vexpand(True)
        try:
            from gi.repository import Gtk as _Gtk  # type: ignore
            self._user_scroller.set_policy(_Gtk.PolicyType.NEVER, _Gtk.PolicyType.AUTOMATIC)
        except Exception:
            pass
        self._user_scroller.set_child(self._user_list_view)

        # Empty state page
        self._empty_page = Adw.StatusPage()
        self._empty_page.set_title("No user jobs yet")
        self._empty_page.set_description("Click the + button or press Ctrl+N to add your first scheduled job.")
        # Add a call-to-action button inside the status page
        cta = Gtk.Button.new_with_label("Add Job")
        if hasattr(cta, "set_action_name"):
            cta.set_action_name("win.add")
        else:
            cta.connect("clicked", self._on_add_clicked)
        try:
            self._empty_page.set_child(cta)  # type: ignore[attr-defined]
        except Exception:
            pass

        # Stack to swap between empty page and list
        self._user_stack = Gtk.Stack()
        self._user_stack.set_hexpand(True)
        self._user_stack.set_vexpand(True)
        self._user_stack.add_named(self._empty_page, "empty")
        self._user_stack.add_named(self._user_scroller, "list")
        box.append(self._user_stack)

        # Populate
        self._refresh_user_jobs()
        # Onboarding toast for first-run empty state
        if self._user_store.get_n_items() == 0:
            self._toast("No jobs yet — click + or press Ctrl+N to add one")
        return box

    # System Jobs page and related functionality removed

    def _refresh_user_jobs(self) -> None:
        # Rebuild the liststore from backend
        jobs = list_user_jobs()
        self._user_store.remove_all()
        for job in jobs:
            self._user_store.append(
                JobRow(
                    job_id=str(job.get("id", "")),
                    schedule=str(job.get("schedule", "")),
                    command=str(job.get("command", "")),
                    enabled=bool(job.get("enabled", True)),
                    last_run=job.get("last_run"),
                    last_exit=job.get("last_exit"),
                    description=job.get("description"),
                )
            )
        # Swap view based on content
        if self._user_store.get_n_items() == 0:
            self._user_stack.set_visible_child_name("empty")
        else:
            self._user_stack.set_visible_child_name("list")

    def _on_refresh_clicked(self) -> None:
        self._refresh_user_jobs()
        self._toast("Refreshed")

    def _on_tick_refresh(self) -> bool:
        # Called by GLib timeout, keep running
        try:
            self._refresh_user_jobs()
        except Exception as e:
            self._toast(f"Refresh failed: {e}")
        return True

    # List item setup/bind
    def _on_setup(self, _factory: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        row = Adw.ActionRow()
        row.add_prefix(Gtk.Image.new_from_icon_name("alarm-symbolic"))
        row.set_title("")
        row.set_subtitle("")
        # Timestamp label (color-coded and larger)
        ts_lbl = Gtk.Label(label="—")
        ts_lbl.set_valign(Gtk.Align.CENTER)
        if hasattr(ts_lbl, "add_css_class"):
            ts_lbl.add_css_class("taskware-timestamp")
            ts_lbl.add_css_class("taskware-dim")
        row.add_suffix(ts_lbl)
        # Toggle for enabled/disabled (non-functional for now)
        toggle = Gtk.Switch()
        toggle.set_valign(Gtk.Align.CENTER)
        row.add_suffix(toggle)
        # Edit button
        edit_btn = Gtk.Button.new_from_icon_name("document-edit-symbolic")
        edit_btn.set_valign(Gtk.Align.CENTER)
        edit_btn.set_tooltip_text("Edit job")
        row.add_suffix(edit_btn)
        # Delete button
        del_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.set_tooltip_text("Delete job")
        del_btn.set_sensitive(True)
        row.add_suffix(del_btn)
        # keep a reference for bind updates
        row._toggle = toggle  # type: ignore[attr-defined]
        row._delete_btn = del_btn  # type: ignore[attr-defined]
        row._edit_btn = edit_btn  # type: ignore[attr-defined]
        row._ts_lbl = ts_lbl  # type: ignore[attr-defined]
        list_item.set_child(row)

    def _on_bind(self, _factory: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        row: Adw.ActionRow = list_item.get_child()  # type: ignore[assignment]
        item: JobRow = list_item.get_item()  # type: ignore[assignment]
        # Title prefers description if present, else command
        title_text = item.description if getattr(item, "description", None) else item.command
        safe_title = GLib.markup_escape_text(title_text) if title_text is not None else ""
        row.set_title(safe_title)
        # Build subtitle with schedule and last run info
        status = ""
        if getattr(item, "last_run", None) is not None and getattr(item, "last_exit", None) is not None:
            label = "ok" if item.last_exit == 0 else f"fail {item.last_exit}"
            status = f" — last: {item.last_run} ({label})"
        # Include command in subtitle if we showed description as title
        sub_core = f"{item.command} — {item.schedule}" if getattr(item, "description", None) else f"{item.schedule}"
        safe_sub = GLib.markup_escape_text(f"{sub_core}{status}")
        row.set_subtitle(safe_sub)
        # update toggle state if available
        toggle = getattr(row, "_toggle", None)
        if isinstance(toggle, Gtk.Switch):
            # set current state without triggering callbacks
            toggle.set_active(item.enabled)
            # ensure only one connection to state-set
            try:
                toggle.disconnect_by_func(self._on_switch_state_set)
            except Exception:
                pass
            toggle.connect("state-set", self._on_switch_state_set, item)
        # update timestamp label
        ts_lbl = getattr(row, "_ts_lbl", None)
        if isinstance(ts_lbl, Gtk.Label):
            # Clear previous classes
            for cls in ("taskware-success", "taskware-error", "taskware-dim"):
                try:
                    ts_lbl.remove_css_class(cls)
                except Exception:
                    pass
            if item.last_run is None:
                ts_lbl.set_text("—")
                try:
                    ts_lbl.add_css_class("taskware-dim")
                except Exception:
                    pass
            else:
                # Parse ISO timestamp and format in American style with local tz
                ts_text = str(item.last_run)
                try:
                    dt = datetime.fromisoformat(ts_text)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc).astimezone()
                    else:
                        dt = dt.astimezone()
                    ts_text = dt.strftime(self._ts_format)
                except Exception:
                    # fall back to raw
                    pass
                ts_lbl.set_text(ts_text)
                # Color by exit status
                if item.last_exit == 0:
                    try:
                        ts_lbl.add_css_class("taskware-success")
                    except Exception:
                        pass
                else:
                    try:
                        ts_lbl.add_css_class("taskware-error")
                    except Exception:
                        pass
                ts_lbl.set_tooltip_text(f"Exit code: {item.last_exit}")
        # wire delete
        del_btn = getattr(row, "_delete_btn", None)
        if isinstance(del_btn, Gtk.Button):
            try:
                del_btn.disconnect_by_func(self._on_delete_clicked)
            except Exception:
                pass
            del_btn.connect("clicked", self._on_delete_clicked, item)
        # wire edit
        edit_btn = getattr(row, "_edit_btn", None)
        if isinstance(edit_btn, Gtk.Button):
            try:
                edit_btn.disconnect_by_func(self._on_edit_clicked)
            except Exception:
                pass
            edit_btn.connect("clicked", self._on_edit_clicked, item)

    def _on_add_clicked(self, *_):
        # Only User Jobs supported
        dlg = AddJobDialog(self)
        dlg.connect("response", self._on_add_dialog_response)
        dlg.present()

    def _on_settings_clicked(self, *_):
        try:
            dlg = SaltSettingsDialog(self)
            dlg.present()
        except Exception as e:
            self._toast(f"Failed to open settings: {e}")

    def _on_add_dialog_response(self, dlg: AddJobDialog, response_id: int) -> None:
        if response_id != Gtk.ResponseType.OK:
            dlg.destroy()
            return
        try:
            command, cron, extra = dlg.get_values()
            description = extra.get("description") if isinstance(extra, dict) else None
            added = add_user_job(cron, command, description)
            self._refresh_user_jobs()
            title = (description or added.get('command') or '').strip()
            self._toast(f"Job added{': ' + self._shorten(title) if title else ''}")
        except Exception as e:
            self._toast(f"Failed to add job: {e}")
        finally:
            dlg.destroy()

    def _on_edit_clicked(self, _btn: Gtk.Button, item: "JobRow") -> None:
        # Prefilled dialog
        dlg = AddJobDialog(self)
        dlg.set_initial(item.command, item.schedule, getattr(item, "description", None))
        if hasattr(dlg, "set_mode_edit"):
            dlg.set_mode_edit()
        dlg.connect("response", self._on_edit_dialog_response, item)
        dlg.present()

    def _on_edit_dialog_response(self, dlg: AddJobDialog, response_id: int, item: "JobRow") -> None:
        if response_id != Gtk.ResponseType.OK:
            dlg.destroy()
            return
        try:
            command, cron, extra = dlg.get_values()
            description = extra.get("description") if isinstance(extra, dict) else None
            updated = update_user_job(item.job_id, cron, command, description)
            self._refresh_user_jobs()
            self._toast("Job updated")
        except Exception as e:
            self._toast(f"Failed to update: {e}")
        finally:
            dlg.destroy()

    def _on_switch_state_set(self, toggle: Gtk.Switch, state: bool, item: "JobRow") -> bool:
        try:
            set_user_job_enabled(item.job_id, bool(state))
            item.enabled = bool(state)
            self._toast("Enabled" if item.enabled else "Disabled")
            return False  # allow state change to proceed
        except Exception as e:
            # revert UI by denying the state change
            self._toast(f"Failed to update job: {e}")
            return True  # prevent the state change

    def _toast(self, message: str) -> None:
        try:
            msg = str(message).strip()
        except Exception:
            msg = ""
        if not msg:
            msg = "Done"
        try:
            toast = Adw.Toast.new(msg)
            # Be explicit to avoid markup/theme issues
            if hasattr(toast, "set_use_markup"):
                toast.set_use_markup(False)
            if hasattr(toast, "set_timeout"):
                toast.set_timeout(3)
            self._toast_overlay.add_toast(toast)
        except Exception:
            # Fallback
            self._toast_overlay.add_toast(Adw.Toast.new("Done"))

    def _shorten(self, text: str, max_len: int = 80) -> str:
        try:
            s = str(text)
        except Exception:
            return ""
        s = s.replace("\n", " ").replace("\r", " ")
        if len(s) <= max_len:
            return s
        return s[: max_len - 1] + "…"

    # -------- System Jobs (systemd timers) --------
    def _refresh_system_jobs(self) -> None:
        # User timers
        try:
            timers = list_user_timers()
        except Exception:
            timers = []
        self._sys_user_store.remove_all()
        for t in timers:
            unit = str(t.get("unit", ""))
            base = unit[:-6] if unit.endswith('.timer') else unit
            if not getattr(self, "_show_all_sys", False):
                # show only Taskware timers
                try:
                    if not is_taskware_timer(base, user=True):
                        continue
                except Exception:
                    continue
            self._sys_user_store.append(SystemTimerRow(
                unit=unit,
                activates=str(t.get("activates", "")),
                next_run=str(t.get("next", "")),
                last_run=str(t.get("last", "")),
                left=str(t.get("left", "")),
                passed=str(t.get("passed", "")),
                is_root=False,
            ))
        # System timers (root)
        try:
            root_timers = list_system_timers()
        except Exception:
            root_timers = []
        self._sys_root_store.remove_all()
        for t in root_timers:
            unit = str(t.get("unit", ""))
            base = unit[:-6] if unit.endswith('.timer') else unit
            if not getattr(self, "_show_all_sys", False):
                try:
                    if not is_taskware_timer(base, user=False):
                        continue
                except Exception:
                    continue
            self._sys_root_store.append(SystemTimerRow(
                unit=unit,
                activates=str(t.get("activates", "")),
                next_run=str(t.get("next", "")),
                last_run=str(t.get("last", "")),
                left=str(t.get("left", "")),
                passed=str(t.get("passed", "")),
                is_root=True,
            ))

    def _on_sys_filter_changed(self, *_):
        self._show_all_sys = bool(self._sys_show_all_chk.get_active())
        self._refresh_system_jobs()

    def _on_sys_policy_changed(self, *_):
        self._allow_delete_all_sys = bool(self._sys_delete_all_chk.get_active())
        self._refresh_system_jobs()

    def _on_sys_setup(self, _factory: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        row = Adw.ActionRow()
        row.add_prefix(Gtk.Image.new_from_icon_name("system-run-symbolic"))
        row.set_title("")
        row.set_subtitle("")
        # Edit and delete buttons
        edit_btn = Gtk.Button.new_from_icon_name("document-edit-symbolic")
        edit_btn.set_valign(Gtk.Align.CENTER)
        edit_btn.set_tooltip_text("Edit timer")
        row.add_suffix(edit_btn)
        del_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.set_tooltip_text("Delete timer")
        row.add_suffix(del_btn)
        row._sys_edit_btn = edit_btn  # type: ignore[attr-defined]
        row._sys_delete_btn = del_btn  # type: ignore[attr-defined]
        list_item.set_child(row)

    def _on_sys_bind(self, _factory: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        row: Adw.ActionRow = list_item.get_child()  # type: ignore[assignment]
        item: SystemTimerRow = list_item.get_item()  # type: ignore[assignment]
        title = f"{item.unit} → {item.activates}" if item.activates else item.unit
        row.set_title(GLib.markup_escape_text(title))
        subtitle = f"Next: {item.next_run}  •  Last: {item.last_run}  •  Left: {item.left}  •  Passed: {item.passed}"
        row.set_subtitle(GLib.markup_escape_text(subtitle))
        # Wire edit/delete
        edit_btn = getattr(row, "_sys_edit_btn", None)
        if isinstance(edit_btn, Gtk.Button):
            try:
                edit_btn.disconnect_by_func(self._on_sys_edit_clicked)
            except Exception:
                pass
            edit_btn.connect("clicked", self._on_sys_edit_clicked, item)
        del_btn = getattr(row, "_sys_delete_btn", None)
        if isinstance(del_btn, Gtk.Button):
            try:
                del_btn.disconnect_by_func(self._on_sys_delete_clicked)
            except Exception:
                pass
            # Only allow delete for Taskware-created timers unless override is enabled
            base = item.unit[:-6] if item.unit.endswith('.timer') else item.unit
            is_tw = is_taskware_timer(base, user=(not item.is_root))
            allow_any = bool(getattr(self, "_allow_delete_all_sys", False))
            can_delete = (is_tw or allow_any)
            del_btn.set_sensitive(can_delete)
            if can_delete:
                del_btn.set_tooltip_text("Delete timer")
            else:
                del_btn.set_tooltip_text("Cannot delete non-Taskware timer; use Disable/Mask via systemctl")
            del_btn.connect("clicked", self._on_sys_delete_clicked, item)

    def _on_delete_clicked(self, _btn: Gtk.Button, item: "JobRow") -> None:
        # Simple confirmation dialog (Gtk for compatibility)
        # Escape command in dialog text as well
        safe_cmd = GLib.markup_escape_text(item.command)
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            buttons=Gtk.ButtonsType.NONE,
            message_type=Gtk.MessageType.QUESTION,
            text="Delete job?",
            secondary_text=f"This will remove the job: {safe_cmd}",
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Delete", Gtk.ResponseType.OK)
        dialog.connect("response", self._on_delete_response, item)
        dialog.present()

    def _on_delete_response(self, dialog: Gtk.Dialog, response_id: int, item: "JobRow") -> None:
        try:
            if response_id != Gtk.ResponseType.OK:
                return
            delete_user_job(item.job_id)
            self._refresh_user_jobs()
            self._toast("Job deleted")
        except Exception as e:
            self._toast(f"Failed to delete: {e}")
        finally:
            dialog.destroy()

class JobRow(GObject.GObject):
    """Simple data object for list rows."""
    def __init__(self, job_id: str, schedule: str, command: str, enabled: bool = True, last_run=None, last_exit=None, description: str | None = None) -> None:
        super().__init__()
        self.job_id = job_id
        self.schedule = schedule
        self.command = command
        self.enabled = enabled
        self.last_run = last_run
        self.last_exit = last_exit
        self.description = description


class SystemTimerRow(GObject.GObject):
    def __init__(self, unit: str, activates: str, next_run: str, last_run: str, left: str, passed: str, is_root: bool) -> None:
        super().__init__()
        self.unit = unit
        self.activates = activates
        self.next_run = next_run
        self.last_run = last_run
        self.left = left
        self.passed = passed
        self.is_root = is_root
