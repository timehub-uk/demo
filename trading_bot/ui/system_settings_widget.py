"""
System Settings Widget – Full configuration UI.

Sections:
  • Profile      – User name, timezone, currency
  • Binance      – API key/secret, testnet toggle
  • Database     – PostgreSQL host/port/name/user
  • Redis        – Host/port/password
  • AI / Voice   – Claude / ElevenLabs API keys, voice toggle
  • ML           – Training params, confidence threshold
  • Trading      – Mode, risk per trade, limits
  • Tax          – UK CGT settings, email reports
  • UI           – Accent color, font size, theme
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox,
    QGroupBox, QTabWidget, QFormLayout, QFrame, QScrollArea,
    QSizePolicy,
)

from ui.styles import (
    ACCENT, GREEN, RED, YELLOW, BG0, BG2, BG3, BG4, BG5,
    BORDER, BORDER2, FG0, FG1, FG2, GLOW,
)
from ui.icons import svg_icon


# ── Masked password line edit ─────────────────────────────────────────────────

class SecretEdit(QWidget):
    """Password field with show/hide toggle."""

    def __init__(self, placeholder: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText(placeholder)
        layout.addWidget(self.edit, 1)

        self.toggle_btn = QPushButton("👁")
        self.toggle_btn.setFixedSize(32, 32)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{ background:{BG4}; border:1px solid {BORDER}; border-radius:4px; font-size:14px; }}
            QPushButton:checked {{ border-color:{ACCENT}; }}
        """)
        self.toggle_btn.toggled.connect(self._toggle)
        layout.addWidget(self.toggle_btn)

    def _toggle(self, show: bool) -> None:
        self.edit.setEchoMode(
            QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        )

    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str) -> None:
        self.edit.setText(text)


# ── Section builder helpers ───────────────────────────────────────────────────

def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        color: {ACCENT};
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 2px;
        padding: 8px 0 4px;
        border-bottom: 1px solid {BORDER};
    """)
    return lbl


def _make_scroll(content: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidget(content)
    return scroll


# ── Settings Widget ────────────────────────────────────────────────────────────

class SystemSettingsWidget(QWidget):
    """
    Full settings panel – read from Settings singleton, write back on Save.
    """

    settings_saved = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._settings = None
        self._setup_ui()
        self._load()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ─────────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setFixedHeight(52)
        hdr.setStyleSheet(f"background:{BG0}; border-bottom:1px solid {BORDER};")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(20, 0, 20, 0)

        title = QLabel("SYSTEM CONFIGURATION")
        title.setStyleSheet(f"color:{ACCENT}; font-size:13px; font-weight:700; letter-spacing:3px;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()

        self.save_btn = QPushButton("  Save All Changes")
        self.save_btn.setObjectName("btn_primary")
        self.save_btn.setIcon(svg_icon("save", ACCENT, 16))
        self.save_btn.setFixedHeight(34)
        self.save_btn.clicked.connect(self._save)
        hdr_layout.addWidget(self.save_btn)

        self.reload_btn = QPushButton("Reload")
        self.reload_btn.setFixedHeight(34)
        self.reload_btn.clicked.connect(self._load)
        hdr_layout.addWidget(self.reload_btn)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color:{FG2}; font-size:11px;")
        hdr_layout.addWidget(self.status_lbl)

        root.addWidget(hdr)

        # ── Tab container ──────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)

        self._build_profile_tab()
        self._build_binance_tab()
        self._build_database_tab()
        self._build_ai_tab()
        self._build_ml_tab()
        self._build_trading_tab()
        self._build_tax_tab()
        self._build_ui_tab()

    # ── Tab builders ───────────────────────────────────────────────────

    def _scrollable_tab(self, title: str, icon_name: str) -> tuple[QScrollArea, QFormLayout]:
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(24, 20, 24, 20)
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        scroll = _make_scroll(content)
        self.tabs.addTab(scroll, svg_icon(icon_name, FG1, 14), f"  {title}  ")
        return scroll, form

    def _build_profile_tab(self) -> None:
        _, form = self._scrollable_tab("Profile", "info")
        form.addRow(_section_label("USER PROFILE"))
        self.p_name     = QLineEdit(); form.addRow("Name:", self.p_name)
        self.p_email    = QLineEdit(); form.addRow("Email:", self.p_email)
        self.p_timezone = QComboBox()
        for tz in ["Europe/London","America/New_York","America/Chicago",
                   "Asia/Tokyo","Asia/Singapore","UTC"]:
            self.p_timezone.addItem(tz)
        form.addRow("Timezone:", self.p_timezone)
        self.p_currency = QComboBox()
        for c in ["GBP","USD","EUR","JPY","AUD"]:
            self.p_currency.addItem(c)
        form.addRow("Display Currency:", self.p_currency)

    def _build_binance_tab(self) -> None:
        _, form = self._scrollable_tab("Binance", "chart")
        form.addRow(_section_label("BINANCE API"))
        self.b_api_key = SecretEdit("Enter API key…")
        form.addRow("API Key:", self.b_api_key)
        self.b_api_secret = SecretEdit("Enter API secret…")
        form.addRow("API Secret:", self.b_api_secret)
        self.b_testnet = QCheckBox("Use Testnet (paper trading via Binance Testnet)")
        form.addRow("Mode:", self.b_testnet)
        self.b_recv_window = QSpinBox()
        self.b_recv_window.setRange(1000, 60000)
        self.b_recv_window.setSuffix(" ms")
        form.addRow("Recv Window:", self.b_recv_window)

    def _build_database_tab(self) -> None:
        _, form = self._scrollable_tab("Database", "database")
        form.addRow(_section_label("POSTGRESQL"))
        self.db_host = QLineEdit(); form.addRow("Host:", self.db_host)
        self.db_port = QSpinBox(); self.db_port.setRange(1, 65535); form.addRow("Port:", self.db_port)
        self.db_name = QLineEdit(); form.addRow("Database:", self.db_name)
        self.db_user = QLineEdit(); form.addRow("User:", self.db_user)
        self.db_pass = SecretEdit(); form.addRow("Password:", self.db_pass)
        self.db_pool = QSpinBox(); self.db_pool.setRange(1, 50); form.addRow("Pool Size:", self.db_pool)

        form.addRow(_section_label("REDIS"))
        self.r_host = QLineEdit(); form.addRow("Host:", self.r_host)
        self.r_port = QSpinBox(); self.r_port.setRange(1, 65535); form.addRow("Port:", self.r_port)
        self.r_db   = QSpinBox(); self.r_db.setRange(0, 15);     form.addRow("DB Index:", self.r_db)
        self.r_pass = SecretEdit(); form.addRow("Password:", self.r_pass)
        self.r_max_conn = QSpinBox(); self.r_max_conn.setRange(1, 200); form.addRow("Max Connections:", self.r_max_conn)

    def _build_ai_tab(self) -> None:
        _, form = self._scrollable_tab("AI & Voice", "brain")
        form.addRow(_section_label("AI PROVIDER"))
        self.ai_provider = QComboBox()
        for p in ["claude","openai","gemini"]:
            self.ai_provider.addItem(p)
        form.addRow("Provider:", self.ai_provider)
        self.ai_claude_key = SecretEdit("Anthropic API key"); form.addRow("Claude API Key:", self.ai_claude_key)
        self.ai_openai_key = SecretEdit("OpenAI API key");  form.addRow("OpenAI API Key:", self.ai_openai_key)

        form.addRow(_section_label("VOICE ALERTS"))
        self.ai_el_key     = SecretEdit("ElevenLabs API key"); form.addRow("ElevenLabs Key:", self.ai_el_key)
        self.ai_el_voice   = QLineEdit(); form.addRow("Voice ID:", self.ai_el_voice)
        self.ai_voice_en   = QCheckBox("Enable voice alerts"); form.addRow("Voice:", self.ai_voice_en)

    def _build_ml_tab(self) -> None:
        _, form = self._scrollable_tab("ML", "ml")
        form.addRow(_section_label("TRAINING"))
        self.ml_train_hours = QSpinBox(); self.ml_train_hours.setRange(1,168); self.ml_train_hours.setSuffix(" h"); form.addRow("Training Hours:", self.ml_train_hours)
        self.ml_top_tokens  = QSpinBox(); self.ml_top_tokens.setRange(10,500); form.addRow("Top Tokens:", self.ml_top_tokens)
        self.ml_retrain_h   = QSpinBox(); self.ml_retrain_h.setRange(1,168); self.ml_retrain_h.setSuffix(" h"); form.addRow("Retrain Interval:", self.ml_retrain_h)
        self.ml_use_gpu     = QCheckBox("Use GPU (MPS on Apple Silicon)"); form.addRow("GPU:", self.ml_use_gpu)

        form.addRow(_section_label("MODEL PARAMETERS"))
        self.ml_lookback    = QSpinBox(); self.ml_lookback.setRange(10,500); self.ml_lookback.setSuffix(" bars"); form.addRow("Lookback Window:", self.ml_lookback)
        self.ml_horizon     = QSpinBox(); self.ml_horizon.setRange(1,50); self.ml_horizon.setSuffix(" bars"); form.addRow("Pred. Horizon:", self.ml_horizon)
        self.ml_batch       = QSpinBox(); self.ml_batch.setRange(16,2048); form.addRow("Batch Size:", self.ml_batch)
        self.ml_lr          = QDoubleSpinBox(); self.ml_lr.setRange(1e-6,0.1); self.ml_lr.setDecimals(6); self.ml_lr.setSingleStep(0.0001); form.addRow("Learning Rate:", self.ml_lr)
        self.ml_lstm_hidden = QSpinBox(); self.ml_lstm_hidden.setRange(32,1024); form.addRow("LSTM Hidden:", self.ml_lstm_hidden)
        self.ml_lstm_layers = QSpinBox(); self.ml_lstm_layers.setRange(1,8); form.addRow("LSTM Layers:", self.ml_lstm_layers)
        self.ml_dropout     = QDoubleSpinBox(); self.ml_dropout.setRange(0,0.9); self.ml_dropout.setDecimals(2); form.addRow("Dropout:", self.ml_dropout)
        self.ml_conf_thresh = QDoubleSpinBox(); self.ml_conf_thresh.setRange(0.5,0.99); self.ml_conf_thresh.setDecimals(2); self.ml_conf_thresh.setSingleStep(0.01); form.addRow("Confidence Threshold:", self.ml_conf_thresh)

    def _build_trading_tab(self) -> None:
        _, form = self._scrollable_tab("Trading", "trading")
        form.addRow(_section_label("EXECUTION"))
        self.t_mode = QComboBox()
        for m in ["manual","auto","hybrid","paper"]:
            self.t_mode.addItem(m)
        form.addRow("Engine Mode:", self.t_mode)
        self.t_order_type = QComboBox()
        for o in ["LIMIT","MARKET"]:
            self.t_order_type.addItem(o)
        form.addRow("Order Type:", self.t_order_type)
        self.t_max_trades   = QSpinBox(); self.t_max_trades.setRange(1,50); form.addRow("Max Open Trades:", self.t_max_trades)
        self.t_slippage_bps = QSpinBox(); self.t_slippage_bps.setRange(0,100); self.t_slippage_bps.setSuffix(" bps"); form.addRow("Slippage:", self.t_slippage_bps)
        self.t_fee_pct      = QDoubleSpinBox(); self.t_fee_pct.setRange(0,1); self.t_fee_pct.setDecimals(3); self.t_fee_pct.setSuffix(" %"); form.addRow("Fee %:", self.t_fee_pct)

        form.addRow(_section_label("RISK"))
        self.t_risk_pct  = QDoubleSpinBox(); self.t_risk_pct.setRange(0.01,10); self.t_risk_pct.setDecimals(2); self.t_risk_pct.setSuffix(" %"); form.addRow("Risk Per Trade:", self.t_risk_pct)
        self.t_trail_stop = QCheckBox("Trailing Stop"); form.addRow("Trailing Stop:", self.t_trail_stop)
        self.t_trail_pct  = QDoubleSpinBox(); self.t_trail_pct.setRange(0.1,10); self.t_trail_pct.setDecimals(2); self.t_trail_pct.setSuffix(" %"); form.addRow("Trailing Stop %:", self.t_trail_pct)

    def _build_tax_tab(self) -> None:
        _, form = self._scrollable_tab("Tax", "info")
        form.addRow(_section_label("UK CGT SETTINGS"))
        self.tax_jurisdiction = QComboBox()
        self.tax_jurisdiction.addItems(["UK","US","EU","Other"])
        form.addRow("Jurisdiction:", self.tax_jurisdiction)
        self.tax_allowance    = QDoubleSpinBox(); self.tax_allowance.setRange(0,100_000); self.tax_allowance.setPrefix("£"); form.addRow("Annual CGT Allowance:", self.tax_allowance)
        self.tax_basic_rate   = QDoubleSpinBox(); self.tax_basic_rate.setRange(0,50); self.tax_basic_rate.setSuffix(" %"); form.addRow("Basic Rate:", self.tax_basic_rate)
        self.tax_higher_rate  = QDoubleSpinBox(); self.tax_higher_rate.setRange(0,60); self.tax_higher_rate.setSuffix(" %"); form.addRow("Higher Rate:", self.tax_higher_rate)
        self.tax_email_rep    = QCheckBox("Email monthly reports"); form.addRow("Email Reports:", self.tax_email_rep)
        self.tax_report_day   = QSpinBox(); self.tax_report_day.setRange(1,28); form.addRow("Report Day:", self.tax_report_day)

    def _build_ui_tab(self) -> None:
        _, form = self._scrollable_tab("Interface", "settings")
        form.addRow(_section_label("DISPLAY"))
        self.ui_font_size = QSpinBox(); self.ui_font_size.setRange(9,18); self.ui_font_size.setSuffix(" pt"); form.addRow("Font Size:", self.ui_font_size)
        self.ui_accent    = QLineEdit(); self.ui_accent.setPlaceholderText("#00D4FF"); form.addRow("Accent Color:", self.ui_accent)
        self.ui_candles   = QSpinBox(); self.ui_candles.setRange(50,1000); form.addRow("Chart Candles:", self.ui_candles)
        self.ui_interval  = QComboBox()
        for iv in ["1m","3m","5m","15m","30m","1h","4h","1d"]:
            self.ui_interval.addItem(iv)
        form.addRow("Default Interval:", self.ui_interval)
        self.ui_notif  = QCheckBox("Show desktop notifications"); form.addRow("Notifications:", self.ui_notif)
        self.ui_sounds = QCheckBox("Sound alerts"); form.addRow("Sounds:", self.ui_sounds)

    # ── Load / Save ────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            from config import get_settings
            s = get_settings()
            self._settings = s

            # Profile
            self.p_name.setText(s.user.name)
            self.p_email.setText(s.user.email)
            _set_combo(self.p_timezone, s.user.timezone)
            _set_combo(self.p_currency, s.user.currency)

            # Binance
            self.b_api_key.setText(s.binance.api_key)
            self.b_api_secret.setText(s.binance.api_secret)
            self.b_testnet.setChecked(s.binance.testnet)
            self.b_recv_window.setValue(s.binance.recv_window)

            # DB
            self.db_host.setText(s.database.host)
            self.db_port.setValue(s.database.port)
            self.db_name.setText(s.database.name)
            self.db_user.setText(s.database.user)
            self.db_pass.setText(s.database.password)
            self.db_pool.setValue(s.database.pool_size)
            self.r_host.setText(s.redis.host)
            self.r_port.setValue(s.redis.port)
            self.r_db.setValue(s.redis.db)
            self.r_pass.setText(s.redis.password)
            self.r_max_conn.setValue(s.redis.max_connections)

            # AI
            _set_combo(self.ai_provider, s.ai.provider)
            self.ai_claude_key.setText(s.ai.claude_api_key)
            self.ai_openai_key.setText(s.ai.openai_api_key)
            self.ai_el_key.setText(s.ai.elevenlabs_api_key)
            self.ai_el_voice.setText(s.ai.elevenlabs_voice_id)
            self.ai_voice_en.setChecked(s.ai.voice_enabled)

            # ML
            self.ml_train_hours.setValue(s.ml.training_hours)
            self.ml_top_tokens.setValue(s.ml.top_tokens)
            self.ml_retrain_h.setValue(s.ml.retrain_interval_hours)
            self.ml_use_gpu.setChecked(s.ml.use_gpu)
            self.ml_lookback.setValue(s.ml.lookback_window)
            self.ml_horizon.setValue(s.ml.prediction_horizon)
            self.ml_batch.setValue(s.ml.batch_size)
            self.ml_lr.setValue(s.ml.learning_rate)
            self.ml_lstm_hidden.setValue(s.ml.lstm_hidden_size)
            self.ml_lstm_layers.setValue(s.ml.lstm_layers)
            self.ml_dropout.setValue(s.ml.dropout)
            self.ml_conf_thresh.setValue(s.ml.confidence_threshold)

            # Trading
            _set_combo(self.t_mode, s.trading.mode)
            _set_combo(self.t_order_type, s.trading.order_type)
            self.t_max_trades.setValue(s.trading.max_open_trades)
            self.t_slippage_bps.setValue(s.trading.slippage_bps)
            self.t_fee_pct.setValue(s.trading.fee_pct)
            self.t_risk_pct.setValue(s.trading.risk_per_trade_pct)
            self.t_trail_stop.setChecked(s.trading.trailing_stop)
            self.t_trail_pct.setValue(s.trading.trailing_stop_pct)

            # Tax
            _set_combo(self.tax_jurisdiction, s.tax.jurisdiction)
            self.tax_allowance.setValue(s.tax.cgt_annual_allowance)
            self.tax_basic_rate.setValue(s.tax.basic_rate_pct)
            self.tax_higher_rate.setValue(s.tax.higher_rate_pct)
            self.tax_email_rep.setChecked(s.tax.email_reports)
            self.tax_report_day.setValue(s.tax.report_day)

            # UI
            self.ui_font_size.setValue(s.ui.font_size)
            self.ui_accent.setText(s.ui.accent_color)
            self.ui_candles.setValue(s.ui.chart_candle_count)
            _set_combo(self.ui_interval, s.ui.default_interval)
            self.ui_notif.setChecked(s.ui.show_notifications)
            self.ui_sounds.setChecked(s.ui.sound_alerts)

            self._flash_status("Settings loaded", GREEN)
        except Exception as e:
            self._flash_status(f"Load error: {e}", RED)

    def _save(self) -> None:
        try:
            from config import get_settings
            s = get_settings()

            s.user.name     = self.p_name.text()
            s.user.email    = self.p_email.text()
            s.user.timezone = self.p_timezone.currentText()
            s.user.currency = self.p_currency.currentText()

            s.binance.api_key     = self.b_api_key.text()
            s.binance.api_secret  = self.b_api_secret.text()
            s.binance.testnet     = self.b_testnet.isChecked()
            s.binance.recv_window = self.b_recv_window.value()

            s.database.host       = self.db_host.text()
            s.database.port       = self.db_port.value()
            s.database.name       = self.db_name.text()
            s.database.user       = self.db_user.text()
            s.database.password   = self.db_pass.text()
            s.database.pool_size  = self.db_pool.value()
            s.redis.host          = self.r_host.text()
            s.redis.port          = self.r_port.value()
            s.redis.db            = self.r_db.value()
            s.redis.password      = self.r_pass.text()
            s.redis.max_connections = self.r_max_conn.value()

            s.ai.provider          = self.ai_provider.currentText()
            s.ai.claude_api_key    = self.ai_claude_key.text()
            s.ai.openai_api_key    = self.ai_openai_key.text()
            s.ai.elevenlabs_api_key = self.ai_el_key.text()
            s.ai.elevenlabs_voice_id = self.ai_el_voice.text()
            s.ai.voice_enabled     = self.ai_voice_en.isChecked()

            s.ml.training_hours    = self.ml_train_hours.value()
            s.ml.top_tokens        = self.ml_top_tokens.value()
            s.ml.retrain_interval_hours = self.ml_retrain_h.value()
            s.ml.use_gpu           = self.ml_use_gpu.isChecked()
            s.ml.lookback_window   = self.ml_lookback.value()
            s.ml.prediction_horizon = self.ml_horizon.value()
            s.ml.batch_size        = self.ml_batch.value()
            s.ml.learning_rate     = self.ml_lr.value()
            s.ml.lstm_hidden_size  = self.ml_lstm_hidden.value()
            s.ml.lstm_layers       = self.ml_lstm_layers.value()
            s.ml.dropout           = self.ml_dropout.value()
            s.ml.confidence_threshold = self.ml_conf_thresh.value()

            s.trading.mode          = self.t_mode.currentText()
            s.trading.order_type    = self.t_order_type.currentText()
            s.trading.max_open_trades = self.t_max_trades.value()
            s.trading.slippage_bps  = self.t_slippage_bps.value()
            s.trading.fee_pct       = self.t_fee_pct.value()
            s.trading.risk_per_trade_pct = self.t_risk_pct.value()
            s.trading.trailing_stop = self.t_trail_stop.isChecked()
            s.trading.trailing_stop_pct = self.t_trail_pct.value()

            s.tax.jurisdiction      = self.tax_jurisdiction.currentText()
            s.tax.cgt_annual_allowance = self.tax_allowance.value()
            s.tax.basic_rate_pct    = self.tax_basic_rate.value()
            s.tax.higher_rate_pct   = self.tax_higher_rate.value()
            s.tax.email_reports     = self.tax_email_rep.isChecked()
            s.tax.report_day        = self.tax_report_day.value()

            s.ui.font_size          = self.ui_font_size.value()
            s.ui.accent_color       = self.ui_accent.text()
            s.ui.chart_candle_count = self.ui_candles.value()
            s.ui.default_interval   = self.ui_interval.currentText()
            s.ui.show_notifications = self.ui_notif.isChecked()
            s.ui.sound_alerts       = self.ui_sounds.isChecked()

            s.save()
            self.settings_saved.emit()
            self._flash_status("✓  All settings saved", GREEN)
        except Exception as e:
            self._flash_status(f"Save error: {e}", RED)

    def _flash_status(self, msg: str, color: str) -> None:
        self.status_lbl.setText(msg)
        self.status_lbl.setStyleSheet(f"color:{color}; font-size:11px;")
        QTimer.singleShot(4000, lambda: self.status_lbl.setText(""))


def _set_combo(combo: QComboBox, value: str) -> None:
    idx = combo.findText(value, Qt.MatchFlag.MatchFixedString)
    if idx >= 0:
        combo.setCurrentIndex(idx)
