"""
First-run setup wizard.
Collects user details, API keys (Binance, Claude, OpenAI, Gemini, ElevenLabs),
database credentials, and master encryption password.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QColor, QPainter, QLinearGradient
from PyQt6.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QGroupBox, QFormLayout, QCheckBox,
    QComboBox, QWidget, QProgressBar, QMessageBox, QFrame,
    QDialog, QDialogButtonBox,
)

from config import get_settings
from config.encryption import EncryptionManager
from ui.styles import ACCENT, GREEN, RED, BG1, BG2, BG3, FG0, FG1, FG2, BORDER


class WelcomePage(QWizardPage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        logo = QLabel("🏦")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("font-size: 64px;")
        layout.addWidget(logo)

        title = QLabel("BinanceML Pro")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-size:32px; font-weight:700; color:{ACCENT};")
        layout.addWidget(title)

        sub = QLabel("Professional AI-Powered Crypto Trading Platform")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"font-size:14px; color:{FG1};")
        layout.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER};")
        layout.addWidget(sep)

        features = [
            "✅  ML-powered trade signals (LSTM + Transformer)",
            "✅  Automated & manual trading via Binance API",
            "✅  UK HMRC-compliant tax reporting",
            "✅  48-hour initial model training",
            "✅  Continuous learning while active",
            "✅  REST API & webhooks for external integrations",
            "✅  Data integrity checks every 25 minutes",
        ]
        for f in features:
            lbl = QLabel(f)
            lbl.setStyleSheet(f"font-size:13px; color:{FG1};")
            layout.addWidget(lbl)

        layout.addStretch()
        info = QLabel("Click Next to configure your account.")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setStyleSheet(f"font-size:12px; color:{FG2};")
        layout.addWidget(info)


class UserProfilePage(QWizardPage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Your Profile")
        self.setSubTitle("Enter your personal details for tax reports and notifications.")

        form = QFormLayout(self)
        form.setSpacing(12)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. John Smith")
        form.addRow("Full Name *", self.name_edit)

        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("e.g. john@example.com")
        form.addRow("Email Address *", self.email_edit)

        self.tz_combo = QComboBox()
        for tz in ["Europe/London","Europe/Berlin","America/New_York","America/Los_Angeles","Asia/Tokyo","UTC"]:
            self.tz_combo.addItem(tz)
        form.addRow("Timezone", self.tz_combo)

        self.currency_combo = QComboBox()
        for c in ["GBP","USD","EUR","JPY","AUD"]:
            self.currency_combo.addItem(c)
        form.addRow("Base Currency", self.currency_combo)

        self.registerField("name*", self.name_edit)
        self.registerField("email*", self.email_edit)


class SecurityPage(QWizardPage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Security")
        self.setSubTitle("Set a master password to encrypt all API keys and sensitive data.")

        layout = QVBoxLayout(self)

        info = QLabel(
            "Your master password encrypts all stored credentials using AES-256-GCM.\n"
            "This password is never stored – it is derived into an encryption key.\n"
            "If you forget it, you will need to re-enter all API keys."
        )
        info.setStyleSheet(f"color:{FG1}; font-size:12px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()

        self.pw_edit = QLineEdit()
        self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_edit.setPlaceholderText("Minimum 12 characters")
        form.addRow("Master Password *", self.pw_edit)

        self.pw_confirm = QLineEdit()
        self.pw_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_confirm.setPlaceholderText("Confirm password")
        form.addRow("Confirm Password *", self.pw_confirm)

        layout.addLayout(form)

        self.strength_bar = QProgressBar()
        self.strength_bar.setRange(0, 100)
        self.strength_bar.setFormat("Password strength: %p%")
        self.strength_bar.setFixedHeight(20)
        layout.addWidget(self.strength_bar)

        self.pw_edit.textChanged.connect(self._update_strength)

        self.registerField("master_pw*", self.pw_edit)

        note = QLabel("⚠ Store this password securely – it cannot be recovered.")
        note.setStyleSheet(f"color:{RED}; font-size:11px;")
        layout.addWidget(note)
        layout.addStretch()

    def _update_strength(self, text: str) -> None:
        score = 0
        if len(text) >= 8: score += 20
        if len(text) >= 12: score += 20
        if any(c.isupper() for c in text): score += 20
        if any(c.isdigit() for c in text): score += 20
        if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in text): score += 20
        self.strength_bar.setValue(score)
        colour = RED if score < 40 else YELLOW if score < 80 else GREEN
        self.strength_bar.setStyleSheet(f"""
            QProgressBar::chunk {{ background:{colour}; border-radius:4px; }}
        """)

    def validatePage(self) -> bool:
        pw = self.pw_edit.text()
        if len(pw) < 12:
            QMessageBox.warning(self, "Weak Password", "Password must be at least 12 characters.")
            return False
        if pw != self.pw_confirm.text():
            QMessageBox.warning(self, "Mismatch", "Passwords do not match.")
            return False
        return True


class BinancePage(QWizardPage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Binance API")
        self.setSubTitle("Connect your Binance account. Use Testnet for safe practice.")

        form = QFormLayout(self)
        form.setSpacing(12)

        self.api_key = QLineEdit()
        self.api_key.setPlaceholderText("Binance API Key")
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Key", self.api_key)

        self.api_secret = QLineEdit()
        self.api_secret.setPlaceholderText("Binance API Secret")
        self.api_secret.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Secret", self.api_secret)

        self.testnet_cb = QCheckBox("Use Testnet (recommended for initial testing)")
        self.testnet_cb.setChecked(True)
        form.addRow("", self.testnet_cb)

        test_btn = QPushButton("🔌 Test Connection")
        test_btn.setObjectName("btn_primary")
        test_btn.clicked.connect(self._test_connection)
        form.addRow("", test_btn)

        self.status_lbl = QLabel("")
        form.addRow("", self.status_lbl)

        hint = QLabel(
            "Create API keys at binance.com/en/my/settings/api-management\n"
            "Enable: Read Info, Spot & Margin Trading\n"
            "Disable: Withdrawals & Transfers"
        )
        hint.setStyleSheet(f"color:{FG2}; font-size:11px;")
        form.addRow("", hint)

    def _test_connection(self) -> None:
        from core.binance_client import BinanceClient
        try:
            client = BinanceClient(
                self.api_key.text().strip(),
                self.api_secret.text().strip(),
                testnet=self.testnet_cb.isChecked(),
            )
            ok = client.ping()
            if ok:
                self.status_lbl.setText("✅ Connected successfully!")
                self.status_lbl.setStyleSheet(f"color:{GREEN};")
            else:
                self.status_lbl.setText("❌ Connection failed")
                self.status_lbl.setStyleSheet(f"color:{RED};")
        except Exception as exc:
            self.status_lbl.setText(f"❌ {str(exc)[:60]}")
            self.status_lbl.setStyleSheet(f"color:{RED};")


class AIApiPage(QWizardPage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("AI Providers")
        self.setSubTitle("Enter API keys for AI services. All are optional – at least one is recommended.")

        form = QFormLayout(self)
        form.setSpacing(10)

        self.provider_combo = QComboBox()
        for p in ["claude","openai","gemini"]:
            self.provider_combo.addItem(p.title(), p)
        form.addRow("Primary AI Provider", self.provider_combo)

        self.claude_key = QLineEdit()
        self.claude_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.claude_key.setPlaceholderText("sk-ant-…")
        form.addRow("Claude API Key", self.claude_key)

        self.openai_key = QLineEdit()
        self.openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key.setPlaceholderText("sk-…")
        form.addRow("OpenAI API Key", self.openai_key)

        self.gemini_key = QLineEdit()
        self.gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Gemini API Key", self.gemini_key)

        self.elevenlabs_key = QLineEdit()
        self.elevenlabs_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("ElevenLabs Voice Key", self.elevenlabs_key)

        self.voice_cb = QCheckBox("Enable voice notifications")
        self.voice_cb.setChecked(True)
        form.addRow("", self.voice_cb)


class DatabasePage(QWizardPage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Database")
        self.setSubTitle("Configure PostgreSQL and Redis connections.")

        form = QFormLayout(self)
        form.setSpacing(10)

        self.pg_host = QLineEdit("localhost")
        form.addRow("PostgreSQL Host", self.pg_host)
        self.pg_port = QLineEdit("5432")
        form.addRow("PostgreSQL Port", self.pg_port)
        self.pg_name = QLineEdit("binanceml")
        form.addRow("Database Name", self.pg_name)
        self.pg_user = QLineEdit("binanceml")
        form.addRow("Username", self.pg_user)
        self.pg_pass = QLineEdit()
        self.pg_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password", self.pg_pass)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        form.addRow(sep)

        self.redis_host = QLineEdit("localhost")
        form.addRow("Redis Host", self.redis_host)
        self.redis_port = QLineEdit("6379")
        form.addRow("Redis Port", self.redis_port)

        test_btn = QPushButton("🔌 Test Connections")
        test_btn.setObjectName("btn_primary")
        test_btn.clicked.connect(self._test_db)
        form.addRow("", test_btn)
        self.db_status = QLabel("")
        form.addRow("", self.db_status)

    def _test_db(self) -> None:
        try:
            from db.postgres import init_db
            from db.redis_client import init_redis
            url = (f"postgresql+psycopg2://{self.pg_user.text()}:{self.pg_pass.text()}"
                   f"@{self.pg_host.text()}:{self.pg_port.text()}/{self.pg_name.text()}")
            init_db(url)
            init_redis(host=self.redis_host.text(), port=int(self.redis_port.text()))
            self.db_status.setText("✅ Database connections OK!")
            self.db_status.setStyleSheet(f"color:{GREEN};")
        except Exception as exc:
            self.db_status.setText(f"❌ {str(exc)[:80]}")
            self.db_status.setStyleSheet(f"color:{RED};")


class SetupWizard(QWizard):
    """Multi-page first-run setup wizard."""

    setup_complete = pyqtSignal(dict)   # emits collected config dict

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("BinanceML Pro – Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(700, 560)
        self.setStyleSheet(f"background:{BG1}; color:{FG0};")

        self.addPage(WelcomePage())
        self.user_page = UserProfilePage()
        self.addPage(self.user_page)
        self.sec_page = SecurityPage()
        self.addPage(self.sec_page)
        self.binance_page = BinancePage()
        self.addPage(self.binance_page)
        self.ai_page = AIApiPage()
        self.addPage(self.ai_page)
        self.db_page = DatabasePage()
        self.addPage(self.db_page)

        self.button(QWizard.WizardButton.FinishButton).clicked.connect(self._on_finish)

    def _on_finish(self) -> None:
        master_pw = self.sec_page.pw_edit.text()
        enc = EncryptionManager()
        enc.initialise(master_pw)

        settings = get_settings()
        settings.user.name = self.user_page.name_edit.text().strip()
        settings.user.email = self.user_page.email_edit.text().strip()
        settings.user.timezone = self.user_page.tz_combo.currentText()
        settings.user.currency = self.user_page.currency_combo.currentText()

        settings.binance.api_key = self.binance_page.api_key.text().strip()
        settings.binance.api_secret = self.binance_page.api_secret.text().strip()
        settings.binance.testnet = self.binance_page.testnet_cb.isChecked()

        settings.ai.provider = self.ai_page.provider_combo.currentData()
        settings.ai.claude_api_key = self.ai_page.claude_key.text().strip()
        settings.ai.openai_api_key = self.ai_page.openai_key.text().strip()
        settings.ai.gemini_api_key = self.ai_page.gemini_key.text().strip()
        settings.ai.elevenlabs_api_key = self.ai_page.elevenlabs_key.text().strip()
        settings.ai.voice_enabled = self.ai_page.voice_cb.isChecked()

        settings.database.host = self.db_page.pg_host.text()
        settings.database.port = int(self.db_page.pg_port.text())
        settings.database.name = self.db_page.pg_name.text()
        settings.database.user = self.db_page.pg_user.text()
        settings.database.password = self.db_page.pg_pass.text()

        settings.redis.host = self.db_page.redis_host.text()
        settings.redis.port = int(self.db_page.redis_port.text())

        settings.first_run = False
        settings.save()

        # Store API keys in OS keychain
        if settings.binance.api_key:
            enc.store_api_key("binance_key", settings.binance.api_key)
            enc.store_api_key("binance_secret", settings.binance.api_secret)
        if settings.ai.claude_api_key:
            enc.store_api_key("claude_key", settings.ai.claude_api_key)

        self.setup_complete.emit({"status": "complete"})


# ── Runtime credential recovery dialog ───────────────────────────────────────

class DbCredentialsDialog(QDialog):
    """
    Shown at startup when PostgreSQL rejects the configured user/password.
    The user can:
      (a) Enter different credentials for an existing PG account, OR
      (b) Enable the superuser section to have the app CREATE the user and
          GRANT it full access to the database automatically.
    """

    def __init__(self, host: str, port: int, db_name: str,
                 failed_user: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Database Credentials Required")
        self.setMinimumWidth(520)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

        self._host      = host
        self._port      = port
        self._db_name   = db_name
        self._ok_user   = None   # set after successful test
        self._ok_pass   = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Error banner ──────────────────────────────────────────────
        banner = QLabel(
            f"<b>Cannot connect to PostgreSQL database '{db_name}'</b><br>"
            f"User <code>{failed_user}</code> does not exist, has the wrong "
            f"password, or lacks the required privileges."
        )
        banner.setWordWrap(True)
        banner.setTextFormat(Qt.TextFormat.RichText)
        banner.setStyleSheet(
            f"background:{RED}22; color:{RED}; padding:10px; "
            f"border:1px solid {RED}66; border-radius:4px;"
        )
        layout.addWidget(banner)

        # ── New credentials ───────────────────────────────────────────
        creds_box = QGroupBox(f"Credentials for database '{db_name}'")
        creds_form = QFormLayout(creds_box)
        creds_form.setSpacing(8)

        self.user_edit = QLineEdit(failed_user)
        creds_form.addRow("Username:", self.user_edit)

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("Password")
        creds_form.addRow("Password:", self.pass_edit)

        layout.addWidget(creds_box)

        # ── Optional: create user via superuser ───────────────────────
        self.su_group = QGroupBox(
            "Create / Grant this user (requires a PostgreSQL superuser)"
        )
        self.su_group.setCheckable(True)
        self.su_group.setChecked(False)
        su_layout = QVBoxLayout(self.su_group)

        hint = QLabel(
            "If the user does not exist yet, provide a superuser account "
            "(e.g. 'postgres') and the app will CREATE the user, create the "
            f"database if needed, and GRANT ALL PRIVILEGES on '{db_name}'."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{FG2}; font-size:11px;")
        su_layout.addWidget(hint)

        su_form = QFormLayout()
        su_form.setSpacing(8)

        self.su_user_edit = QLineEdit("postgres")
        su_form.addRow("Superuser name:", self.su_user_edit)

        self.su_pass_edit = QLineEdit()
        self.su_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.su_pass_edit.setPlaceholderText("Superuser password")
        su_form.addRow("Superuser password:", self.su_pass_edit)

        su_layout.addLayout(su_form)
        layout.addWidget(self.su_group)

        # ── Test button + status ──────────────────────────────────────
        test_btn = QPushButton("Test & Connect")
        test_btn.setObjectName("btn_primary")
        test_btn.clicked.connect(self._test_and_connect)
        layout.addWidget(test_btn)

        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setMinimumHeight(36)
        layout.addWidget(self.status_lbl)

        # ── Buttons ───────────────────────────────────────────────────
        self.ok_btn = QPushButton("Save && Continue")
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self.accept)
        skip_btn = QPushButton("Skip (offline mode)")
        skip_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.ok_btn)
        btn_row.addWidget(skip_btn)
        layout.addLayout(btn_row)

    # ── Helpers ───────────────────────────────────────────────────────

    def accepted_credentials(self) -> tuple[str, str]:
        """Return (user, password) after dialog accepted."""
        return self._ok_user, self._ok_pass

    def _set_status(self, text: str, ok: bool) -> None:
        colour = GREEN if ok else RED
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(f"color:{colour};")

    def _test_and_connect(self) -> None:
        user     = self.user_edit.text().strip()
        password = self.pass_edit.text()

        if not user:
            self._set_status("Username cannot be empty.", ok=False)
            return

        # Step 1: optionally create / grant via superuser
        if self.su_group.isChecked():
            ok = self._setup_via_superuser(user, password)
            if not ok:
                return   # error already shown in status_lbl

        # Step 2: test the target connection
        url = (
            f"postgresql+psycopg2://{user}:{password}"
            f"@{self._host}:{self._port}/{self._db_name}"
        )
        try:
            from sqlalchemy import create_engine
            engine = create_engine(
                url,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 5},
            )
            with engine.connect():
                pass
            engine.dispose()

            self._ok_user = user
            self._ok_pass = password
            self.ok_btn.setEnabled(True)
            self._set_status(
                f"Connected successfully as '{user}'. Click Save & Continue.",
                ok=True,
            )
        except Exception as exc:
            self.ok_btn.setEnabled(False)
            self._set_status(f"Connection failed: {str(exc)[:140]}", ok=False)

    def _setup_via_superuser(self, new_user: str, new_pass: str) -> bool:
        """
        Connect as superuser and:
          1. CREATE the target database if it doesn't exist
          2. CREATE USER (or ALTER PASSWORD) for new_user
          3. GRANT ALL PRIVILEGES ON DATABASE to new_user
          4. GRANT ALL ON SCHEMA public to new_user (PostgreSQL 15+)
        Returns True on success, False on failure (status_lbl updated).
        """
        from sqlalchemy import create_engine, text

        su_user = self.su_user_edit.text().strip()
        su_pass = self.su_pass_edit.text()
        db_name = self._db_name

        if not su_user:
            self._set_status("Superuser name cannot be empty.", ok=False)
            return False

        # ── Connect to postgres system DB as superuser ────────────────
        sys_url = (
            f"postgresql+psycopg2://{su_user}:{su_pass}"
            f"@{self._host}:{self._port}/postgres"
        )
        try:
            sys_engine = create_engine(
                sys_url,
                isolation_level="AUTOCOMMIT",
                connect_args={"connect_timeout": 5},
            )
            with sys_engine.connect() as conn:
                # Create database if missing
                db_exists = conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"),
                    {"n": db_name},
                ).fetchone()
                if not db_exists:
                    conn.execute(text(f'CREATE DATABASE "{db_name}"'))

                # Create or update the application user
                role_exists = conn.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :n"),
                    {"n": new_user},
                ).fetchone()
                if role_exists:
                    conn.execute(
                        text(f'ALTER USER "{new_user}" WITH PASSWORD :pw'),
                        {"pw": new_pass},
                    )
                else:
                    conn.execute(
                        text(f'CREATE USER "{new_user}" WITH PASSWORD :pw'),
                        {"pw": new_pass},
                    )

                # Grant database-level privileges
                conn.execute(text(
                    f'GRANT ALL PRIVILEGES ON DATABASE "{db_name}" TO "{new_user}"'
                ))

            sys_engine.dispose()

            # ── Connect to the target DB as superuser to grant schema ─
            tgt_url = (
                f"postgresql+psycopg2://{su_user}:{su_pass}"
                f"@{self._host}:{self._port}/{db_name}"
            )
            tgt_engine = create_engine(
                tgt_url,
                isolation_level="AUTOCOMMIT",
                connect_args={"connect_timeout": 5},
            )
            with tgt_engine.connect() as conn:
                conn.execute(text(
                    f'GRANT ALL ON SCHEMA public TO "{new_user}"'
                ))
                conn.execute(text(
                    f'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
                    f'GRANT ALL ON TABLES TO "{new_user}"'
                ))
            tgt_engine.dispose()

            self._set_status(
                f"User '{new_user}' created/updated with full access to '{db_name}'.",
                ok=True,
            )
            return True

        except Exception as exc:
            self._set_status(
                f"Superuser setup failed: {str(exc)[:160]}",
                ok=False,
            )
            return False
