import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw


class AddTimerDialog(Gtk.Dialog):
    def __init__(self, parent: Adw.ApplicationWindow):
        super().__init__(transient_for=parent, modal=True, use_header_bar=True)
        self.set_title("Add System Timer")
        self.set_default_size(600, 520)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.get_content_area().append(box)

        # Name (unit base)
        self._name = Gtk.Entry(placeholder_text="Unique name, e.g. backup-nightly")
        box.append(Gtk.Label(label="Timer name (no spaces)"))
        box.append(self._name)

        # Command
        self._command = Gtk.Entry(placeholder_text="Command to run, e.g. /usr/bin/uptime -p")
        box.append(Gtk.Label(label="Command (ExecStart)"))
        box.append(self._command)

        # Builder
        builder_frame = Gtk.Frame()
        builder_frame.set_label("Schedule builder (OnCalendar)")
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        builder_frame.set_child(b)
        box.append(builder_frame)

        # Frequency dropdown
        self._freq_model = Gtk.StringList.new([
            "Every minute",
            "Every N minutes",
            "Hourly at minute",
            "Daily at time",
            "Weekly on selected days at time",
            "Monthly on day at time",
        ])
        self._freq_dd = Gtk.DropDown(model=self._freq_model)
        b.append(self._row("Frequency", self._freq_dd))

        # Weekdays toggles (Sun=0..Sat=6 in systemd strings)
        self._weekday_buttons: list[Gtk.ToggleButton] = []
        weekdays_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for name in ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]:
            btn = Gtk.ToggleButton(label=name)
            btn.connect("toggled", self._on_builder_changed)
            btn.set_margin_end(2)
            self._weekday_buttons.append(btn)
            weekdays_box.append(btn)
        b.append(self._row("Weekdays", weekdays_box))

        # Time selectors (12-hour AM/PM with 15-minute intervals)
        self._hour12_model = Gtk.StringList.new([f"{i}" for i in range(1,13)])
        self._hour12_dd = Gtk.DropDown(model=self._hour12_model)
        self._min15_model = Gtk.StringList.new(["00","15","30","45"])
        self._min15_dd = Gtk.DropDown(model=self._min15_model)
        self._ampm_model = Gtk.StringList.new(["AM","PM"])
        self._ampm_dd = Gtk.DropDown(model=self._ampm_model)
        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        time_box.append(Gtk.Label(label="Hour"))
        time_box.append(self._hour12_dd)
        time_box.append(Gtk.Label(label="Minute"))
        time_box.append(self._min15_dd)
        time_box.append(self._ampm_dd)
        b.append(self._row("Time (12-hour)", time_box))

        # Day of month for Monthly
        day_adj = Gtk.Adjustment(lower=1, upper=31, step_increment=1, page_increment=5)
        self._day = Gtk.SpinButton(adjustment=day_adj, climb_rate=1, digits=0)
        b.append(self._row("Day of month", self._day))

        # N minutes
        n_adj = Gtk.Adjustment(lower=1, upper=59, step_increment=1, page_increment=5)
        self._n_minutes = Gtk.SpinButton(adjustment=n_adj, climb_rate=1, digits=0)
        b.append(self._row("N (minutes)", self._n_minutes))

        # OnCalendar (editable)
        self._oncal = Gtk.Entry(placeholder_text="OnCalendar, e.g. *:0/15 or Mon,Wed 18:30 or 18:00 or 2025-10-01..2025-10-31 18:00")
        box.append(Gtk.Label(label="OnCalendar (auto-filled, editable)"))
        box.append(self._oncal)

        # Optional date range (limits when the timer triggers)
        self._range_chk = Gtk.CheckButton.new_with_label("Limit to date range")
        box.append(self._range_chk)
        range_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._start_cal = Gtk.Calendar()
        self._end_cal = Gtk.Calendar()
        range_box.append(self._col("Start date", self._start_cal))
        range_box.append(self._col("End date", self._end_cal))
        box.append(range_box)

        # Run as root (sudo/pkexec)
        self._root_chk = Gtk.CheckButton.new_with_label("Run as root (requires authentication)")
        box.append(self._root_chk)

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self._ok = self.add_button("Add", Gtk.ResponseType.OK)
        self._ok.set_sensitive(False)

        # Signals
        self._name.connect("changed", self._validate)
        self._command.connect("changed", self._validate)
        self._oncal.connect("changed", self._validate)
        self._freq_dd.connect("notify::selected", self._on_builder_changed)
        self._hour12_dd.connect("notify::selected", self._on_builder_changed)
        self._min15_dd.connect("notify::selected", self._on_builder_changed)
        self._ampm_dd.connect("notify::selected", self._on_builder_changed)
        self._n_minutes.connect("value-changed", self._on_builder_changed)
        self._day.connect("value-changed", self._on_builder_changed)
        self._range_chk.connect("toggled", self._on_builder_changed)

        # Defaults
        self._freq_dd.set_selected(0)
        # Default to 6:00 PM
        self._hour12_dd.set_selected(5)  # 6
        self._min15_dd.set_selected(0)   # :00
        self._ampm_dd.set_selected(1)    # PM
        self._n_minutes.set_value(5)
        # Preselect Wed/Sat
        for i, name in enumerate(["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]):
            if name in ("Wed","Sat"):
                self._weekday_buttons[i].set_active(True)
        self._update_builder_visibility()
        self._apply_builder_to_oncal()

    def _validate(self, *_):
        name_ok = self._name.get_text().strip() != "" and (" " not in self._name.get_text())
        cmd_ok = self._command.get_text().strip() != ""
        on_ok = self._oncal.get_text().strip() != ""
        # If range enabled, ensure start <= end
        if self._range_chk.get_active():
            y1,m1,d1 = self._start_cal.get_date()
            y2,m2,d2 = self._end_cal.get_date()
            start = (y1, m1, d1)
            end = (y2, m2, d2)
            if start > end:
                on_ok = False
        self._ok.set_sensitive(name_ok and cmd_ok and on_ok)

    def get_values(self):
        return (
            self._name.get_text().strip(),
            self._command.get_text().strip(),
            self._oncal.get_text().strip(),
            bool(self._root_chk.get_active()),
        )

    # ---- Edit support ----
    def set_initial(self, name: str, command: str, oncalendar: str, is_root: bool = False) -> None:
        """Prefill dialog fields for editing an existing timer."""
        self._name.set_text(name)
        self._name.set_editable(False)
        self._command.set_text(command)
        if oncalendar:
            self._oncal.set_text(oncalendar)
        # Lock root toggle to reflect existing unit scope
        self._root_chk.set_active(bool(is_root))
        self._root_chk.set_sensitive(False)
        self._validate()

    def set_mode_edit(self) -> None:
        try:
            self.set_title("Edit System Timer")
        except Exception:
            pass
        try:
            self._ok.set_label("Save")
        except Exception:
            pass

    def _row(self, title: str, widget: Gtk.Widget) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(Gtk.Label(label=title, xalign=0))
        box.append(widget)
        return box

    def _col(self, title: str, widget: Gtk.Widget) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(Gtk.Label(label=title, xalign=0))
        box.append(widget)
        return box

    def _on_builder_changed(self, *_):
        self._update_builder_visibility()
        self._apply_builder_to_oncal()
        self._validate()

    def _update_builder_visibility(self) -> None:
        sel = self._freq_dd.get_selected()
        every_minute = (sel == 0)
        every_n = (sel == 1)
        hourly = (sel == 2)
        daily = (sel == 3)
        weekly = (sel == 4)
        monthly = (sel == 5)
        for btn in self._weekday_buttons:
            btn.set_visible(weekly)
        self._hour12_dd.set_visible(hourly or daily or weekly or monthly)
        self._min15_dd.set_visible(hourly or daily or weekly or monthly)
        self._ampm_dd.set_visible(hourly or daily or weekly or monthly)
        self._n_minutes.set_visible(every_n)
        self._day.set_visible(monthly)

    def _apply_builder_to_oncal(self) -> None:
        sel = self._freq_dd.get_selected()
        # Compute 24h hour and minute from 12h dropdowns
        h12 = int(self._hour12_model.get_string(self._hour12_dd.get_selected()) or "12")
        ampm = self._ampm_model.get_string(self._ampm_dd.get_selected()) or "AM"
        h = (0 if h12 == 12 else h12)
        if ampm == "PM":
            h = (h + 12) % 24
        m = int(self._min15_model.get_string(self._min15_dd.get_selected()) or "0")
        n = int(self._n_minutes.get_value())
        # Collect weekday labels
        days = [btn.get_label() for btn in self._weekday_buttons if btn.get_active()]
        day_of_month = int(self._day.get_value())
        if sel == 0:
            oncal = "minutely"  # alias in systemd
        elif sel == 1:
            n = max(1, min(59, n))
            # systemd supports *:0/5 to mean every 5 minutes
            oncal = f"*:0/{n}"
        elif sel == 2:
            oncal = f"*:{m:02d}"
        elif sel == 3:
            oncal = f"{h:02d}:{m:02d}"
        elif sel == 4:
            prefix = ",".join(days) if days else "Mon..Sun"
            oncal = f"{prefix} {h:02d}:{m:02d}"
        elif sel == 5:
            # monthly on given day at time: *-*-DD HH:MM
            oncal = f"*-*-{day_of_month:02d} {h:02d}:{m:02d}"
        else:
            oncal = "minutely"
        # Apply date range if enabled
        if self._range_chk.get_active():
            y1,m1,d1 = self._start_cal.get_date()
            y2,m2,d2 = self._end_cal.get_date()
            # Gtk.Calendar returns month 0-based
            s = f"{y1:04d}-{m1+1:02d}-{d1:02d}"
            e = f"{y2:04d}-{m2+1:02d}-{d2:02d}"
            oncal = f"{s}..{e} {oncal}"
        self._oncal.set_text(oncal)
