import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw


class AddJobDialog(Gtk.Dialog):
    def __init__(self, parent: Adw.ApplicationWindow):
        super().__init__(transient_for=parent, modal=True, use_header_bar=True)
        self.set_title("Add New Job")
        self.set_default_size(640, 700)
        self._suppress_builder = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.get_content_area().append(box)

        # Optional description
        self._desc_entry = Gtk.Entry(placeholder_text="Optional description, e.g. Nightly DB backup")
        box.append(Gtk.Label(label="Description (optional)"))
        box.append(self._desc_entry)

        # Command entry
        self._command_entry = Gtk.Entry(placeholder_text="Command to run, e.g. /usr/bin/backup --quick")
        box.append(Gtk.Label(label="Command"))
        box.append(self._command_entry)

        # (Removed) Natural language schedule field

        # Schedule builder (dropdowns/time) -> generates cron expression
        builder_frame = Gtk.Frame()
        builder_frame.set_label("Schedule builder")
        builder_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        builder_frame.set_child(builder_box)
        box.append(builder_frame)

        # Frequency dropdown
        self._freq_model = Gtk.StringList.new([
            "Every minute",
            "Every N minutes",
            "Hourly",
            "Daily at time",
            "Weekly on selected weekdays at time",
            "Biweekly (every other week) at time",
            "Monthly on day at time",
            "One time at date/time",
        ])
        self._freq_dd = Gtk.DropDown(model=self._freq_model)
        builder_box.append(self._row("Frequency", self._freq_dd))

        # Weekday multi-select (toggle buttons Sun..Sat)
        self._weekday_buttons: list[Gtk.ToggleButton] = []
        weekdays_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for idx, name in enumerate(["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]):
            btn = Gtk.ToggleButton(label=name)
            btn.connect("toggled", self._on_builder_changed)
            btn.set_margin_end(2)
            self._weekday_buttons.append(btn)
            weekdays_box.append(btn)
        self._row_weekdays = self._row("Weekdays", weekdays_box)
        builder_box.append(self._row_weekdays)

        # Biweekly controls (apply only to Weekly mode via wrapper guard)
        self._biweekly_chk = Gtk.CheckButton.new_with_label("Run every other week (biweekly)")
        self._row_biweekly_chk = self._row("Biweekly", self._biweekly_chk)
        builder_box.append(self._row_biweekly_chk)
        self._biweekly_anchor_cal = Gtk.Calendar()
        self._row_biweekly_anchor = self._row("Biweekly anchor (week 0 start)", self._biweekly_anchor_cal)
        builder_box.append(self._row_biweekly_anchor)

        # Time selectors (for Hourly/Daily/Weekly/Monthly) — 12-hour with AM/PM
        hour_adj = Gtk.Adjustment(lower=1, upper=12, step_increment=1, page_increment=1)
        self._hour = Gtk.SpinButton(adjustment=hour_adj, climb_rate=1, digits=0)
        self._hour_end = Gtk.SpinButton(adjustment=hour_adj, climb_rate=1, digits=0)
        # Minute spin (for Hourly/Every minute)
        minute_adj = Gtk.Adjustment(lower=0, upper=59, step_increment=1, page_increment=1)
        self._minute = Gtk.SpinButton(adjustment=minute_adj, climb_rate=1, digits=0)
        # 15-minute dropdowns for start/end minutes in windowed modes
        self._min15_model = Gtk.StringList.new(["00","15","30","45"])
        self._start_min_dd = Gtk.DropDown(model=self._min15_model)
        self._end_min_dd = Gtk.DropDown(model=self._min15_model)
        self._start_min_dd.set_selected(0)
        self._end_min_dd.set_selected(3)
        # AM/PM dropdowns
        self._ampm_model = Gtk.StringList.new(["AM", "PM"])
        self._ampm = Gtk.DropDown(model=self._ampm_model)
        self._ampm_end = Gtk.DropDown(model=self._ampm_model)
        self._ampm.set_selected(0)
        self._ampm_end.set_selected(0)
        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        time_box.append(Gtk.Label(label="Start hour"))
        time_box.append(self._hour)
        time_box.append(self._ampm)
        time_box.append(Gtk.Label(label="End hour"))
        time_box.append(self._hour_end)
        time_box.append(self._ampm_end)
        time_box.append(Gtk.Label(label="Start minute"))
        time_box.append(self._start_min_dd)
        time_box.append(Gtk.Label(label="End minute"))
        time_box.append(self._end_min_dd)
        self._row_time_window = self._row("Legacy time row (hidden)", time_box)
        self._row_time_window.set_visible(False)
        builder_box.append(self._row_time_window)

        # Day of month selector for Monthly
        dom_adj = Gtk.Adjustment(lower=1, upper=31, step_increment=1, page_increment=5)
        self._dom = Gtk.SpinButton(adjustment=dom_adj, climb_rate=1, digits=0)
        self._dom.set_value(1)
        self._row_dom = self._row("Day of month", self._dom)
        builder_box.append(self._row_dom)

        # One-time date selector
        self._once_cal = Gtk.Calendar()
        self._row_once = self._row("One-time date", self._once_cal)
        builder_box.append(self._row_once)

        # N minutes interval
        n_adj = Gtk.Adjustment(lower=1, upper=59, step_increment=1, page_increment=5)
        self._n_minutes = Gtk.SpinButton(adjustment=n_adj, climb_rate=1, digits=0)
        self._row_every_n = self._row("N (minutes)", self._n_minutes)
        builder_box.append(self._row_every_n)

        # Human-readable start/end dropdowns in 15-min increments for Every-N mode
        def _fmt_time(i: int) -> str:
            h = i // 4
            m = (i % 4) * 15
            ampm = "AM" if h < 12 else "PM"
            h12 = h % 12
            if h12 == 0:
                h12 = 12
            return f"{h12:02d}:{m:02d} {ampm}"

        self._time_opts = Gtk.StringList.new([_fmt_time(i) for i in range(96)])
        self._start_dd = Gtk.DropDown(model=self._time_opts)
        self._end_dd = Gtk.DropDown(model=self._time_opts)
        # Defaults: 12:00 AM to 11:45 PM
        self._start_dd.set_selected(0)
        self._end_dd.set_selected(95)
        en_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        en_box.append(Gtk.Label(label="Start"))
        en_box.append(self._start_dd)
        en_box.append(Gtk.Label(label="End"))
        en_box.append(self._end_dd)
        self._row_en_window = self._row("Time window", en_box)
        builder_box.append(self._row_en_window)

        # Optional constraints (timezone + date range)
        # Enable/disable optional constraints
        self._constraints_chk = Gtk.CheckButton.new_with_label("Enable optional constraints (timezone & date range)")
        box.append(self._constraints_chk)

        self._advanced_frame = Gtk.Frame()
        self._advanced_frame.set_label("Optional constraints")
        adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        self._advanced_frame.set_child(adv_box)
        box.append(self._advanced_frame)

        # Timezone dropdown (basic list)
        self._tz_model = Gtk.StringList.new([
            "System default",
            "UTC",
            "America/New_York",
            "America/Los_Angeles",
            "Europe/London",
            "Europe/Berlin",
            "Asia/Tokyo",
        ])
        self._tz_dd = Gtk.DropDown(model=self._tz_model)
        adv_box.append(self._row("Timezone", self._tz_dd))

        # Date range
        dates_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._start_cal = Gtk.Calendar()
        self._end_cal = Gtk.Calendar()
        dates_box.append(self._col("Start date", self._start_cal))
        dates_box.append(self._col("End date", self._end_cal))
        adv_box.append(dates_box)

        # Cron preview (editable)
        self._cron_entry = Gtk.Entry(placeholder_text="Cron expression, e.g. */15 * * * *")
        box.append(Gtk.Label(label="Cron expression (auto-filled, editable)"))
        box.append(self._cron_entry)

        # Preview label
        self._preview = Gtk.Label(label="")
        self._preview.set_xalign(0)
        box.append(self._preview)

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self._add_btn = self.add_button("Add", Gtk.ResponseType.OK)
        self._add_btn.set_sensitive(False)

        # Signals
        self._cron_entry.connect("changed", self._validate)
        self._command_entry.connect("changed", self._validate)
        # Builder signals
        self._freq_dd.connect("notify::selected", self._on_builder_changed)
        self._hour.connect("value-changed", self._on_builder_changed)
        self._minute.connect("value-changed", self._on_builder_changed)
        self._hour_end.connect("value-changed", self._on_builder_changed)
        self._n_minutes.connect("value-changed", self._on_builder_changed)
        self._start_dd.connect("notify::selected", self._on_builder_changed)
        self._end_dd.connect("notify::selected", self._on_builder_changed)

        # Initialize defaults
        self._freq_dd.set_selected(0)  # Every minute
        # Preselect Wed and Sat for convenience demo
        for i in (3, 6):
            self._weekday_buttons[i].set_active(True)
        self._hour.set_value(18)
        self._hour_end.set_value(23)
        self._minute.set_value(0)
        self._n_minutes.set_value(5)
        # Default timezone and constraints off by default
        self._tz_dd.set_selected(0)
        self._constraints_chk.set_active(False)
        self._advanced_frame.set_visible(False)
        # Wire constraints toggle
        self._constraints_chk.connect("toggled", lambda *_: self._advanced_frame.set_visible(self._constraints_chk.get_active()))
        self._update_builder_visibility()
        self._apply_builder_to_cron()

    # (Removed) Natural language change handler

    def _validate(self, *_):
        cmd_ok = bool(self._command_entry.get_text().strip())
        cron_ok = len(self._cron_entry.get_text().strip().split()) == 5
        self._add_btn.set_sensitive(cmd_ok and cron_ok)

    def get_values(self):
        command = self._command_entry.get_text().strip()
        cron = self._cron_entry.get_text().strip()
        description = self._desc_entry.get_text().strip()
        # Gather optional constraints
        constraints_enabled = bool(self._constraints_chk.get_active())
        if constraints_enabled:
            tz = self._tz_model.get_string(self._tz_dd.get_selected()) or "System default"
            # Calendar returns year, month (0-based), day
            y1, m1, d1 = self._start_cal.get_date()
            y2, m2, d2 = self._end_cal.get_date()
            extra = {
                "constraints_enabled": True,
                "timezone": tz,
                "start_date": f"{y1:04d}-{m1+1:02d}-{d1:02d}",
                "end_date": f"{y2:04d}-{m2+1:02d}-{d2:02d}",
            }
        else:
            extra = {"constraints_enabled": False}
        if description:
            extra["description"] = description
        # Include biweekly settings if applicable (Biweekly option only)
        sel = self._freq_dd.get_selected()
        if sel == 5:
            extra["biweekly"] = True
            y, m, d = self._biweekly_anchor_cal.get_date()
            extra["biweekly_anchor"] = f"{y:04d}-{m+1:02d}-{d:02d}"
        # Include one-time settings (use Start dropdown for time)
        if sel == 7:
            extra["one_time"] = True
            y, m, d = self._once_cal.get_date()
            idx = int(self._start_min_dd.get_selected())
            # If Start/End dropdowns represent full day timeline, compute hour/min from index
            # Our model encodes 0..95 for Every-N mode; for unified use we map selected to 0,15,30,45 minutes at current hour selection via index*15
            # Here, we interpret Start selection as absolute in day: assume 0..95 mapping if available; fallback to 0..3 for minutes in current hour
            try:
                # If the dropdown has 96 entries, treat as absolute; else map 0..3 to 0,15,30,45 at hour from cron text (we'll just use 0-based hour)
                if hasattr(self._time_opts, 'get_n_items') and self._time_opts.get_n_items() == 96:
                    s_idx = int(self._start_dd.get_selected())
                    hh = s_idx // 4
                    mm = (s_idx % 4) * 15
                else:
                    # Fallback to current minute choice and 0 hour
                    hh = 0
                    mm = [0,15,30,45][idx if 0 <= idx <= 3 else 0]
            except Exception:
                hh = 0
                mm = 0
            extra["one_time_at"] = f"{y:04d}-{m+1:02d}-{d:02d}T{hh:02d}:{mm:02d}"
        return command, cron, extra

    def _col(self, title: str, widget: Gtk.Widget) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(Gtk.Label(label=title, xalign=0))
        box.append(widget)
        return box

    # UI helpers
    def _row(self, title: str, widget: Gtk.Widget) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(Gtk.Label(label=title, xalign=0))
        box.append(widget)
        return box

    # Prefill values when editing an existing job
    def set_initial(self, command: str, cron: str, description: str | None = None) -> None:
        self._command_entry.set_text(command)
        if cron:
            self._cron_entry.set_text(cron)
        if description:
            self._desc_entry.set_text(description)
        # Do not try to reverse-parse cron fully into builder; just validate
        try:
            self._suppress_builder = True
            self._apply_cron_to_builder(cron)
        finally:
            self._suppress_builder = False
        self._validate()

    def set_mode_edit(self) -> None:
        """Switch labels to reflect Edit mode."""
        try:
            self.set_title("Edit Job")
        except Exception:
            pass
        try:
            # Change the OK button label to 'Save'
            self._add_btn.set_label("Save")
        except Exception:
            pass

    def _on_builder_changed(self, *_):
        if self._suppress_builder:
            return
        self._update_builder_visibility()
        self._apply_builder_to_cron()
        self._validate()

    def _update_builder_visibility(self) -> None:
        sel = self._freq_dd.get_selected()
        # Visibility rules
        every_minute = (sel == 0)
        every_n = (sel == 1)
        hourly = (sel == 2)
        daily = (sel == 3)
        weekly = (sel == 4) or (sel == 5)
        biweekly = (sel == 5)
        monthly = (sel == 6)
        onetime = (sel == 7)
        # Rows visibility — show only what applies to the selected frequency
        self._row_weekdays.set_visible(weekly or every_n or hourly)
        self._row_time_window.set_visible(False)
        self._row_every_n.set_visible(every_n)
        self._row_en_window.set_visible(daily or weekly or monthly or onetime or every_n or hourly)
        self._row_dom.set_visible(monthly)
        self._row_biweekly_chk.set_visible(False)  # no longer used; keep hidden
        self._row_biweekly_anchor.set_visible(biweekly)
        self._row_once.set_visible(onetime)
        # Hide legacy hour/AMPM widgets; grid controls are source of truth
        self._hour.set_visible(False)
        self._ampm.set_visible(False)
        self._hour_end.set_visible(False)
        self._ampm_end.set_visible(False)
        self._minute.set_visible(every_minute)
        # Hide 15-min minute dropdowns; the 24h Start/End grid is the source of truth
        self._start_min_dd.set_visible(False)
        self._end_min_dd.set_visible(False)
        # Inner widgets: 24h grid always visible when time window row is visible
        self._n_minutes.set_visible(every_n)
        self._start_dd.set_visible(daily or weekly or monthly or onetime or every_n or hourly)
        # End time only relevant for Every N minutes and Hourly; others are single-time
        self._end_dd.set_visible(every_n or hourly)
        # Inner calendars visibility (row visibility already controls labels)
        self._biweekly_anchor_cal.set_visible(biweekly)
        self._once_cal.set_visible(onetime)

    def _apply_builder_to_cron(self) -> None:
        sel = self._freq_dd.get_selected()
        # Derive times from 15-min Start/End dropdowns when applicable
        # For Every-N we already have absolute indices in _start_dd/_end_dd over 24h
        # For other modes we also use _start_dd/_end_dd if available, otherwise map minute-only
        h = int(self._hour.get_value())  # retained for Hourly/Every minute
        h2 = int(self._hour_end.get_value())
        if sel == 0:
            m = int(self._minute.get_value())
        else:
            s_idx = int(self._start_dd.get_selected())
            e_idx = int(self._end_dd.get_selected())
            s_h, s_m = (s_idx // 4, (s_idx % 4) * 15)
            e_h, e_m = (e_idx // 4, (e_idx % 4) * 15)
            m = s_m
        n = int(self._n_minutes.get_value())
        # Collect selected weekdays (0=Sun..6=Sat)
        dows = [str(i) for i, btn in enumerate(self._weekday_buttons) if btn.get_active()]
        dow_field = ",".join(dows) if dows else "*"
        if sel == 0:  # Every minute
            cron = "* * * * *"
        elif sel == 1:  # Every N minutes with human-readable window and optional DOWs
            n = max(1, min(59, n))
            # Map dropdowns to hour range; minute offsets aren't compatible with */N in plain cron
            s_idx = int(self._start_dd.get_selected())
            e_idx = int(self._end_dd.get_selected())
            s_h, s_m = (s_idx // 4, (s_idx % 4) * 15)
            e_h, e_m = (e_idx // 4, (e_idx % 4) * 15)
            hour_field = f"{s_h}-{e_h}" if e_h >= s_h else "*"
            cron = f"*/{n} {hour_field} * * {dow_field}"
            # If a non-zero start minute was chosen, inform user in preview that cron alignment is on :00
            if s_m != 0 or e_m != 45:
                self._preview.set_text("Note: Cron runs every N minutes aligned to :00; minute offsets in window are not represented.")
        elif sel == 2:  # Hourly within time window at start-minute, with weekdays
            hour_field = f"{s_h}-{e_h}" if e_h >= s_h else str(s_h)
            cron = f"{m} {hour_field} * * {dow_field}"
        elif sel == 3:  # Daily at start time (single hour)
            cron = f"{m} {s_h} * * *"
        elif sel == 4 or sel == 5:  # Weekly/Biweekly at start time (single hour)
            cron = f"{m} {s_h} * * {dow_field}"
        elif sel == 6:  # Monthly at start time (single hour)
            dom = max(1, min(31, int(self._dom.get_value())))
            cron = f"{m} {s_h} {dom} * *"
        elif sel == 7:  # One-time: run daily at selected start time; wrapper guard enforces the exact date/time
            cron = f"{m} {s_h} * * *"
        else:
            cron = "* * * * *"
        # Update cron entry without triggering recursion
        self._cron_entry.set_text(cron)

    def _apply_cron_to_builder(self, cron: str) -> None:
        """Best-effort sync from a 5-field cron into builder controls."""
        parts = cron.strip().split()
        if len(parts) != 5:
            return
        minute, hour, dom, mon, dow = parts
        # Defaults
        self._freq_dd.set_selected(0)
        for btn in self._weekday_buttons:
            btn.set_active(False)
        self._hour.set_value(0)
        self._hour_end.set_value(0)
        self._minute.set_value(0)
        self._n_minutes.set_value(5)
        # Weekly with hour window and selected DOWs
        def set_dows(dow_field: str):
            if dow_field == "*":
                return
            for token in dow_field.split(','):
                if token.isdigit():
                    idx = int(token)
                    if 0 <= idx <= 6:
                        self._weekday_buttons[idx].set_active(True)
        # Hour range helper
        def set_hour_window(hfield: str):
            if '-' in hfield:
                try:
                    s, e = hfield.split('-', 1)
                    self._hour.set_value(int(s))
                    self._hour_end.set_value(int(e))
                except Exception:
                    pass
            elif hfield == '*':
                self._hour.set_value(0)
                self._hour_end.set_value(0)
            else:
                try:
                    v = int(hfield)
                    self._hour.set_value(v)
                    self._hour_end.set_value(v)
                except Exception:
                    pass
        # Detect */N minutes (optionally hour range and DOW list)
        if minute.startswith('*/') and dom == '*' and mon == '*':
            try:
                n = int(minute[2:])
                self._freq_dd.set_selected(1)  # Every N minutes
                self._n_minutes.set_value(max(1, min(59, n)))
                # Set dropdown window to hours only (minutes align to :00)
                if '-' in hour:
                    s,e = hour.split('-',1)
                    s = int(s); e = int(e)
                    self._start_dd.set_selected(max(0, min(95, s*4)))
                    self._end_dd.set_selected(max(0, min(95, e*4 + 3)))
                elif hour == '*':
                    self._start_dd.set_selected(0)
                    self._end_dd.set_selected(95)
                set_dows(dow)
            except Exception:
                pass
        # Hourly pattern m * * * *
        elif hour == '*' and dom == '*' and mon == '*' and dow == '*':
            try:
                m = int(minute) if minute != '*' else 0
                self._freq_dd.set_selected(2)
                self._minute.set_value(m)
            except Exception:
                pass
        # Daily m H or H-H2
        elif dom == '*' and mon == '*' and dow == '*':
            self._freq_dd.set_selected(3)
            try:
                self._minute.set_value(int(minute))
            except Exception:
                pass
            # Also sync 15-minute dropdown to closest value
            try:
                mv = int(minute)
                sel_idx = 0 if mv < 8 else 1 if mv < 23 else 2 if mv < 38 else 3
                self._start_min_dd.set_selected(sel_idx)
            except Exception:
                pass
            # Parse H or H-H2 in 24h to 12h controls
            def set_hour_window_12(hfield: str):
                def from24(hv: int):
                    ampm_idx = 0 if hv < 12 else 1
                    h12 = hv % 12
                    if h12 == 0:
                        h12 = 12
                    return h12, ampm_idx
                if '-' in hfield:
                    try:
                        s, e = hfield.split('-', 1)
                        s = int(s); e = int(e)
                        hs, ams = from24(s)
                        he, ame = from24(e)
                        self._hour.set_value(hs)
                        self._ampm.set_selected(ams)
                        self._hour_end.set_value(he)
                        self._ampm_end.set_selected(ame)
                    except Exception:
                        pass
                elif hfield == '*':
                    self._hour.set_value(12)
                    self._ampm.set_selected(0)
                    self._hour_end.set_value(12)
                    self._ampm_end.set_selected(0)
                else:
                    try:
                        v = int(hfield)
                        hv, ap = from24(v)
                        self._hour.set_value(hv)
                        self._ampm.set_selected(ap)
                        self._hour_end.set_value(hv)
                        self._ampm_end.set_selected(ap)
                    except Exception:
                        pass
            set_hour_window_12(hour)
        # Monthly m H dom
        elif dom != '*' and mon == '*' and dow == '*':
            self._freq_dd.set_selected(6)
            try:
                self._minute.set_value(int(minute))
            except Exception:
                pass
            set_hour_window(hour)
            try:
                self._dom.set_value(int(dom))
            except Exception:
                pass
        # Weekly m H dowlist (fallback)
        else:
            self._freq_dd.set_selected(4)
            try:
                self._minute.set_value(int(minute))
            except Exception:
                pass
            # Also sync 15-minute dropdown to closest value
            try:
                mv = int(minute)
                sel_idx = 0 if mv < 8 else 1 if mv < 23 else 2 if mv < 38 else 3
                self._start_min_dd.set_selected(sel_idx)
            except Exception:
                pass
            # Reuse 12h conversion for weekly, same format as daily hour field
            def set_hour_window_12(hfield: str):
                def from24(hv: int):
                    ampm_idx = 0 if hv < 12 else 1
                    h12 = hv % 12
                    if h12 == 0:
                        h12 = 12
                    return h12, ampm_idx
                if '-' in hfield:
                    try:
                        s, e = hfield.split('-', 1)
                        s = int(s); e = int(e)
                        hs, ams = from24(s)
                        he, ame = from24(e)
                        self._hour.set_value(hs)
                        self._ampm.set_selected(ams)
                        self._hour_end.set_value(he)
                        self._ampm_end.set_selected(ame)
                    except Exception:
                        pass
                elif hfield == '*':
                    self._hour.set_value(12)
                    self._ampm.set_selected(0)
                    self._hour_end.set_value(12)
                    self._ampm_end.set_selected(0)
                else:
                    try:
                        v = int(hfield)
                        hv, ap = from24(v)
                        self._hour.set_value(hv)
                        self._ampm.set_selected(ap)
                        self._hour_end.set_value(hv)
                        self._ampm_end.set_selected(ap)
                    except Exception:
                        pass
            set_hour_window_12(hour)
            set_dows(dow)
        self._update_builder_visibility()
