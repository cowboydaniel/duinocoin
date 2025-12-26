"""UI dialog for editing wallet credentials."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .state import Configuration


class WalletCredentialsDialog(QDialog):
    """Dialog to prompt for wallet username and token."""

    def __init__(self, config: Configuration, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Wallet Credentials")
        self._config = config

        layout = QVBoxLayout()
        form = QFormLayout()

        self.username_input = QLineEdit(self._config.wallet_username)
        self.token_input = QLineEdit(self._config.wallet_token)
        self.token_input.setEchoMode(QLineEdit.Password)

        form.addRow("Username:", self.username_input)
        form.addRow("API token (optional):", self.token_input)

        layout.addLayout(form)

        clear_button = QPushButton("Clear token")
        clear_button.clicked.connect(self._clear_token)
        layout.addWidget(clear_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def get_credentials(self) -> tuple[str, str]:
        """Return username and token from the dialog inputs."""
        return self.username_input.text().strip(), self.token_input.text().strip()

    def _clear_token(self) -> None:
        self.token_input.clear()
