# pyqt_convert_png_to_webp.py
# Requires: py -3.13 -m pip install PyQt6 Pillow
import os
import shutil
import sys
from dataclasses import dataclass
from PIL import Image

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QProgressBar, QTextEdit, QFileDialog, QCheckBox, QLineEdit
)


@dataclass
class JobConfig:
    folder: str
    keep_backup: bool
    overwrite: bool
    no_alpha: bool  # if True -> lossy WebP (RGB), drops transparency


class ConverterWorker(QObject):
    progress = pyqtSignal(int)           # 0..100
    log = pyqtSignal(str)                # log lines
    done = pyqtSignal(int)               # converted count
    error = pyqtSignal(str)              # fatal error

    def __init__(self, cfg: JobConfig):
        super().__init__()
        self.cfg = cfg
        self._stopped = False
        self._lossy_quality = 90  # fixed as requested

    def stop(self):
        self._stopped = True

    def _convert_one(self, src_png: str, dst_webp: str):
        """PNG -> WebP.
        - If cfg.no_alpha: lossy (RGB), drops transparency, quality=90.
        - Else: lossless (preserve alpha if present).
        """
        with Image.open(src_png) as im:
            if self.cfg.no_alpha:
                im = im.convert("RGB")
                im.save(dst_webp, "WEBP", quality=self._lossy_quality, method=6)
            else:
                mode = "RGBA" if im.mode in ("RGBA", "LA") else "RGB"
                im = im.convert(mode)
                im.save(dst_webp, "WEBP", lossless=True, method=6)

    def run(self):
        try:
            folder = self.cfg.folder.rstrip("/\\")
            if not os.path.isdir(folder):
                self.error.emit(f"Folder not found: {folder}")
                return

            folder_name = os.path.basename(folder)
            parent_dir = os.path.dirname(folder)
            backup_folder = os.path.join(parent_dir, f"{folder_name}_PNG")

            pngs = [f for f in os.listdir(folder) if f.lower().endswith(".png")]
            total = len(pngs)
            if total == 0:
                self.log.emit("No PNG files found in the selected folder.")
                self.done.emit(0)
                return

            mode_text = "LOSSY (no transparency, q=90)" if self.cfg.no_alpha else "LOSSLESS (preserve transparency)"
            self.log.emit(f"Mode: {mode_text}")

            if self.cfg.keep_backup:
                os.makedirs(backup_folder, exist_ok=True)
                self.log.emit(f"Backup folder: {backup_folder}")

            converted = 0
            for i, fname in enumerate(pngs, start=1):
                if self._stopped:
                    self.log.emit("Stopped by user.")
                    break

                src = os.path.join(folder, fname)
                dst_name = os.path.splitext(fname)[0] + ".webp"
                dst = os.path.join(folder, dst_name)

                # Skip if exists and not overwriting
                if not self.cfg.overwrite and os.path.exists(dst):
                    self.log.emit(f"Skip (already exists): {dst_name}")
                    self.progress.emit(int(i * 100 / total))
                    continue

                try:
                    if self.cfg.keep_backup:
                        bak = os.path.join(backup_folder, fname)
                        if not os.path.exists(bak):
                            shutil.move(src, bak)
                        src_for_convert = bak
                    else:
                        src_for_convert = src

                    self._convert_one(src_for_convert, dst)
                    self.log.emit(f"Converted: {fname} → {dst_name}")
                    converted += 1

                    if not self.cfg.keep_backup and os.path.exists(src):
                        try:
                            os.remove(src)
                        except Exception as e_rm:
                            self.log.emit(f"Warn: failed to delete original {fname}: {e_rm}")

                except Exception as e:
                    self.log.emit(f"Failed: {fname} -> {e}")

                self.progress.emit(int(i * 100 / total))

            self.done.emit(converted)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PNG → WebP (Lossless or Lossy No-Alpha)")
        self.setMinimumWidth(720)

        self.hint = QLabel("Step 1) Select Folder   →   Step 2) Click Convert")
        font = self.hint.font()
        font.setPointSize(font.pointSize() + 1)
        font.setBold(True)
        self.hint.setFont(font)

        # Folder row
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("No folder selected")
        self.folder_edit.setReadOnly(True)
        self.btn_pick = QPushButton("Select Folder")

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Folder:"))
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.btn_pick)

        # Options
        self.chk_backup = QCheckBox("Keep backup <Folder>_PNG")
        self.chk_backup.setChecked(True)

        self.chk_overwrite = QCheckBox("Overwrite existing .webp")
        self.chk_overwrite.setChecked(False)

        self.chk_no_alpha = QCheckBox("Convert WITHOUT transparency (lossy WebP q=90)")
        self.chk_no_alpha.setChecked(False)

        opts = QHBoxLayout()
        opts.addWidget(self.chk_backup)
        opts.addWidget(self.chk_overwrite)
        opts.addWidget(self.chk_no_alpha)
        opts.addStretch(1)

        # Actions
        self.btn_convert = QPushButton("Convert")
        self.btn_convert.setEnabled(False)  # disabled until a folder is picked
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)

        actions = QHBoxLayout()
        actions.addWidget(self.btn_convert)
        actions.addWidget(self.btn_stop)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.hint)
        layout.addLayout(folder_row)
        layout.addLayout(opts)
        layout.addLayout(actions)
        layout.addWidget(self.progress)
        layout.addWidget(self.log, 1)

        self.selected_folder = None
        self.thread = None
        self.worker = None

        self.btn_pick.clicked.connect(self.pick_folder)
        self.btn_convert.clicked.connect(self.start_convert)
        self.btn_stop.clicked.connect(self.stop_convert)

        # Initial tip
        self.log.append("Ready. Select a folder that contains .png files.")

    def pick_folder(self):
        dlg_opts = QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        folder = QFileDialog.getExistingDirectory(self, "Select folder containing PNG files", options=dlg_opts)
        if folder:
            self.selected_folder = folder
            self.folder_edit.setText(folder)
            self.btn_convert.setEnabled(True)
            self.log.append(f"Selected folder: {folder}")

    def start_convert(self):
        if not self.selected_folder:
            self.log.append("Select a folder first.")
            return

        cfg = JobConfig(
            folder=self.selected_folder,
            keep_backup=self.chk_backup.isChecked(),
            overwrite=self.chk_overwrite.isChecked(),
            no_alpha=self.chk_no_alpha.isChecked()
        )

        # UI lock
        self.progress.setValue(0)
        self.btn_convert.setEnabled(False)
        self.btn_pick.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.chk_backup.setEnabled(False)
        self.chk_overwrite.setEnabled(False)
        self.chk_no_alpha.setEnabled(False)
        self.log.append("Starting conversion...")

        # Worker thread
        self.thread = QThread()
        self.worker = ConverterWorker(cfg)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.log.connect(self.log.append)
        self.worker.done.connect(self.on_done)
        self.worker.error.connect(self.on_error)

        # Cleanup
        self.worker.done.connect(self.thread.quit)
        self.worker.error.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()

    def stop_convert(self):
        if self.worker:
            self.worker.stop()
            self.log.append("Stopping...")

    def on_done(self, count: int):
        self.log.append(f"\nDone. Converted {count} file(s).")
        self._unlock_ui()

    def on_error(self, msg: str):
        self.log.append(f"\nError: {msg}")
        self._unlock_ui()

    def _unlock_ui(self):
        self.btn_convert.setEnabled(bool(self.selected_folder))
        self.btn_pick.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.chk_backup.setEnabled(True)
        self.chk_overwrite.setEnabled(True)
        self.chk_no_alpha.setEnabled(True)
        self.worker = None
        self.thread = None


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
