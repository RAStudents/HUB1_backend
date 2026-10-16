from pathlib import Path
from typing import List
import cv2
import numpy as np

from acmenra_cv import Drawer, Fill, Font, Instance, LabelPosition, Stroke, Style, TaskType
from acmenra_ds import ImageParser

# Базовая контрастная палитра (RGB/BGR кортежи для классов)
DEFAULT_PALETTE: List[tuple] = [
    (255, 56, 56),
    (255, 157, 151),
    (255, 112, 31),
    (255, 178, 29),
    (207, 210, 49),
    (72, 249, 10),
    (146, 204, 23),
    (61, 219, 134),
    (26, 147, 52),
    (0, 212, 187),
    (44, 153, 168),
    (0, 194, 255),
    (52, 69, 147),
    (100, 115, 255),
    (0, 24, 236),
    (132, 56, 255),
    (82, 0, 133),
    (203, 56, 255),
    (255, 149, 200),
    (255, 55, 199),
]


def build_default_style() -> Style:
    """Собирает стиль отрисовки для превьюшек галереи."""
    return Style(
        palette=DEFAULT_PALETTE,
        font=Font(color=(255, 255, 255), font=1, font_scale=2, thickness=2),
        stroke=Stroke(thickness=3, segment=0.2, alpha=1.0),
        fill=Fill(alpha=0.35),
        smooth=2,
        rounding=0.04,
        alpha=0.65,
        show=True,
        label=LabelPosition.TOP,
    )


def render_thumbnail_array(
    frame: np.ndarray,
    instances: List[Instance],
    task: TaskType,
    style: Style | None = None,
) -> np.ndarray:
    """
    Рисует инстансы (бокс, OBB или полигон/маску) на матрице изображения через Drawer.
    """
    if not instances:
        return frame.copy()

    active_style = style or build_default_style()
    drawer = Drawer(style=active_style)

    # Включаем отрисовку только нужного примитива, чтобы не рисовать плейсхолдер-бокс!
    return drawer.draw_instances(
        frame=frame.copy(),
        instances=instances,
        is_box=(task == TaskType.DETECT),
        is_obb=(task == TaskType.OBB),
        is_polygon=(task == TaskType.SEGMENT),
        style=active_style,
    )


def render_thumbnail_bytes(
    image_path: Path,
    instances: List[Instance],
    task: TaskType,
    jpeg_quality: int = 85,
) -> bytes:
    """
    Читает картинку через ImageParser, рисует маски через Drawer
    и возвращает готовые JPEG-байты для загрузки в S3 (MinIO).
    """
    parser = ImageParser()
    frame = parser.parse(path=image_path, is_strict=True)
    if frame is None:
        raise ValueError(f"Не удалось прочитать изображение: {image_path}")

    rendered = render_thumbnail_array(frame=frame, instances=instances, task=task)

    success, encoded = cv2.imencode(
        ".jpg", rendered, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
    )
    if not success:
        raise RuntimeError(f"Ошибка кодирования превью в JPEG для {image_path}")

    return encoded.tobytes()