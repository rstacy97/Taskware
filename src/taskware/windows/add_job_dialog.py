import gi
from taskware.utils.nl2cron import nl_to_cron_with_suggestions, nl_to_cron_and_extras

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib, Gdk


class AddJobDialog(Gtk.Dialog):
    def __init__(self, parent: Adw.ApplicationWindow):
        super().__init__(transient_for=parent, modal=True, use_header_bar=True)
        self.set_title("Add New Job")
        self.set_default_size(640, 700)
        self._suppress_builder = False

        # Gently delay tooltips so they don't pop immediately on hover
        try:
            settings = Gtk.Settings.get_default()
            if settings is not None and hasattr(settings.props, "gtk_tooltip_timeout"):
                # milliseconds; ~1.5 second delay
                settings.props.gtk_tooltip_timeout = 1500
        except Exception:
            pass

        # Root: single column layout (no side panel to avoid layout issues)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.get_content_area().append(box)

        # Optional description
        self._desc_entry = Gtk.Entry(placeholder_text="Optional description, e.g. Nightly DB backup")
        box.append(Gtk.Label(label="Description (optional)"))
        box.append(self._desc_entry)

        # Natural language schedule (smarter parsing with suggestions)
        self._nl_entry = Gtk.Entry(placeholder_text="e.g. every monday at 6 pm, every 15 minutes, daily at 02:30")
        box.append(Gtk.Label(label="Natural language schedule (optional)"))
        box.append(self._nl_entry)
        # Suggestions area
        self._sugg_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.append(self._sugg_box)

        # Command entry with inline templates menu button
        box.append(Gtk.Label(label="Command"))
        cmd_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._command_entry = Gtk.Entry(placeholder_text="Command to run, e.g. /usr/bin/backup --quick")
        self._command_entry.set_hexpand(True)
        cmd_row.append(self._command_entry)
        # Menu button with templates
        self._cmd_menu_btn = Gtk.MenuButton()
        try:
            # Use a down arrow style icon; fallback to text arrow if unavailable
            self._cmd_menu_btn.set_icon_name("pan-down-symbolic")
        except Exception:
            try:
                self._cmd_menu_btn.set_label("▼")
            except Exception:
                self._cmd_menu_btn.set_label("Templates")
        # Build popover with template buttons
        self._cmd_pop = Gtk.Popover()
        tmpl_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        templates = [
            "/usr/bin/echo 'Hello from Taskware'",
            "/usr/bin/notify-send 'Taskware' 'Scheduled job ran'",
            "/usr/bin/rsync -av --dry-run ~/Documents/ /path/to/backup/Documents/",
            "/usr/bin/find ~/Downloads -type f -name '*.tmp' -mtime +7 -print",
            "/usr/bin/curl -fsSL https://example.com/health || exit 1",
            "/usr/bin/python3 /path/to/script.py",
            "/usr/bin/bash -lc 'date >> ~/taskware_run.log'",
        ]
        template_tooltips = {
            "/usr/bin/echo 'Hello from Taskware'": "Simple test command that prints a message to stdout.",
            "/usr/bin/notify-send 'Taskware' 'Scheduled job ran'": "Desktop notification to confirm the job ran (requires notify-send).",
            "/usr/bin/rsync -av --dry-run ~/Documents/ /path/to/backup/Documents/": "Preview rsync of Documents to backup (dry-run, no changes; note trailing slashes).",
            "/usr/bin/find ~/Downloads -type f -name '*.tmp' -mtime +7 -print": "List .tmp files older than 7 days in Downloads (non-destructive).",
            "/usr/bin/curl -fsSL https://example.com/health || exit 1": "Perform an HTTP health check; fail the job if the endpoint is unhealthy.",
            "/usr/bin/python3 /path/to/script.py": "Run a Python script (replace with your script's path).",
            "/usr/bin/bash -lc 'date >> ~/taskware_run.log'": "Append the current date to a log file in your home directory.",
        }
        for tpl in templates:
            b = Gtk.Button.new_with_label(tpl)
            b.set_halign(Gtk.Align.FILL)
            b.set_hexpand(True)
            try:
                desc = template_tooltips.get(tpl)
                if desc:
                    b.set_tooltip_text(desc)
            except Exception:
                pass
            def _on_tpl_clicked(_btn, text=tpl):
                self._command_entry.set_text(text)
                try:
                    self._cmd_pop.popdown()
                except Exception:
                    pass
                self._validate()
            b.connect("clicked", _on_tpl_clicked)
            tmpl_box.append(b)
        self._cmd_pop.set_child(tmpl_box)
        self._cmd_menu_btn.set_popover(self._cmd_pop)
        cmd_row.append(self._cmd_menu_btn)
        # AI button: open helper in a small external window (Firefox preferred)
        AI_URL = "https://chatgpt.com/g/g-68d2f08efca88191957b61fd0237124c-taskware-cron-command-generator"
        self._ai_btn = Gtk.Button.new_with_label("AI")
        self._ai_btn.set_tooltip_text("Open AI assistant to generate cron commands")
        self._ai_btn.connect("clicked", lambda *_: self._open_ai_external(AI_URL))
        cmd_row.append(self._ai_btn)
        box.append(cmd_row)

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
        # Time window enable checkbox (applies to Every N minutes and Hourly)
        self._window_chk = Gtk.CheckButton.new_with_label("Limit to time window")
        self._window_chk.set_active(False)
        self._window_chk.connect("toggled", self._on_builder_changed)
        en_box.append(self._window_chk)
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
        # Connect NL parser after UI is ready
        self._nl_entry.connect("changed", self._on_nl_changed)
        self._nl_extras: dict[str, object] = {}
        self._apply_builder_to_cron()

    # (Removed) Natural language change handler

    def _validate(self, *_):
        cmd_ok = bool(self._command_entry.get_text().strip())
        cron_ok = len(self._cron_entry.get_text().strip().split()) == 5
        self._add_btn.set_sensitive(cmd_ok and cron_ok)

    def _on_nl_changed(self, *_):
        text = self._nl_entry.get_text().strip()
        cron, extras, suggestions = (nl_to_cron_and_extras(text) if text else (None, {}, []))
        # Clear previous suggestions
        for child in list(self._sugg_box):
            self._sugg_box.remove(child)
        if cron:
            # Apply parsed cron
            self._cron_entry.set_text(cron)
            # If extras specify a frequency context, set it before applying cron
            # Decide target frequency index:
            # 0=Every minute,1=Every N,2=Hourly,3=Daily,4=Weekly,5=Biweekly,6=Monthly,7=One-time
            target_sel = None
            if extras.get("day_of_month") is not None:
                target_sel = 6  # Monthly
            elif extras.get("weekday") is not None and extras.get("biweekly"):
                target_sel = 5  # Biweekly
            elif extras.get("weekday") is not None:
                target_sel = 4  # Weekly
            elif extras.get("hour") is not None:
                target_sel = 3  # Daily (single time)
            if target_sel is not None:
                try:
                    self._freq_dd.set_selected(target_sel)
                except Exception:
                    pass
            # Update time/weekday/day-of-month controls from extras when available
            try:
                if "hour" in extras and "minute" in extras and hasattr(self, "_start_dd"):
                    h = max(0, min(23, int(extras["hour"])) )
                    m = max(0, min(59, int(extras["minute"])) )
                    m = (m // 15) * 15
                    self._start_dd.set_selected(h * 4 + (m // 15))
                if "weekday" in extras and hasattr(self, "_weekday_buttons"):
                    # Clear all then set selected
                    for i, btn in enumerate(self._weekday_buttons):
                        btn.set_active(i == int(extras["weekday"]))
                if "day_of_month" in extras and hasattr(self, "_dom"):
                    self._dom.set_value(int(extras["day_of_month"]))
            except Exception:
                pass
            # Apply cron to builder to ensure consistency
            self._apply_cron_to_builder(cron)
            # Stash extras (e.g., biweekly) for submit
            self._nl_extras = extras or {}
            # If NL indicates biweekly, enforce Biweekly selection (index 5)
            try:
                if bool(self._nl_extras.get("biweekly")):
                    self._freq_dd.set_selected(5)
            except Exception:
                pass
            self._validate()
            return
        # No cron parsed; apply extras-only hints if present (weekday/biweekly), else clear
        self._nl_extras = extras or {}
        if self._nl_extras.get("weekday") is not None or self._nl_extras.get("weekdays") is not None:
            target_sel = 5 if self._nl_extras.get("biweekly") else 4
            try:
                self._freq_dd.set_selected(target_sel)
            except Exception:
                pass
            try:
                # Clear all
                for btn in self._weekday_buttons:
                    btn.set_active(False)
                if self._nl_extras.get("weekdays") is not None:
                    for idx in (self._nl_extras.get("weekdays") or []):
                        if isinstance(idx, int) and 0 <= idx <= 6:
                            self._weekday_buttons[idx].set_active(True)
                else:
                    idx = int(self._nl_extras["weekday"]) or 0
                    if 0 <= idx <= 6:
                        self._weekday_buttons[idx].set_active(True)
            except Exception:
                pass
            # With frequency/weekday set, rebuild cron from current grid/time
            self._apply_builder_to_cron()
            # Re-enforce Biweekly selection if indicated
            try:
                if bool(self._nl_extras.get("biweekly")):
                    self._freq_dd.set_selected(5)
            except Exception:
                pass
            self._validate()
        # Even without a full parse, try to set context (frequency) and time from keywords
        lower = text.lower()
        target_sel = None
        # Biweekly synonyms
        if any(kw in lower for kw in ("biweekly", "bi-weekly", "every other week", "every 2 weeks", "every two weeks")):
            target_sel = 5
        # Monthly synonyms
        elif any(kw in lower for kw in ("monthly", "every month")):
            target_sel = 6
        # Weekly
        elif "weekly" in lower or "every week" in lower:
            target_sel = 4
        # Daily / Hourly
        elif "daily" in lower or "every day" in lower:
            target_sel = 3
        elif "hourly" in lower or "every hour" in lower:
            target_sel = 2
        if target_sel is not None:
            try:
                self._freq_dd.set_selected(target_sel)
            except Exception:
                pass
        # Parse an 'at <time>' snippet and update Start time
        import re as _re
        m = _re.search(r"\bat\s+((?:[0-9]{1,2}(?::[0-9]{2})?\s*(?:a|p|am|pm)?)|(?:[0-9]{1,2}:[0-9]{2})|noon|midnight)\b", lower)
        if m and hasattr(self, "_start_dd"):
            t = m.group(1).strip()
            # simple time parse
            h = None; minute = 0
            m2 = None
            if t == "noon":
                h = 12; minute = 0
            elif t == "midnight":
                h = 0; minute = 0
            else:
                m2 = _re.match(r"^(\d{1,2}):(\d{2})$", t)
            if m2 is not None:
                h = int(m2.group(1)); minute = int(m2.group(2))
            else:
                m3 = _re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(a|p|am|pm)$", t)
                if m3:
                    h = int(m3.group(1)); minute = int(m3.group(2) or 0)
                    ap = m3.group(3)
                    if ap == "a":
                        ap = "am"
                    elif ap == "p":
                        ap = "pm"
                    if 1 <= h <= 12:
                        if ap == "pm" and h != 12:
                            h += 12
                        if ap == "am" and h == 12:
                            h = 0
                else:
                    m4 = _re.match(r"^(\d{1,2})$", t)
                    if m4:
                        h = int(m4.group(1))
            if h is not None and 0 <= h <= 23 and 0 <= minute < 60:
                minute = (minute // 15) * 15
                try:
                    self._start_dd.set_selected(h * 4 + (minute // 15))
                except Exception:
                    pass
        # If no 'at <time>' form matched, still accept bare 'noon' or 'midnight' anywhere
        if ("noon" in lower or "midnight" in lower) and hasattr(self, "_start_dd"):
            try:
                h = 12 if "noon" in lower else 0
                minute = 0
                self._start_dd.set_selected(h * 4 + (minute // 15))
            except Exception:
                pass
        # Also accept standalone compact times like '5a', '7:15p', '5pm', '07:30'
        if hasattr(self, "_start_dd"):
            tmatch = _re.search(r"\b(\d{1,2}(:\d{2})?\s*(?:a|p|am|pm)|\d{1,2}:\d{2})\b", lower)
            if tmatch:
                t = tmatch.group(1).strip()
                h = None; minute = 0
                if t == "noon":
                    h = 12; minute = 0
                elif t == "midnight":
                    h = 0; minute = 0
                else:
                    m2 = _re.match(r"^(\d{1,2}):(\d{2})$", t)
                    if m2:
                        h = int(m2.group(1)); minute = int(m2.group(2))
                    else:
                        m3 = _re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(a|p|am|pm)$", t)
                        if m3:
                            h = int(m3.group(1)); minute = int(m3.group(2) or 0)
                            ap = m3.group(3)
                            if ap == "a": ap = "am"
                            if ap == "p": ap = "pm"
                            if 1 <= h <= 12:
                                if ap == "pm" and h != 12:
                                    h += 12
                                if ap == "am" and h == 12:
                                    h = 0
                if h is not None and 0 <= h <= 23 and 0 <= minute < 60:
                    minute = (minute // 15) * 15
                    try:
                        self._start_dd.set_selected(h * 4 + (minute // 15))
                    except Exception:
                        pass
        # Weekday words (support multiple)
        wd_map = {"sun":0,"sunday":0,"sundays":0,
                  "mon":1,"monday":1,"mondays":1,
                  "tue":2,"tues":2,"tuesday":2,"tuesdays":2,
                  "wed":3,"wednesday":3,"wednesdays":3,
                  "thu":4,"thur":4,"thurs":4,"thursday":4,"thursdays":4,
                  "fri":5,"friday":5,"fridays":5,
                  "sat":6,"saturday":6,"saturdays":6}
        if hasattr(self, "_weekday_buttons"):
            tokens = [t.strip() for t in lower.replace(","," ").replace(" and ", " ").split() if t.strip()]
            selected = {wd_map[t] for t in tokens if t in wd_map}
            if selected:
                # If any weekdays detected, ensure weekly frequency unless already set to biweekly
                if self._freq_dd.get_selected() not in (4, 5):
                    self._freq_dd.set_selected(4)
                for i, btn in enumerate(self._weekday_buttons):
                    btn.set_active(i in selected)
        # Show suggestion buttons if any
        for sug in suggestions[:3]:
            btn = Gtk.Button.new_with_label(sug)
            def on_click(_b, phrase=sug):
                self._nl_entry.set_text(phrase)
            btn.connect("clicked", on_click)
            self._sugg_box.append(btn)

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
        # Merge any extras provided by NLP
        if getattr(self, "_nl_extras", None):
            try:
                extra.update(self._nl_extras)
            except Exception:
                pass
        return command, cron, extra

    def _open_ai_external(self, url: str) -> None:
        """Open the URL in a new browser window sized for chat.
        Prefers Chromium-family app mode for reliable sizing; then Firefox with size hints.
        This helper does not touch any scheduler UI.
        """
        # Desired size
        W, H = 686, 765
        # Compute a right-edge position when possible
        pos_x, pos_y = 100, 120
        try:
            display = Gdk.Display.get_default()
            if display:
                monitor = display.get_primary_monitor() or display.get_monitor(0)
                if monitor:
                    geo = monitor.get_geometry()
                    # Place near right edge with small margin
                    pos_x = max(0, geo.x + geo.width - W - 24)
                    pos_y = max(0, geo.y + 120)
        except Exception:
            pass
        # Prefer Chromium-family with app mode for stable sizing
        try:
            for bin_name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser"):
                if GLib.find_program_in_path(bin_name):
                    argv = [
                        bin_name,
                        "--new-window",
                        f"--app={url}",
                        f"--window-size={W},{H}",
                        f"--window-position={pos_x},{pos_y}",
                    ]
                    Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
                    # Post-position on X11 if wmctrl is present (some WMs ignore flags)
                    if GLib.getenv("XDG_SESSION_TYPE") == "x11" and GLib.find_program_in_path("wmctrl"):
                        try:
                            # Try common classes
                            classes = [
                                "chromium.Chromium",
                                "google-chrome.Google-chrome",
                                "brave-browser.Brave-browser",
                            ]
                            for cls in classes:
                                Gio.Subprocess.new([
                                    "bash","-lc",
                                    f"sleep 0.5; wmctrl -x -r {cls} -e 0,{pos_x},{pos_y},{W},{H} || true"
                                ], Gio.SubprocessFlags.NONE)
                        except Exception:
                            pass
                    return
        except Exception:
            pass
        # Firefox with size hints; may be ignored by some Wayland sessions
        try:
            if GLib.find_program_in_path("firefox"):
                Gio.Subprocess.new(["firefox", "--new-window", url, "--width", str(W), "--height", str(H)], Gio.SubprocessFlags.NONE)
                # Best-effort resize on X11 via wmctrl if available
                if GLib.find_program_in_path("wmctrl"):
                    try:
                        Gio.Subprocess.new([
                            "bash",
                            "-lc",
                            f"sleep 0.8; wmctrl -x -r firefox.Firefox -b remove,maximized_vert,maximized_horz; wmctrl -x -r firefox.Firefox -e 0,{pos_x},{pos_y},{W},{H}",
                        ], Gio.SubprocessFlags.NONE)
                    except Exception:
                        pass
                return
        except Exception:
            pass
        # Fallback
        try:
            Gio.AppInfo.launch_default_for_uri(url)
        except Exception:
            pass

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
        self._row_en_window.set_visible(daily or weekly or monthly or onetime or every_n or hourly or every_minute)
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
        self._start_dd.set_visible(daily or weekly or monthly or onetime or every_n or hourly or every_minute)
        # Window checkbox relevant for Every minute, Every N minutes and Hourly
        self._window_chk.set_visible(every_minute or every_n or hourly)
        # End time relevant for Every minute, Every N minutes and Hourly; others are single-time
        self._end_dd.set_visible(every_minute or every_n or hourly)
        # Enable/disable Start/End based on checkbox for applicable modes
        use_window = self._window_chk.get_active() if (every_minute or every_n or hourly) else True
        self._start_dd.set_sensitive(True if (daily or weekly or monthly or onetime) else use_window)
        self._end_dd.set_sensitive(use_window)
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
            # If time window is enabled, restrict hours; otherwise all hours
            if self._window_chk.get_active():
                s_idx = int(self._start_dd.get_selected())
                e_idx = int(self._end_dd.get_selected())
                s_h, s_m = (s_idx // 4, (s_idx % 4) * 15)
                e_h, e_m = (e_idx // 4, (e_idx % 4) * 15)
                hour_field = f"{s_h}-{e_h}" if e_h >= s_h else "*"
                cron = f"* {hour_field} * * *"
            else:
                cron = "* * * * *"
        elif sel == 1:  # Every N minutes with human-readable window and optional DOWs
            n = max(1, min(59, n))
            # Map dropdowns to hour range; minute offsets aren't compatible with */N in plain cron
            s_idx = int(self._start_dd.get_selected())
            e_idx = int(self._end_dd.get_selected())
            s_h, s_m = (s_idx // 4, (s_idx % 4) * 15)
            e_h, e_m = (e_idx // 4, (e_idx % 4) * 15)
            # Apply window only if enabled; otherwise full day
            if self._window_chk.get_active():
                hour_field = f"{s_h}-{e_h}" if e_h >= s_h else "*"
            else:
                hour_field = "*"
            cron = f"*/{n} {hour_field} * * {dow_field}"
            # If a non-zero start minute was chosen, inform user in preview that cron alignment is on :00
            if s_m != 0 or e_m != 45:
                self._preview.set_text("Note: Cron runs every N minutes aligned to :00; minute offsets in window are not represented.")
        elif sel == 2:  # Hourly within time window at start-minute, with weekdays
            if self._window_chk.get_active():
                hour_field = f"{s_h}-{e_h}" if e_h >= s_h else str(s_h)
            else:
                hour_field = "*"
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

        def set_grid_from(minute_str: str, hour_field: str, set_end_from_range: bool = False) -> None:
            try:
                m = int(minute_str) if minute_str.isdigit() else 0
                m = (m // 15) * 15
                if '-' in hour_field:
                    hs_str, he_str = hour_field.split('-', 1)
                    hs = int(hs_str) if hs_str.isdigit() else 0
                    he = int(he_str) if he_str.isdigit() else hs
                elif hour_field == '*':
                    hs = 0; he = 0
                else:
                    hs = int(hour_field)
                    he = hs
                if hasattr(self, "_start_dd"):
                    self._start_dd.set_selected(max(0, min(95, hs * 4 + (m // 15))))
                if set_end_from_range and hasattr(self, "_end_dd"):
                    self._end_dd.set_selected(max(0, min(95, he * 4 + 3)))
            except Exception:
                pass

        def set_dows(dow_field: str) -> None:
            if dow_field == "*":
                return
            for token in dow_field.split(','):
                if token.isdigit():
                    idx = int(token)
                    if 0 <= idx <= 6:
                        self._weekday_buttons[idx].set_active(True)

        # Reset some defaults
        for btn in self._weekday_buttons:
            btn.set_active(False)

        # Every minute (all fields '*') or with hour window
        if minute == '*' and dom == '*' and mon == '*' and dow == '*':
            self._freq_dd.set_selected(0)
            if '-' in hour:
                try:
                    s, e = hour.split('-', 1)
                    s = int(s); e = int(e)
                    self._start_dd.set_selected(max(0, min(95, s * 4)))
                    self._end_dd.set_selected(max(0, min(95, e * 4 + 3)))
                    self._window_chk.set_active(True)
                except Exception:
                    pass
            elif hour == '*':
                # Full day, disable window
                self._window_chk.set_active(False)
            # nothing else to set
        # Every N minutes
        elif minute.startswith('*/') and dom == '*' and mon == '*':
            try:
                n = int(minute[2:])
                self._freq_dd.set_selected(1)
                self._n_minutes.set_value(max(1, min(59, n)))
                if '-' in hour:
                    s, e = hour.split('-', 1)
                    s = int(s); e = int(e)
                    self._start_dd.set_selected(max(0, min(95, s * 4)))
                    self._end_dd.set_selected(max(0, min(95, e * 4 + 3)))
                    self._window_chk.set_active(True)
                elif hour == '*':
                    self._start_dd.set_selected(0)
                    self._end_dd.set_selected(95)
                    self._window_chk.set_active(False)
                set_dows(dow)
            except Exception:
                pass
        # Hourly
        elif hour == '*' and dom == '*' and mon == '*' and dow == '*':
            try:
                m = int(minute) if minute != '*' else 0
                self._freq_dd.set_selected(2)
                self._minute.set_value(m)
                self._window_chk.set_active(False)
            except Exception:
                pass
        # Daily
        elif dom == '*' and mon == '*' and dow == '*':
            self._freq_dd.set_selected(3)
            set_grid_from(minute, hour)
            self._window_chk.set_active(True)
        # Monthly
        elif dom != '*' and mon == '*' and dow == '*':
            self._freq_dd.set_selected(6)
            set_grid_from(minute, hour)
            try:
                self._dom.set_value(int(dom))
            except Exception:
                pass
            self._window_chk.set_active(True)
        # Weekly / Biweekly
        else:
            try:
                is_biweekly = bool(getattr(self, "_nl_extras", {}).get("biweekly"))
            except Exception:
                is_biweekly = False
            self._freq_dd.set_selected(5 if is_biweekly else 4)
            set_grid_from(minute, hour)
            set_dows(dow)
            self._window_chk.set_active(True)

        self._update_builder_visibility()
