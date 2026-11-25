import sys
import time
import math
import random

try:
    import winsound
except ImportError:  # Не Windows: колокольчик просто не играет.
    winsound = None

from datetime import datetime
from pathlib import Path

import table
from PySide6.QtCore import Qt, QTimer, QPointF, QUrl, QObject, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtWidgets import QApplication, QWidget, QLabel
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


BASE_DIR = Path(__file__).resolve().parent
ASSETS = BASE_DIR / "assets"

PIG_SIZE = int(130 * 1.67)
RUN_PIG_SIZE = int(PIG_SIZE * 1.5)
EXIT_MARGIN = RUN_PIG_SIZE * 2
INTRO_FRAME = "pig_bell.png"
IDLE_FRAME = "pig_idle.png"
SHEET_PATH = ASSETS / "spritesheets" / "pig_animation_spritesheet.png"
SHEET_COLS = 6
SHEET_ROWS = 3
SHEET_FRAMES_PER_SIDE = 9
SHEET_INSET = 8
FRAME_MS = 110
EDGE_MARGIN = 40
BELL_MS = 1800
TICK_MS = 250
TEST_WORK_MIN = 0.1
TEST_BREAK_MIN = 0.05
TIMER_WIDTH = 240
TIMER_HEIGHT = 48
WORK_TEXT_SHIFT = 24
TOP_TEXT_SHIFT = 20
LEFT_TEXT_SHIFT = 20
BOTTOM_TEXT_SHIFT = 20

WORK_MINUTES = 45
BREAK_MINUTES = 15
SLOT_CHECK_MS = 1000
SCHEDULE_RELOAD_MS = 10 * 60 * 1000


def play_bell_sound(path):
    """Воспроизведение WAV-файла колокольчика (только на Windows)."""
    if winsound is None or not path.exists():
        return

    try:
        winsound.PlaySound(
            str(path),
            winsound.SND_FILENAME | winsound.SND_ASYNC
        )
    except RuntimeError:
        print("Не удалось воспроизвести bell.wav")


def ask_minutes(label, default):
    """Спрашиваем длительность фазы в минутах при запуске скрипта."""
    while True:
        raw = input(f"{label} [{default} мин]: ").strip().replace(",", ".")

        if not raw:
            return default * 60 * 1000

        try:
            value = float(raw)
        except ValueError:
            print("Введите число минут, например 25 или 0.1.")
            continue

        if value <= 0:
            print("Время должно быть больше нуля.")
            continue

        return round(value * 60 * 1000)


def scaled_pixmap(path, size=PIG_SIZE):
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return pixmap

    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation
    )


def load_sheet_frames(sheet, start_col, size=PIG_SIZE):
    """Берёт 3 столбца x 3 ряда кадров для одного направления."""
    frames = []
    frame_width = sheet.width() // SHEET_COLS

    for row in range(SHEET_ROWS):
        y0 = round(row * sheet.height() / SHEET_ROWS)
        y1 = round((row + 1) * sheet.height() / SHEET_ROWS)

        for col in range(start_col, start_col + 3):
            pixmap = sheet.copy(
                col * frame_width + SHEET_INSET,
                y0 + SHEET_INSET,
                frame_width - 2 * SHEET_INSET,
                y1 - y0 - 2 * SHEET_INSET
            )
            frames.append(
                pixmap.scaled(
                    size,
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            )

    return frames[:SHEET_FRAMES_PER_SIDE]


class ErrorWidget(QLabel):
    """Сообщение об ошибке получения расписания поверх всех окон."""

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(TIMER_WIDTH * 3, TIMER_HEIGHT * 4)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet(
            """
            QLabel {
                background-color: rgba(60, 20, 24, 235);
                color: #ffb3b3;
                font-size: 30px;
                font-weight: bold;
                border: 2px solid #d66b7a;
                border-radius: 20px;
                padding: 16px;
            }
            """
        )
        self.hide()

    def show_error(self, message):
        self.setText("Не удалось получить расписание:\n" + str(message))
        self.show()
        self.raise_()

    def clear(self):
        self.hide()


class TimerWidget(QLabel):
    """Всегда видимый таймер: над свинкой во время работы и сверху экрана в отдых."""

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(TIMER_WIDTH * 2, TIMER_HEIGHT * 2)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_offset = (0, 0)
        self.setStyleSheet(
            """
            QLabel {
                background-color: rgba(28, 28, 34, 215);
                color: white;
                font-size: 38px;
                font-weight: bold;
                border-radius: 24px;
            }
            """
        )
        self.hide()

    def set_text_offset(self, dx=0, dy=0):
        """Сдвигает текст внутри виджета, не двигая сам виджет."""
        offset = (dx, dy)
        if offset == self.text_offset:
            return

        self.text_offset = offset
        # Центр текста смещается на половину величины отступа.
        self.setContentsMargins(0, 0, 2 * dx, 2 * dy)

    def set_text(self, text):
        if self.text() != text:
            self.setText(text)

    def set_remaining(self, label, seconds):
        minutes, secs = divmod(seconds, 60)
        self.set_text(f"{label}: {minutes:02d}:{secs:02d}")

    def set_countdown(self, label, seconds):
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        if hours:
            self.set_text(f"{label}: {hours:02d}:{minutes:02d}:{secs:02d}")
        else:
            self.set_text(f"{label}: {minutes:02d}:{secs:02d}")


class IntroWidget(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(PIG_SIZE, PIG_SIZE)

        self.pixmap = scaled_pixmap(ASSETS / INTRO_FRAME)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)

        self.started = 0

    def show_intro(self, x, y):
        self.move(x, y)
        self.started = 0
        self.timer.start(30)
        self.show()
        self.raise_()

    def stop_intro(self):
        self.timer.stop()
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        self.started += 1

        if self.pixmap.isNull():
            painter.setPen(QColor("#D66B91"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "🐷"
            )
            return

        offset = math.sin(self.started * 0.18) * 8
        x = (self.width() - self.pixmap.width()) // 2
        y = (self.height() - self.pixmap.height()) // 2 + offset

        painter.drawPixmap(int(x), int(y), self.pixmap)


class PigWidget(QWidget):
    run_finished = Signal()

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(PIG_SIZE, PIG_SIZE)

        sheet = QPixmap(str(SHEET_PATH))
        self.left_frames = []
        self.right_frames = []
        self.run_left_frames = []
        self.run_right_frames = []

        if not sheet.isNull():
            self.left_frames = load_sheet_frames(sheet, 0)
            self.right_frames = load_sheet_frames(sheet, 3)
            self.run_left_frames = load_sheet_frames(sheet, 0, RUN_PIG_SIZE)
            self.run_right_frames = load_sheet_frames(sheet, 3, RUN_PIG_SIZE)

        self.frames = self.left_frames
        self.idle_pixmap = scaled_pixmap(ASSETS / IDLE_FRAME)

        self.frame_index = 0
        self.sleeping = False
        self.sleep_tick = 0

        self.frame_timer = QTimer(self)
        self.frame_timer.timeout.connect(self.next_frame)
        self.frame_timer.start(FRAME_MS)

        self.move_timer = QTimer(self)
        self.move_timer.timeout.connect(self.move_step)

        self.progress = 0
        self.duration = 250

        self.start_point = QPointF()
        self.end_point = QPointF()
        self.screen_rect = None
        self.off_screen_detected = False
        self.spawn_left = False
        self.spawn_top = False
        self.spawn_bottom = False
        self.last_corner = None
        self.last_run_direction = None

        self.hide()

    def next_frame(self):
        self.sleep_tick += 1

        if self.frames:
            self.frame_index = (
                self.frame_index + 1
            ) % len(self.frames)

            self.update()

    def show_idle(self):
        # Idle-свинка показывается только во время работы.
        if not self.idle_pixmap.isNull():
            self.frames = [self.idle_pixmap]
            self.frame_index = 0

        self.resize(PIG_SIZE, PIG_SIZE)

        if self.screen_rect is not None:
            rect = self.screen_rect
            corners = [
                (rect.left(), rect.top()),
                (rect.right() - self.width() + 1, rect.top()),
                (rect.left(), rect.bottom() - self.height() + 1),
                (
                    rect.right() - self.width() + 1,
                    rect.bottom() - self.height() + 1
                )
            ]
            # Не повторяем предыдущий угол: он исключается из выбора,
            # пока есть другие варианты.
            variants = [c for c in corners if c != self.last_corner] or corners
            x, y = random.choice(variants)
            self.last_corner = (x, y)
            self.spawn_left = x == rect.left()
            self.spawn_top = y == rect.top()
            self.spawn_bottom = y == rect.bottom() - self.height() + 1

            # У левого края сдвигаем свинку внутрь экрана, у правого — влево.
            shift = (
                WORK_TEXT_SHIFT
                if x == rect.left()
                else -WORK_TEXT_SHIFT
            )
            self.move(x + shift, y)

        self.show()
        self.raise_()
        self.update()

    def is_off_screen(self):
        g = self.geometry()
        r = self.screen_rect

        return (
            g.right() < r.left()
            or g.left() > r.right()
            or g.bottom() < r.top()
            or g.top() > r.bottom()
        )

    def begin_run(self, screen):
        rect = screen.availableGeometry()
        self.screen_rect = rect
        self.sleeping = False

        # Направления строго по диагонали экрана: ↘, ↙, ↗, ↖.
        directions = ((1, 1), (-1, 1), (1, -1), (-1, -1))
        variants = [
            d for d in directions if d != self.last_run_direction
        ] or directions
        sign_x, sign_y = random.choice(variants)
        self.last_run_direction = (sign_x, sign_y)

        sx = rect.left() if sign_x > 0 else rect.right() - RUN_PIG_SIZE + 1
        sy = rect.top() if sign_y > 0 else rect.bottom() - RUN_PIG_SIZE + 1

        # Вектор диагонали экрана. Конец траектории лежит на той же
        # прямой, но за пределами монитора, чтобы свинка сначала
        # убегала за край и только потом скрывалась.
        diag_x = rect.right() - rect.left()
        diag_y = rect.bottom() - rect.top()
        dx = sign_x * diag_x
        dy = sign_y * diag_y

        factor = 1 + EXIT_MARGIN / max(1, min(diag_x, diag_y))
        ex = sx + dx * factor
        ey = sy + dy * factor

        self.start_point = QPointF(sx, sy)
        self.end_point = QPointF(ex, ey)

        # В спрайтшите первые 3 столбца — свинка смотрит влево,
        # последние 3 столбца — вправо. Во время бега свинка крупнее.
        self.frames = (
            self.run_right_frames if dx > 0 else self.run_left_frames
        )
        self.frame_index = 0
        self.progress = 0
        self.off_screen_detected = False

        self.resize(RUN_PIG_SIZE, RUN_PIG_SIZE)
        self.move(int(sx), int(sy))
        self.show()
        self.raise_()

        self.move_timer.start(16)

    def move_step(self):
        self.progress += 1
        t = min(self.progress / self.duration, 1.0)

        x = self.start_point.x() + (
            self.end_point.x() - self.start_point.x()
        ) * t

        y = self.start_point.y() + (
            self.end_point.y() - self.start_point.y()
        ) * t

        self.move(int(x), int(y))

        if (
            not self.off_screen_detected
            and self.screen_rect is not None
            and self.is_off_screen()
        ):
            self.off_screen_detected = True
            self.move_timer.stop()
            self.run_finished.emit()
            return

        if t >= 1.0:
            self.move_timer.stop()
            if not self.off_screen_detected:
                self.off_screen_detected = True
                self.run_finished.emit()

    def paintEvent(self, event):
        if not self.frames:
            painter = QPainter(self)
            painter.setPen(QColor("#D66B91"))

            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "🐷"
            )
            return

        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform
        )

        pixmap = self.frames[self.frame_index]

        x = (self.width() - pixmap.width()) // 2
        y = (self.height() - pixmap.height()) // 2

        painter.drawPixmap(x, y, pixmap)

        if self.sleeping:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QColor("#b9d4ff"))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(20)
            painter.setFont(font)

            for index in range(3):
                rise = (self.sleep_tick + index * 12) % 36
                z_x = 12 + index * 22
                z_y = max(4, 48 - rise)
                painter.drawText(z_x, z_y, "z")


class Assistant(QObject):
    def __init__(self, app, test=False):
        super().__init__()

        self.app = app
        self.test_mode = test

        print(" Pomodoro со свинкой")
        if test:
            # В тесте длительности короткие и спрашиваются у пользователя.
            self.work_ms = ask_minutes("Время работы", TEST_WORK_MIN)
            self.break_ms = ask_minutes("Время отдыха", TEST_BREAK_MIN)
        else:
            # Обычный режим: фиксированные 45/15 внутри активного слота.
            self.work_ms = WORK_MINUTES * 60 * 1000
            self.break_ms = BREAK_MINUTES * 60 * 1000

        # Звуковые файлы
        self.bell_sound = ASSETS / "bell.wav"
        self.pig_sound = ASSETS / "pig_oink.mp3"

        # MP3-плеер для звука свинки
        self.pig_player = QMediaPlayer(self)
        self.pig_audio = QAudioOutput(self)

        self.pig_player.setAudioOutput(self.pig_audio)
        self.pig_audio.setVolume(0.8)

        self.pig_player.errorOccurred.connect(
            self.on_audio_error
        )

        self.timer_widget = TimerWidget()
        self.error_widget = ErrorWidget()
        self.intro = IntroWidget()
        self.pig = PigWidget()
        self.pig.run_finished.connect(self.on_run_finished)

        self.state = "idle"
        self.phase_end = 0.0
        self.screen = None
        self.next_after_run = "break"
        self.run_token = 0
        self.last_intro_corner = None

        self.schedule = []
        self.current_slot = None
        self.active_slot = None
        self.schedule_ready = False

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.tick)

        self.slot_timer = QTimer(self)
        self.slot_timer.timeout.connect(self.update_slot)

        self.reload_timer = QTimer(self)
        self.reload_timer.timeout.connect(self.reload_schedule)

        self.idle_follow_timer = QTimer(self)
        self.idle_follow_timer.timeout.connect(self.place_timer_above_pig)

    def on_audio_error(self, error, error_string):
        print("Ошибка звука свинки:", error_string)

    def play_pig_sound(self):
        if self.pig_sound.exists():
            self.pig_player.stop()

            self.pig_player.setSource(
                QUrl.fromLocalFile(str(self.pig_sound))
            )

            self.pig_player.play()
        else:
            print("Файл pig_oink.mp3 не найден:", self.pig_sound)

    def place_timer_above_pig(self):
        rect = self.pig.screen_rect

        if rect is None:
            return

        # Центрируем строго над свинкой и не сдвигаем по X.
        x = self.pig.x() + (
            self.pig.width() - self.timer_widget.width()
        ) // 2
        y = self.pig.y() - self.timer_widget.height() - 4

        # Если сверху нет места, показываем таймер внутри верхней части свинки.
        top_spawn = y < rect.top() + 4
        if top_spawn:
            y = self.pig.y() + 4

        # У левого края дополнительно сдвигаем текст внутрь экрана,
        # у верхнего/нижнего края — вверх/вниз соответственно.
        dx = (
            WORK_TEXT_SHIFT - LEFT_TEXT_SHIFT
            if self.pig.spawn_left
            else WORK_TEXT_SHIFT
        )
        if self.pig.spawn_top or top_spawn:
            dy = TOP_TEXT_SHIFT
        elif self.pig.spawn_bottom:
            dy = -BOTTOM_TEXT_SHIFT
        else:
            dy = 0

        self.timer_widget.set_text_offset(dx, dy)

        self.timer_widget.move(x, y)

    def place_timer_top(self):
        rect = (
            self.screen.availableGeometry()
            if self.screen is not None
            else None
        )

        if rect is None:
            return

        x = (
            rect.left() + rect.right() - self.timer_widget.width()
        ) // 2
        self.timer_widget.move(x, rect.top() + 20)

    def place_error(self):
        screens = self.app.screens()
        if not screens:
            return

        rect = screens[0].availableGeometry()
        x = (rect.left() + rect.right() - self.error_widget.width()) // 2
        y = (rect.top() + rect.bottom() - self.error_widget.height()) // 2
        self.error_widget.move(x, y)

    def reload_schedule(self):
        try:
            slots = table.load_slots()
        except Exception as exc:
            message = str(exc)
            print("Ошибка расписания:", message)
            self.error_widget.show_error(message)
            self.place_error()
            return

        self.error_widget.clear()
        self.schedule = slots
        self.schedule_ready = True

        try:
            path = table.export_slots(slots)
            print("Расписание сохранено:", path)
        except Exception as exc:
            print("Не удалось сохранить расписание:", exc)

        self.update_slot()

    def update_slot(self, force=False):
        if not self.schedule_ready:
            return

        slot = table.current_slot(self.schedule)
        key = slot.key() if slot is not None else None
        current_key = (
            self.current_slot.key() if self.current_slot is not None else None
        )

        if key == current_key and not force:
            if slot is None:
                return
            if slot.active:
                self.clip_phase_to_slot(slot)
            else:
                self.update_sleep_time(slot)
            return

        self.current_slot = slot
        # Слот сменился: отменяем отложенный запуск старого бега.
        self.run_token += 1
        if slot is None:
            self.start_sleep(None)
        elif slot.active:
            self.start_active_slot(slot)
        else:
            self.start_sleep(slot)

    def clip_phase_to_slot(self, slot):
        if self.state not in ("work", "break"):
            return

        end_ms = slot.end.timestamp() * 1000
        if self.phase_end > end_ms:
            self.phase_end = end_ms

    def phase_duration(self, base_ms):
        if self.test_mode or self.active_slot is None:
            return base_ms

        left_ms = (
            self.active_slot.end - datetime.now().astimezone()
        ).total_seconds() * 1000
        return min(base_ms, max(0, int(left_ms)))

    def start_active_slot(self, slot):
        # Начало активного слота: сразу показываем анимацию бега.
        self.active_slot = slot
        self.pig.sleeping = False
        self.state = "run"
        self.next_after_run = "work"

        self.idle_follow_timer.stop()
        self.pig.move_timer.stop()
        self.intro.stop_intro()
        self.pig.hide()
        self.timer_widget.hide()

        screens = self.app.screens()
        if not screens:
            self.on_run_finished()
            return

        screen = screens[0]
        self.screen = screen
        self.pig.begin_run(screen)

    def start_sleep(self, slot):
        # Неактивный слот: спящая свинка и время до конца слота.
        self.state = "sleep"
        self.active_slot = None
        self.run_token += 1

        self.idle_follow_timer.stop()
        self.pig.move_timer.stop()
        self.intro.stop_intro()

        self.timer_widget.set_text_offset(0, 0)
        self.pig.sleeping = True

        screens = self.app.screens()
        if screens:
            self.screen = screens[0]
            self.pig.screen_rect = self.screen.availableGeometry()

        self.pig.show_idle()
        self.timer_widget.show()
        self.timer_widget.raise_()
        self.place_timer_top()

        if slot is None:
            self.timer_widget.set_text("Ожидание слота")
        else:
            self.update_sleep_time(slot)

    def update_sleep_time(self, slot):
        if self.state != "sleep":
            return

        remaining = table.seconds_until_end(slot)
        self.timer_widget.set_countdown(slot.name, remaining)

    def tick(self):
        if self.state == "run":
            # Во время бега таймер не показываем.
            return

        if self.state not in ("work", "break"):
            return

        if not self.test_mode and self.schedule_ready:
            self.update_slot()
            if self.state not in ("work", "break"):
                return

        remaining = max(
            0,
            math.ceil((self.phase_end - time.monotonic() * 1000) / 1000)
        )
        label = "Работа" if self.state == "work" else "Отдых"
        self.timer_widget.set_remaining(label, remaining)

        if remaining == 0:
            if self.state == "work":
                self.start_run(next_state="break")
            else:
                self.start_run(next_state="work")

    def start_work(self):
        # Работа: видна свинка и таймер до конца рабочего интервала.
        self.state = "work"
        self.pig.sleeping = False
        self.phase_end = (
            time.monotonic() * 1000 + self.phase_duration(self.work_ms)
        )

        screens = self.app.screens()
        if screens:
            self.screen = screens[0]
            self.pig.screen_rect = self.screen.availableGeometry()

        self.pig.show_idle()
        self.timer_widget.set_text_offset(WORK_TEXT_SHIFT, 0)
        self.timer_widget.show()
        self.timer_widget.raise_()
        self.place_timer_above_pig()
        self.idle_follow_timer.start(TICK_MS)
        self.tick()

    def start_run(self, next_state="break"):
        # Фаза закончилась: колокольчик, вступление и бег свинки.
        self.state = "run"
        self.next_after_run = next_state
        self.idle_follow_timer.stop()
        self.pig.hide()
        screens = self.app.screens()

        if not screens:
            # Экрана нет: бег невозможен, сразу идём в следующую фазу.
            self.run_token += 1
            self.on_run_finished()
            return

        # Отменяем отложенный запуск бега, если до колокольчика
        # успела начаться новая фаза.
        self.run_token += 1
        token = self.run_token

        screen = random.choice(screens)
        self.screen = screen
        rect = screen.availableGeometry()

        left_x = rect.left() + EDGE_MARGIN
        right_x = rect.right() - PIG_SIZE - EDGE_MARGIN
        top_y = rect.top() + EDGE_MARGIN
        bottom_y = rect.bottom() - PIG_SIZE - EDGE_MARGIN

        corners = [
            (left_x, top_y), (right_x, top_y),
            (left_x, bottom_y), (right_x, bottom_y)
        ]
        variants = [
            c for c in corners if c != self.last_intro_corner
        ] or corners
        x, y = random.choice(variants)
        self.last_intro_corner = (x, y)

        self.timer_widget.hide()

        self.intro.show_intro(x, y)
        play_bell_sound(self.bell_sound)

        def start_pig():
            if token != self.run_token or self.state != "run":
                return
            self.intro.stop_intro()
            self.play_pig_sound()
            self.pig.begin_run(screen)

        QTimer.singleShot(BELL_MS, start_pig)

    def start_break(self):
        # Отдых: таймер сверху экрана, свинки нет.
        self.state = "break"
        self.pig.sleeping = False
        self.phase_end = (
            time.monotonic() * 1000 + self.phase_duration(self.break_ms)
        )

        self.timer_widget.set_text_offset(0, 0)
        self.timer_widget.show()
        self.timer_widget.raise_()
        self.place_timer_top()
        self.tick()

    def on_run_finished(self):
        # Свинка убежала: переходим к следующей фазе.
        self.idle_follow_timer.stop()
        self.pig.hide()
        self.intro.stop_intro()

        if self.next_after_run == "work":
            self.start_work()
        else:
            self.start_break()

    def start(self):
        self.tick_timer.start(TICK_MS)

        if self.test_mode:
            # В тесте первым делом идёт работа с введёнными длительностями.
            self.start_work()
            return

        self.slot_timer.start(SLOT_CHECK_MS)
        self.reload_timer.start(SCHEDULE_RELOAD_MS)
        self.reload_schedule()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    assistant = Assistant(app, test="--test" in sys.argv)
    assistant.start()

    sys.exit(app.exec())
