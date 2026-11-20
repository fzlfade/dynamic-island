"""Ask Claude from the notch: Ctrl+Alt+Space, type a question, the answer streams into the island."""
import threading

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics

from island.pages import Page

HOTKEY_ID = 2
MODEL = "claude-opus-5-5"
ASK_SYSTEM = ("You answer inside a small notch at the top of a Windows desktop. "
              "Reply in at most three short sentences of plain text, no Markdown.")
NO_CREDENTIALS = "Set ANTHROPIC_API_KEY or run: ant auth login"


class Asker(QObject):
    """Streams one answer on a worker thread; results arrive through the signals."""
    chunk = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.thread = None

    def ask(self, question, client=None):
        self.thread = threading.Thread(target=self._run, args=(question, client), daemon=True)
        self.thread.start()

    def _run(self, question, client):
        import anthropic
        try:
            client = client or anthropic.Anthropic()  # env var or `ant auth login` profile; no key in our files
            parts = []
            with client.beta.messages.stream(
                model=MODEL, max_tokens=64000,
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",  # retry a refusal on another model
                output_config={"effort": "low"},
                system=ASK_SYSTEM, messages=[{"role": "user", "content": question}],
            ) as stream:
                for text in stream.text_stream:
                    parts.append(text)
                    self.chunk.emit(text)
                final = stream.get_final_message()
            if final.stop_reason == "refusal":
                self.failed.emit("Claude declined this one.")
            else:
                self.finished.emit("".join(parts))
        except anthropic.AuthenticationError:  # status-error subclasses first: they'd also match APIStatusError
            self.failed.emit(NO_CREDENTIALS)
        except anthropic.RateLimitError:
            self.failed.emit("Busy right now, try again shortly")
        except anthropic.APIStatusError as e:
            self.failed.emit(f"Error {e.status_code}")
        except anthropic.APIConnectionError:
            self.failed.emit("No connection")
        except anthropic.AnthropicError:  # e.g. no credentials found when building the client
            self.failed.emit(NO_CREDENTIALS)


class AskPage(Page):
    title = "Ask"
    FONT = QFont("Segoe UI Variable Text", 10)

    def __init__(self):
        self.question, self.text, self.state = "", "", "idle"
        self.shown = ""  # the tail of the answer that fits, set on each draw

    def start(self, question):
        self.question, self.text, self.state = question, "", "streaming"

    def add(self, chunk):
        self.text += chunk

    def finish(self):
        self.state = "done"

    def fail(self, message):
        self.text, self.state = message, "error"

    def animating(self):
        return self.state == "streaming"

    def draw(self, p, r, island):
        if self.state == "idle":
            island._text(p, QRectF(r), "Press Ctrl+Alt+Space to ask Claude", 11, QColor(140, 140, 140), Qt.AlignCenter)
            return
        island._text(p, QRectF(r.left() + 22, r.top() + 10, r.width() - 44, 20), self.question, 10,
                     QColor(150, 150, 155), Qt.AlignLeft)
        box = QRectF(r.left() + 22, r.top() + 32, r.width() - 44, r.height() - 56)
        self.shown = self._tail_that_fits(self.text or "…", box)
        p.setFont(self.FONT)
        p.setPen(QColor(255, 120, 110) if self.state == "error" else QColor(255, 255, 255))
        p.drawText(box, Qt.AlignLeft | Qt.AlignBottom | Qt.TextWordWrap, self.shown)

    def _tail_that_fits(self, text, box):
        """Drop leading words until the wrapped text fits, so the newest lines stay visible."""
        fm, words = QFontMetrics(self.FONT), text.split(" ")
        for start in range(len(words)):
            tail = " ".join(words[start:])
            if fm.boundingRect(box.toRect(), Qt.TextWordWrap, tail).height() <= box.height():
                return tail
        return words[-1]

    def click(self, pos, button, island):
        self.state = "idle"  # a click on the answer closes it
        island._animate_to(0.0)
        return True
