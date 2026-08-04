#!/usr/bin/env python3
"""Ainos Desktop - Inference Playground Widget.

Provides an interactive inference playground with streaming output,
configurable parameters, and conversation history management.
"""

import logging
import time
import uuid
from typing import Any
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal, Slot, QSize
from PySide6.QtGui import QColor, QFont, QTextCursor, QIcon
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QTextEdit,
    QPlainTextEdit,
    QSplitter,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QSlider,
    QGroupBox,
    QScrollArea,
    QSizePolicy,
    QProgressBar,
    QTabWidget,
    QMenu,
    QToolBar,
    QApplication,
)

from client.models import InferenceRequest, InferenceResponse, GenerationConfig

logger = logging.getLogger(__name__)


class MessageBubble(QFrame):
    """A chat message bubble widget."""

    def __init__(
        self,
        content: str,
        role: str = "user",
        timestamp: str = "",
        token_count: int = 0,
        parent: QWidget | None = None,
    ):
        """Initialize the message bubble.

        Args:
            content: Message text content.
            role: Message role ('user', 'assistant', 'system').
            timestamp: Message timestamp.
            token_count: Token count for this message.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._content = content
        self._role = role
        self._timestamp = timestamp or datetime.now().strftime("%H:%M:%S")
        self._token_count = token_count

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the message bubble UI."""
        is_user = self._role == "user"
        is_system = self._role == "system"

        # Colors
        if is_user:
            bg_color = "#2A3A5C"
            border_color = "#3A4A6C"
            text_color = "#CDD6F4"
        elif is_system:
            bg_color = "#2A3A2A"
            border_color = "#3A4A3A"
            text_color = "#A6E3A1"
        else:
            bg_color = "#252540"
            border_color = "#353550"
            text_color = "#CDD6F4"

        self.setStyleSheet(f"""
            MessageBubble {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Header
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        role_label = QLabel(self._role.capitalize())
        role_label.setStyleSheet(
            f"font-size: 9pt; font-weight: 600; color: {text_color};"
        )
        header_layout.addWidget(role_label)

        header_layout.addStretch()

        # Timestamp
        time_label = QLabel(self._timestamp)
        time_label.setStyleSheet("font-size: 8pt; color: #6C7086;")
        header_layout.addWidget(time_label)

        # Token count
        if self._token_count > 0:
            token_label = QLabel(f"{self._token_count} tokens")
            token_label.setStyleSheet("font-size: 8pt; color: #6C7086;")
            header_layout.addWidget(token_label)

        layout.addLayout(header_layout)

        # Content
        content_label = QLabel(self._content)
        content_label.setWordWrap(True)
        content_label.setStyleSheet(
            f"font-size: 10pt; color: {text_color}; background: transparent; "
            f"border: none; padding: 4px 0;"
        )
        content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(content_label)

    def append_content(self, text: str) -> None:
        """Append content to the message.

        Args:
            text: Additional text to append.
        """
        self._content += text
        # Find the content label and update it
        for i in range(self.layout().count()):
            item = self.layout().itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QLabel):
                if item.widget() != self.layout().itemAt(0).widget():
                    item.widget().setText(self._content)
                    break


class StreamingTextEdit(QPlainTextEdit):
    """A text edit widget optimized for streaming text display."""

    def __init__(self, parent: QWidget | None = None):
        """Initialize the streaming text edit.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setReadOnly(True)
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1E1E2E;
                color: #CDD6F4;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 12px;
                font-family: 'Consolas', 'SF Mono', 'Fira Code', monospace;
                font-size: 10pt;
                selection-background-color: #89B4FA;
                selection-color: #1E1E2E;
            }
        """)
        self.setMinimumHeight(200)

    def append_stream_text(self, text: str) -> None:
        """Append streaming text to the output.

        Args:
            text: Text chunk to append.
        """
        self.moveCursor(QTextCursor.MoveOperation.End)
        self.insertPlainText(text)
        # Auto-scroll to bottom
        scrollbar = self.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())


class InferenceWidget(QWidget):
    """Inference playground widget with streaming support."""

    def __init__(self, app: Any, parent: QWidget | None = None):
        """Initialize the inference widget.

        Args:
            app: The AinosApplication instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._app = app
        self._current_session_id: str = ""
        self._is_streaming = False
        self._stream_buffer = ""
        self._messages: list[MessageBubble] = []
        self._theme = "dark"

        self._setup_ui()

        logger.info("Inference widget initialized")

    def _setup_ui(self) -> None:
        """Set up the inference playground UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)

        # ===== Left Panel: Chat / Messages =====
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(24, 24, 24, 24)
        left_layout.setSpacing(12)

        # Header
        header_layout = QHBoxLayout()

        header_text = QLabel("Inference Playground")
        header_text.setProperty("heading", True)
        header_layout.addWidget(header_text)

        header_layout.addStretch()

        # Session controls
        new_session_btn = QPushButton("New Session")
        new_session_btn.clicked.connect(self.new_session)
        header_layout.addWidget(new_session_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_chat)
        header_layout.addWidget(clear_btn)

        left_layout.addLayout(header_layout)

        # Model selector
        model_layout = QHBoxLayout()
        model_layout.setSpacing(8)

        model_label = QLabel("Model:")
        model_label.setStyleSheet("font-size: 10pt; color: #A0A8C0;")
        model_layout.addWidget(model_label)

        self._model_combo = QComboBox()
        self._model_combo.addItems(["Llama 3.1 8B", "CodeLlama 7B", "Mistral 7B", "DeepSeek Coder 6.7B"])
        self._model_combo.setMinimumWidth(200)
        model_layout.addWidget(self._model_combo)

        model_layout.addStretch()

        # System prompt
        sys_prompt_label = QLabel("System Prompt:")
        sys_prompt_label.setStyleSheet("font-size: 10pt; color: #A0A8C0;")
        model_layout.addWidget(sys_prompt_label)

        self._system_prompt_input = QPlainTextEdit()
        self._system_prompt_input.setPlaceholderText("Optional system prompt...")
        self._system_prompt_input.setMaximumHeight(60)
        self._system_prompt_input.setStyleSheet("""
            QPlainTextEdit {
                background-color: #252540;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 9pt;
            }
        """)
        model_layout.addWidget(self._system_prompt_input, 1)

        left_layout.addLayout(model_layout)

        # Messages area (scrollable)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._messages_container = QWidget()
        self._messages_layout = QVBoxLayout(self._messages_container)
        self._messages_layout.setSpacing(12)
        self._messages_layout.addStretch()

        scroll_area.setWidget(self._messages_container)
        left_layout.addWidget(scroll_area, 1)

        # Streaming output area (for non-chat mode)
        self._stream_output = StreamingTextEdit()
        self._stream_output.setPlaceholderText("Generated output will appear here...")
        self._stream_output.setVisible(False)
        left_layout.addWidget(self._stream_output)

        # Input area
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        self._input_edit = QPlainTextEdit()
        self._input_edit.setPlaceholderText("Enter your prompt here... (Ctrl+Enter to send)")
        self._input_edit.setMaximumHeight(100)
        self._input_edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #252540;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 10pt;
                selection-background-color: #89B4FA;
                selection-color: #1E1E2E;
            }
            QPlainTextEdit:focus {
                border-color: #89B4FA;
            }
        """)
        input_layout.addWidget(self._input_edit, 1)

        self._send_btn = QPushButton("Send")
        self._send_btn.setProperty("primary", True)
        self._send_btn.setFixedSize(100, 40)
        self._send_btn.clicked.connect(self._send_message)
        input_layout.addWidget(self._send_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setProperty("danger", True)
        self._stop_btn.setFixedSize(100, 40)
        self._stop_btn.setVisible(False)
        self._stop_btn.clicked.connect(self._stop_generation)
        input_layout.addWidget(self._stop_btn)

        left_layout.addLayout(input_layout)

        # ===== Right Panel: Parameters =====
        right_panel = QWidget()
        right_panel.setFixedWidth(300)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 24, 24, 24)
        right_layout.setSpacing(16)

        # Parameters group
        params_group = QGroupBox("Generation Parameters")
        params_layout = QVBoxLayout(params_group)
        params_layout.setSpacing(12)

        # Temperature
        temp_layout = QHBoxLayout()
        temp_label = QLabel("Temperature:")
        temp_label.setStyleSheet("font-size: 10pt; color: #A0A8C0;")
        temp_layout.addWidget(temp_label)

        self._temp_slider = QSlider(Qt.Orientation.Horizontal)
        self._temp_slider.setRange(0, 200)
        self._temp_slider.setValue(70)
        self._temp_slider.valueChanged.connect(self._update_temp_label)
        temp_layout.addWidget(self._temp_slider, 1)

        self._temp_value = QLabel("0.70")
        self._temp_value.setFixedWidth(40)
        self._temp_value.setStyleSheet("font-size: 10pt; color: #CDD6F4;")
        temp_layout.addWidget(self._temp_value)

        params_layout.addLayout(temp_layout)

        # Top P
        top_p_layout = QHBoxLayout()
        top_p_label = QLabel("Top P:")
        top_p_label.setStyleSheet("font-size: 10pt; color: #A0A8C0;")
        top_p_layout.addWidget(top_p_label)

        self._top_p_slider = QSlider(Qt.Orientation.Horizontal)
        self._top_p_slider.setRange(0, 100)
        self._top_p_slider.setValue(90)
        self._top_p_slider.valueChanged.connect(self._update_top_p_label)
        top_p_layout.addWidget(self._top_p_slider, 1)

        self._top_p_value = QLabel("0.90")
        self._top_p_value.setFixedWidth(40)
        self._top_p_value.setStyleSheet("font-size: 10pt; color: #CDD6F4;")
        top_p_layout.addWidget(self._top_p_value)

        params_layout.addLayout(top_p_layout)

        # Top K
        top_k_layout = QHBoxLayout()
        top_k_label = QLabel("Top K:")
        top_k_label.setStyleSheet("font-size: 10pt; color: #A0A8C0;")
        top_k_layout.addWidget(top_k_label)

        self._top_k_spin = QSpinBox()
        self._top_k_spin.setRange(1, 200)
        self._top_k_spin.setValue(40)
        self._top_k_spin.setStyleSheet("""
            QSpinBox {
                background-color: #252540;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 4px;
                padding: 4px 8px;
            }
        """)
        top_k_layout.addWidget(self._top_k_spin)

        top_k_layout.addStretch()
        params_layout.addLayout(top_k_layout)

        # Max Tokens
        max_tokens_layout = QHBoxLayout()
        max_tokens_label = QLabel("Max Tokens:")
        max_tokens_label.setStyleSheet("font-size: 10pt; color: #A0A8C0;")
        max_tokens_layout.addWidget(max_tokens_label)

        self._max_tokens_spin = QSpinBox()
        self._max_tokens_spin.setRange(8, 65536)
        self._max_tokens_spin.setValue(2048)
        self._max_tokens_spin.setSingleStep(128)
        max_tokens_layout.addWidget(self._max_tokens_spin)

        max_tokens_layout.addStretch()
        params_layout.addLayout(max_tokens_layout)

        # Frequency Penalty
        freq_pen_layout = QHBoxLayout()
        freq_pen_label = QLabel("Freq. Penalty:")
        freq_pen_label.setStyleSheet("font-size: 10pt; color: #A0A8C0;")
        freq_pen_layout.addWidget(freq_pen_label)

        self._freq_pen_spin = QDoubleSpinBox()
        self._freq_pen_spin.setRange(0.0, 2.0)
        self._freq_pen_spin.setValue(0.0)
        self._freq_pen_spin.setSingleStep(0.1)
        freq_pen_layout.addWidget(self._freq_pen_spin)

        freq_pen_layout.addStretch()
        params_layout.addLayout(freq_pen_layout)

        # Presence Penalty
        pres_pen_layout = QHBoxLayout()
        pres_pen_label = QLabel("Pres. Penalty:")
        pres_pen_label.setStyleSheet("font-size: 10pt; color: #A0A8C0;")
        pres_pen_layout.addWidget(pres_pen_label)

        self._pres_pen_spin = QDoubleSpinBox()
        self._pres_pen_spin.setRange(0.0, 2.0)
        self._pres_pen_spin.setValue(0.0)
        self._pres_pen_spin.setSingleStep(0.1)
        pres_pen_layout.addWidget(self._pres_pen_spin)

        pres_pen_layout.addStretch()
        params_layout.addLayout(pres_pen_layout)

        # Stream checkbox
        self._stream_check = QCheckBox("Stream output")
        self._stream_check.setChecked(True)
        self._stream_check.setStyleSheet("font-size: 10pt; color: #CDD6F4;")
        params_layout.addWidget(self._stream_check)

        right_layout.addWidget(params_group)

        # Stats group
        stats_group = QGroupBox("Session Stats")
        stats_layout = QVBoxLayout(stats_group)
        stats_layout.setSpacing(8)

        self._stats_labels = {}
        stats_items = [
            ("Session ID:", "session_id", "--"),
            ("Messages:", "message_count", "0"),
            ("Total Tokens:", "total_tokens", "0"),
            ("Duration:", "duration", "--"),
            ("Tokens/sec:", "tokens_per_sec", "--"),
        ]

        for label, key, default in stats_items:
            lbl = QLabel(f"{label} {default}")
            lbl.setStyleSheet("font-size: 9pt; color: #A0A8C0;")
            stats_layout.addWidget(lbl)
            self._stats_labels[key] = lbl

        stats_layout.addStretch()
        right_layout.addWidget(stats_group)

        right_layout.addStretch()

        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter)

    def _update_temp_label(self, value: int) -> None:
        """Update the temperature label.

        Args:
            value: Slider position (0-200).
        """
        temp = value / 100.0
        self._temp_value.setText(f"{temp:.2f}")

    def _update_top_p_label(self, value: int) -> None:
        """Update the top-p label.

        Args:
            value: Slider position (0-100).
        """
        top_p = value / 100.0
        self._top_p_value.setText(f"{top_p:.2f}")

    @Slot()
    def new_session(self) -> None:
        """Start a new inference session."""
        self._current_session_id = str(uuid.uuid4())
        self._clear_chat()
        self._stream_output.clear()
        self._stream_output.setVisible(False)
        self._stats_labels["session_id"].setText(f"Session ID: {self._current_session_id[:8]}...")
        self._stats_labels["message_count"].setText("Messages: 0")
        self._stats_labels["total_tokens"].setText("Total Tokens: 0")
        self._stats_labels["duration"].setText("Duration: --")
        self._stats_labels["tokens_per_sec"].setText("Tokens/sec: --")
        logger.info("New inference session started: %s", self._current_session_id)

    @Slot()
    def _clear_chat(self) -> None:
        """Clear all messages from the chat area."""
        # Remove all message widgets except the stretch at the end
        while self._messages_layout.count() > 1:
            item = self._messages_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._messages.clear()

    @Slot()
    def _send_message(self) -> None:
        """Send a message for inference."""
        prompt = self._input_edit.toPlainText().strip()
        if not prompt:
            return

        if self._is_streaming:
            return

        # Disable input during generation
        self._input_edit.setReadOnly(True)
        self._send_btn.setVisible(False)
        self._stop_btn.setVisible(True)

        # Add user message to chat
        user_bubble = MessageBubble(prompt, "user")
        self._add_message_bubble(user_bubble)

        # Clear input
        self._input_edit.clear()

        # Get generation config
        config = self._build_config()

        # Start streaming simulation
        self._is_streaming = True
        self._stream_buffer = ""

        # Add assistant message placeholder
        assistant_bubble = MessageBubble("", "assistant", token_count=0)
        self._add_message_bubble(assistant_bubble)

        # Simulate streaming response
        self._simulate_streaming(assistant_bubble, prompt)

        # Update stats
        self._stats_labels["message_count"].setText(
            f"Messages: {len(self._messages)}"
        )

    def _add_message_bubble(self, bubble: MessageBubble) -> None:
        """Add a message bubble to the chat area.

        Args:
            bubble: The message bubble widget to add.
        """
        # Insert before the stretch
        self._messages_layout.insertWidget(
            self._messages_layout.count() - 1, bubble
        )
        self._messages.append(bubble)

        # Auto-scroll
        parent_scroll = self._find_parent_scroll_area()
        if parent_scroll:
            QTimer.singleShot(100, lambda: self._scroll_to_bottom(parent_scroll))

    def _find_parent_scroll_area(self) -> QScrollArea | None:
        """Find the parent scroll area.

        Returns:
            QScrollArea or None.
        """
        parent = self.parent()
        while parent:
            if isinstance(parent, QScrollArea):
                return parent
            if isinstance(parent, QWidget):
                # Check children
                for child in parent.findChildren(QScrollArea):
                    return child
            parent = parent.parent()
        return None

    def _scroll_to_bottom(self, scroll_area: QScrollArea) -> None:
        """Scroll a scroll area to the bottom.

        Args:
            scroll_area: The scroll area to scroll.
        """
        scrollbar = scroll_area.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def _build_config(self) -> GenerationConfig:
        """Build generation config from UI parameters.

        Returns:
            GenerationConfig instance.
        """
        return GenerationConfig(
            temperature=self._temp_slider.value() / 100.0,
            top_p=self._top_p_slider.value() / 100.0,
            top_k=self._top_k_spin.value(),
            max_tokens=self._max_tokens_spin.value(),
            frequency_penalty=self._freq_pen_spin.value(),
            presence_penalty=self._pres_pen_spin.value(),
            stream=self._stream_check.isChecked(),
        )

    def _simulate_streaming(self, bubble: MessageBubble, prompt: str) -> None:
        """Simulate streaming response for demonstration.

        Args:
            bubble: The assistant message bubble to update.
            prompt: The user's prompt text.
        """
        # Demo responses
        responses = {
            "hello": "Hello! How can I assist you today? I'm running on Ainos, your AI backend platform.",
            "hi": "Hi there! I'm ready to help with any questions or tasks you have.",
            "help": "I can help you with:\n\n1. **Code generation and review**\n2. **Text analysis and summarization**\n3. **Question answering**\n4. **Creative writing**\n5. **Data analysis**\n\nWhat would you like assistance with?",
        }

        # Find matching response or generate generic
        response_text = ""
        for key, resp in responses.items():
            if key in prompt.lower():
                response_text = resp
                break

        if not response_text:
            response_text = (
                f"Thank you for your message. I've received your input and am processing it.\n\n"
                f"You said: \"{prompt[:100]}{'...' if len(prompt) > 100 else ''}\"\n\n"
                f"This is a simulated response from the Ainos inference playground. "
                f"In a production environment, this would be connected to a live AI model "
                f"running on the Ainos backend server. The streaming display shows tokens "
                f"as they are generated by the model in real-time."
            )

        # Simulate character-by-character streaming
        self._stream_chars = list(response_text)
        self._stream_index = 0
        self._stream_start_time = time.time()

        self._stream_timer = QTimer(self)
        self._stream_timer.timeout.connect(lambda: self._stream_next_char(bubble))
        self._stream_timer.start(20)  # 20ms per character

    def _stream_next_char(self, bubble: MessageBubble) -> None:
        """Stream the next character of the response.

        Args:
            bubble: The assistant message bubble to update.
        """
        if self._stream_index < len(self._stream_chars):
            # Stream in chunks of 1-3 chars
            chunk_size = min(3, len(self._stream_chars) - self._stream_index)
            chunk = "".join(self._stream_chars[self._stream_index:self._stream_index + chunk_size])
            self._stream_index += chunk_size
            self._stream_buffer += chunk

            # Update bubble
            bubble.append_content(chunk)

            # Auto-scroll
            parent_scroll = self._find_parent_scroll_area()
            if parent_scroll:
                self._scroll_to_bottom(parent_scroll)

        else:
            # Streaming complete
            self._stream_timer.stop()
            self._is_streaming = False

            # Re-enable input
            self._input_edit.setReadOnly(False)
            self._send_btn.setVisible(True)
            self._stop_btn.setVisible(False)

            # Update stats
            elapsed = time.time() - self._stream_start_time
            token_count = len(self._stream_buffer.split())
            self._stats_labels["total_tokens"].setText(f"Total Tokens: {token_count}")
            self._stats_labels["duration"].setText(f"Duration: {elapsed:.1f}s")
            if elapsed > 0:
                tokens_per_sec = token_count / elapsed
                self._stats_labels["tokens_per_sec"].setText(f"Tokens/sec: {tokens_per_sec:.1f}")

    @Slot()
    def _stop_generation(self) -> None:
        """Stop the current generation."""
        if hasattr(self, '_stream_timer') and self._stream_timer:
            self._stream_timer.stop()

        self._is_streaming = False
        self._input_edit.setReadOnly(False)
        self._send_btn.setVisible(True)
        self._stop_btn.setVisible(False)

        logger.info("Generation stopped by user")

    def apply_theme(self, theme_name: str) -> None:
        """Apply a theme to the inference widget.

        Args:
            theme_name: Theme name ('dark' or 'light').
        """
        self._theme = theme_name

    def cleanup(self) -> None:
        """Cleanup resources."""
        if hasattr(self, '_stream_timer') and self._stream_timer:
            self._stream_timer.stop()