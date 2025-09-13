# delta_pix.py — "DeltaPix" image converter/viewer
# Requires: Python 3.13+  |  pip install PyQt6 Pillow

import os
import sys
import io
from dataclasses import dataclass
from typing import List, Optional, Tuple
from PyQt6.QtGui import QImage, QPen, QBrush, QColor
from PyQt6.QtCore import Qt, QRectF, QSettings, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QPixmap, QPainter
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QMessageBox, QGraphicsView, QGraphicsScene,
    QGraphicsRectItem, QDockWidget, QListWidget, QListWidgetItem, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QMenu, QFormLayout, QSpinBox, QCheckBox,
    QDialog, QDialogButtonBox, QSlider, QStyle, QToolBar
)
from PIL import Image

SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".webp"}

# =========================
# Utilities
# =========================
def is_image_file(path: str) -> bool:
    return os.path.splitext(path.lower())[1] in SUPPORTED_EXT

def load_image(path: str) -> Optional[Image.Image]:
    try:
        im = Image.open(path)
        im.load()
        copy = im.copy()
        im.close()
        return copy
    except Exception as e:
        print(f"load_image error: {e}")
        return None

def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    """Safe conversion from PIL.Image to QPixmap without ImageQt segfaults."""
    try:
        if img.mode == "RGB":
            r, g, b = img.split()
            img = Image.merge("RGB", (b, g, r))  # swap to BGR
            data = img.tobytes()
            qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGB888)
        elif img.mode == "RGBA":
            r, g, b, a = img.split()
            img = Image.merge("RGBA", (b, g, r, a))  # BGRA
            data = img.tobytes()
            qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        else:
            img = img.convert("RGBA")
            r, g, b, a = img.split()
            img = Image.merge("RGBA", (b, g, r, a))
            data = img.tobytes()
            qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(qimg)
    except Exception as e:
        print(f"pil_to_qpixmap error: {e}")
        pm = QPixmap(1, 1)
        pm.fill(Qt.GlobalColor.transparent)
        return pm

def estimate_encoded_size(img: Image.Image, fmt: str, **options) -> Tuple[int, bytes]:
    buf = io.BytesIO()
    if fmt == "JPEG":
        img = img.convert("RGB")
    img.save(buf, fmt, **options)
    data = buf.getvalue()
    return len(data), data

def human_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"

# =========================
# Graphics View (Zoom/Pan + Editing)
# =========================
class EditableRect(QGraphicsRectItem):
    def __init__(self, rect):
        super().__init__(rect)
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsRectItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setBrush(QColor("red"))     # default fill
        self.setPen(QColor("black"))     # default border
        self.setZValue(10)

    def contextMenuEvent(self, event):
        color = QColorDialog.getColor()
        if color.isValid():
            self.setBrush(color)


# =========================
# ImageView = only view
# =========================
class ImageView(QGraphicsView):
    zoom_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(
            self.renderHints()
            | QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._pixmap_item = None
        self._zoom_factor = 1.0

    def set_image(self, qpix: QPixmap):
        self.scene().clear()
        self._pixmap_item = self.scene().addPixmap(qpix)
        self.scene().setSceneRect(QRectF(qpix.rect()))
        self._zoom_factor = 1.0
        self.fit_in_view()

    def fit_in_view(self):
        if not self._pixmap_item:
            return
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.resetTransform()
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom_factor = 1.0
        self.zoom_changed.emit(self._zoom_factor)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self._zoom_factor *= factor
        self.zoom_changed.emit(self._zoom_factor)

    def add_square(self):
        rect = EditableRect(QRectF(0, 0, 200, 200))
        self.scene().addItem(rect)
        rect.setPos(50, 50)
        return rect


# =========================
# MainWindow handles layers
# =========================
class DeltaPix(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DeltaPix")
        self.resize(1200, 800)

        # Center view
        self.view = ImageView()
        self.setCentralWidget(self.view)

        # Layers dock
        self.layers_list = QListWidget()
        dock_layers = QDockWidget("Layers", self)
        dock_layers.setWidget(self.layers_list)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_layers)

    def add_layer(self, name, item):
        lw_item = QListWidgetItem(name)
        lw_item.setData(Qt.ItemDataRole.UserRole, item)
        self.layers_list.addItem(lw_item)

    def move_layer_up(self):
        row = self.layers_list.currentRow()
        if row > 0:
            item = self.layers_list.takeItem(row)
            self.layers_list.insertItem(row - 1, item)
            graphics_item = item.data(Qt.ItemDataRole.UserRole)
            graphics_item.setZValue(graphics_item.zValue() + 1)

    def export_scene(self, filename: str):
        rect = self.view.sceneRect()
        image = QImage(int(rect.width()), int(rect.height()), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)

        painter = QPainter(image)
        self.view.scene().render(painter)
        painter.end()

        image.save(filename)

# =========================
# Export Settings
# =========================
@dataclass
class ExportSettings:
    formats: List[str]
    resize_percent: int
    png_optimize: bool
    jpg_quality: int
    webp_lossless: bool
    webp_quality: int
    drop_alpha: bool
    max_width: int = 0
    max_height: int = 0

# =========================
# Export Dialog
# =========================
class ExportDialog(QDialog):
    def __init__(self, parent, base_img: Optional[Image.Image], batch_count: int):
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.base_img = base_img
        self.batch_count = batch_count

        # Controls
        self.chk_png = QCheckBox("PNG")
        self.chk_jpg = QCheckBox("JPG")
        self.chk_webp = QCheckBox("WebP")
        self.chk_png.setChecked(True)

        self.spin_resize = QSpinBox()
        self.spin_resize.setRange(1, 100)
        self.spin_resize.setValue(100)

        self.spin_max_w = QSpinBox()
        self.spin_max_w.setRange(0, 10000)
        self.spin_max_w.setValue(0)

        self.spin_max_h = QSpinBox()
        self.spin_max_h.setRange(0, 10000)
        self.spin_max_h.setValue(0)

        self.chk_png_opt = QCheckBox("PNG optimize (lossless)")
        self.chk_png_opt.setChecked(True)

        self.slider_jpg_q = QSlider(Qt.Orientation.Horizontal)
        self.slider_jpg_q.setRange(1, 100)
        self.slider_jpg_q.setValue(90)

        self.chk_webp_lossless = QCheckBox("WebP Lossless (uncheck for lossy)")
        self.slider_webp_q = QSlider(Qt.Orientation.Horizontal)
        self.slider_webp_q.setRange(1, 100)
        self.slider_webp_q.setValue(90)

        self.chk_drop_alpha = QCheckBox("Drop transparency (force RGB)")
        self.chk_drop_alpha.setChecked(False)

        # Form
        form = QFormLayout()
        fmts_row = QHBoxLayout()
        fmts_row.addWidget(self.chk_png)
        fmts_row.addWidget(self.chk_jpg)
        fmts_row.addWidget(self.chk_webp)
        form.addRow("Export Formats:", QWidget())
        form.itemAt(form.rowCount()-1, QFormLayout.ItemRole.FieldRole).widget().setLayout(fmts_row)

        form.addRow("Resize (%):", self.spin_resize)
        form.addRow("Max Width (px):", self.spin_max_w)
        form.addRow("Max Height (px):", self.spin_max_h)
        form.addRow("JPG Quality:", self.slider_jpg_q)
        form.addRow("WebP Lossless:", self.chk_webp_lossless)
        form.addRow("WebP Quality:", self.slider_webp_q)
        form.addRow(self.chk_png_opt)
        form.addRow(self.chk_drop_alpha)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(btns)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

    def current_settings(self) -> ExportSettings:
        fmts = []
        if self.chk_png.isChecked(): fmts.append("PNG")
        if self.chk_jpg.isChecked(): fmts.append("JPEG")
        if self.chk_webp.isChecked(): fmts.append("WEBP")
        if not fmts:
            fmts = ["PNG"]
        return ExportSettings(
            formats=fmts,
            resize_percent=self.spin_resize.value(),
            png_optimize=self.chk_png_opt.isChecked(),
            jpg_quality=self.slider_jpg_q.value(),
            webp_lossless=self.chk_webp_lossless.isChecked(),
            webp_quality=self.slider_webp_q.value(),
            drop_alpha=self.chk_drop_alpha.isChecked(),
            max_width=self.spin_max_w.value(),
            max_height=self.spin_max_h.value()
        )

# =========================
# Main Window
# =========================
class DeltaPix(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DeltaPix")
        self.resize(1200, 800)
        self.settings = QSettings("DeltaPix", "DeltaPix")

        self.images: List[str] = []
        self.current_index: int = -1
        self.current_img: Optional[Image.Image] = None

        self.view = ImageView()
        self.setCentralWidget(self.view)

        # Zoom label in status bar
        self.zoom_label = QLabel("Zoom: 100%")
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.view.zoom_changed.connect(self._update_zoom_label)

        self.file_list = QListWidget()
        self.file_list.itemSelectionChanged.connect(self._on_list_selection)
        dock = QDockWidget("Imported Files", self)
        dock.setWidget(self.file_list)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        self.setAcceptDrops(True)

        # Build menus/toolbars first
        self._build_menu()
        self._build_toolbar()

        # Now safe to rebuild recent
        self._rebuild_recent_menu()


    # ----- Helpers
    def _get_last_dir(self, key: str, fallback: str = "") -> str:
        return self.settings.value(key, fallback)

    def _set_last_dir(self, key: str, path: str):
        if path:
            if os.path.isfile(path):
                self.settings.setValue(key, os.path.dirname(path))
            else:
                self.settings.setValue(key, path)

    def _update_zoom_label(self, factor: float):
        pct = int(factor * 100)
        self.zoom_label.setText(f"Zoom: {pct}%")

    # ----- Menus / Toolbars
    def _build_menu(self):
        menubar = self.menuBar()
        self.menu_file = menubar.addMenu("&File")

        act_import_files = QAction("Import Files…", self)
        act_import_files.triggered.connect(self.import_files)
        self.menu_file.addAction(act_import_files)

        act_import_folder = QAction("Import Folder…", self)
        act_import_folder.triggered.connect(self.import_folder)
        self.menu_file.addAction(act_import_folder)

        self.menu_recent = QMenu("Recent", self)
        self.menu_file.addMenu(self.menu_recent)
        self.menu_file.addSeparator()

        # Export
        act_export = QAction("Export…", self)
        act_export.triggered.connect(self.export_dialog)
        self.menu_file.addAction(act_export)

        self.menu_file.addSeparator()
        act_quit = QAction("Exit", self)
        act_quit.triggered.connect(self.close)
        self.menu_file.addAction(act_quit)

        # Edit menu
        self.menu_edit = menubar.addMenu("&Edit")
        act_square = QAction("Add Square", self)
        act_square.triggered.connect(self.view.add_square)
        self.menu_edit.addAction(act_square)

        # View
        self.menu_view = menubar.addMenu("&View")
        act_fit = QAction("Fit to Window", self)
        act_fit.triggered.connect(self.view.fit_in_view)
        self.menu_view.addAction(act_fit)

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(tb)

        btn_square = QAction("Add Square", self)
        btn_square.triggered.connect(self.view.add_square)
        tb.addAction(btn_square)

        imp = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton), "Import Files…", self)
        imp.triggered.connect(self.import_files)
        tb.addAction(imp)

        exp = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "Export…", self)
        exp.triggered.connect(self.export_dialog)
        tb.addAction(exp)

        tb.addSeparator()
        fit = QAction("Fit", self)
        fit.triggered.connect(self.view.fit_in_view)
        tb.addAction(fit)

    # ----- Recent
    def _get_recent(self) -> List[str]:
        return self.settings.value("recent_files", [], list)

    def _save_recent(self, paths: List[str]):
        self.settings.setValue("recent_files", paths[:10])

    def _add_recent(self, path: str):
        rec = self._get_recent()
        if path in rec:
            rec.remove(path)
        rec.insert(0, path)
        self._save_recent(rec)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        self.menu_recent.clear()
        rec = self._get_recent()
        if not rec:
            a = QAction("(empty)", self)
            a.setEnabled(False)
            self.menu_recent.addAction(a)
            return
        for p in rec:
            a = QAction(p, self)
            a.triggered.connect(lambda _, x=p: self._open_recent(x))
            self.menu_recent.addAction(a)

    def _open_recent(self, path: str):
        if os.path.isfile(path) and is_image_file(path):
            self._add_files([path])

    # ----- Import
    def import_files(self):
        try:
            start_dir = self._get_last_dir("last_import_dir", "")
            files, _ = QFileDialog.getOpenFileNames(
                self, "Import Images", start_dir, "Images (*.png *.jpg *.jpeg *.webp)"
            )
            if files:
                self._set_last_dir("last_import_dir", files[0])
                self._add_files(files)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    def import_folder(self):
        start_dir = self._get_last_dir("last_import_dir", "")
        folder = QFileDialog.getExistingDirectory(self, "Import Folder", start_dir)
        if folder:
            self._set_last_dir("last_import_dir", folder)
        if not folder:
            return
        files = [os.path.join(folder, f) for f in os.listdir(folder) if is_image_file(os.path.join(folder, f))]
        if files:
            self._add_files(files)

    def _add_files(self, paths: List[str]):
        added = 0
        for p in paths:
            if not os.path.isfile(p) or not is_image_file(p):
                continue
            if p not in self.images:
                self.images.append(p)
                item = QListWidgetItem(os.path.basename(p))
                item.setToolTip(p)
                self.file_list.addItem(item)
                self._add_recent(p)
                added += 1
        if added:
            self.file_list.setCurrentRow(self.file_list.count() - 1)

    def _on_list_selection(self):
        row = self.file_list.currentRow()
        if row < 0 or row >= len(self.images):
            return
        path = self.images[row]
        img = load_image(path)
        if img is None:
            QMessageBox.warning(self, "Open Failed", f"Could not open:\n{path}")
            return
        self.current_index = row
        self.current_img = img
        self._display_image(img)

    def _display_image(self, img: Image.Image):
        qpix = pil_to_qpixmap(img)
        self.view.set_image(qpix)
        if 0 <= self.current_index < len(self.images):
            self.setWindowTitle(f"DeltaPix — {self.images[self.current_index]}")

    # ----- DnD
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = []
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if os.path.isdir(p):
                for fname in os.listdir(p):
                    full = os.path.join(p, fname)
                    if is_image_file(full):
                        paths.append(full)
            elif is_image_file(p):
                paths.append(p)
        if paths:
            self._add_files(paths)

    # ----- Export
    def export_dialog(self, preset: Optional[str] = None):
        if not self.images:
            QMessageBox.information(self, "Export", "Import at least one image first.")
            return

        base_img = self.current_img
        dlg = ExportDialog(self, base_img, batch_count=len(self.images))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        cfg = dlg.current_settings()

        # Single vs batch / multi-format logic
        multi_formats = len(cfg.formats) > 1
        is_batch = len(self.images) > 1 or multi_formats

        if is_batch:
            start_dir = self._get_last_dir("last_export_dir", "")
            out_dir = QFileDialog.getExistingDirectory(self, "Select Output Folder", start_dir)
            if out_dir:
                self._set_last_dir("last_export_dir", out_dir)
            if not out_dir:
                return
            self._export_batch(out_dir, cfg)
        else:
            cur_path = self.images[self.current_index]
            base_name, _ = os.path.splitext(os.path.basename(cur_path))
            fmt = cfg.formats[0]
            ext = ".png" if fmt == "PNG" else (".jpg" if fmt == "JPEG" else ".webp")
            start_dir = self._get_last_dir("last_export_dir", "")
            out_path, _ = QFileDialog.getSaveFileName(
                self, "Save As",
                os.path.join(start_dir, base_name + ext),
                "Images (*.png *.jpg *.jpeg *.webp)"
            )
            if out_path:
                self._set_last_dir("last_export_dir", out_path)
            if not out_path:
                return
            img = load_image(cur_path)
            if img is None:
                QMessageBox.warning(self, "Export", f"Failed to open {cur_path}")
                return
            ok, msg = self._save_one(img, out_path, fmt, cfg)
            if not ok:
                QMessageBox.warning(self, "Export Failed", msg)
            else:
                QMessageBox.information(self, "Export", f"Saved:\n{out_path}")

    def _apply_resize(self, img: Image.Image, pct: int, max_w: int = 0, max_h: int = 0) -> Image.Image:
        if pct != 100:
            w, h = img.size
            w = max(1, int(w * pct / 100))
            h = max(1, int(h * pct / 100))
            img = img.resize((w, h), Image.LANCZOS)

        if max_w > 0 or max_h > 0:
            w, h = img.size
            scale = 1.0
            if max_w > 0 and w > max_w:
                scale = min(scale, max_w / w)
            if max_h > 0 and h > max_h:
                scale = min(scale, max_h / h)
            if scale < 1.0:
                w = int(w * scale)
                h = int(h * scale)
                img = img.resize((w, h), Image.LANCZOS)
        return img

    def _save_one(self, img: Image.Image, out_path: str, fmt: str, cfg: ExportSettings) -> Tuple[bool, str]:
        try:
            im = img
            if cfg.drop_alpha or fmt == "JPEG":
                im = im.convert("RGB")
            im = self._apply_resize(im, cfg.resize_percent, cfg.max_width, cfg.max_height)

            kwargs = {}
            if fmt == "PNG":
                kwargs["optimize"] = cfg.png_optimize
            elif fmt == "JPEG":
                kwargs["quality"] = cfg.jpg_quality
            elif fmt == "WEBP":
                if cfg.webp_lossless:
                    kwargs["lossless"] = True
                    kwargs["method"] = 6
                else:
                    kwargs["quality"] = cfg.webp_quality
                    kwargs["method"] = 6

            im.save(out_path, fmt, **kwargs)
            return True, "ok"
        except Exception as e:
            return False, str(e)

    def _export_batch(self, out_dir: str, cfg: ExportSettings):
        errors = []
        for path in self.images:
            img = load_image(path)
            if img is None:
                errors.append(f"Open failed: {path}")
                continue
            base, _ = os.path.splitext(os.path.basename(path))
            for fmt in cfg.formats:
                ext = ".png" if fmt == "PNG" else (".jpg" if fmt == "JPEG" else ".webp")
                out_path = os.path.join(out_dir, f"{base}{ext}")
                ok, msg = self._save_one(img, out_path, fmt, cfg)
                if not ok:
                    errors.append(f"{os.path.basename(path)} → {fmt}: {msg}")
        if errors:
            QMessageBox.warning(self, "Export Done (with errors)", "\n".join(errors[:20]))
        else:
            QMessageBox.information(self, "Export", "Batch export completed.")

# =========================
# Main
# =========================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("DeltaPix")
    app.setOrganizationName("DeltaPix")
    app.setOrganizationDomain("deltapix.local")

    def _excepthook(exc_type, exc, tb):
        QMessageBox.critical(None, "Fatal Error", f"{exc_type.__name__}: {exc}")
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = _excepthook

    w = DeltaPix()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
