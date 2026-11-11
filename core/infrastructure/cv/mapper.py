# core/infrastructure/cv/mapper.py

import math
import logging
from typing import List, Sequence

from acmenra_cv import Box, Instance, Obb, Point, Polygon, TaskType
from acmenra_ds import make_category_enum

from apps.api.app.schemas.annotation import AnnotationItemDTO, BoxDTO, ObbDTO, PointDTO, PolygonDTO


logger = logging.getLogger(__name__)


def instance_to_dto(instance: Instance,
                    task: TaskType) -> AnnotationItemDTO:
    """
    Конвертирует Instance из acmenra-cv в DTO для API.

    - Плейсхолдер-бокс для OBB и SEGMENT наружу не отдаётся.
    - Угол OBB переводится из радиан в градусы.
    """
    box_dto = None
    obb_dto = None
    polygon_dto = None

    if task == TaskType.DETECT:
        cx, cy, w, h = instance.box.to_xywhn()
        box_dto = BoxDTO(x=float(cx), y=float(cy), width=float(w), height=float(h))

    elif task == TaskType.OBB and instance.obb is not None:
        cx, cy, w, h, yaw_rad = instance.obb.to_xywhrn()
        obb_dto = ObbDTO(
            x=float(cx),
            y=float(cy),
            width=float(w),
            height=float(h),
            angle_deg=float(math.degrees(yaw_rad)),
        )

    elif task == TaskType.SEGMENT and instance.polygon is not None:
        pts = [PointDTO(x=float(p.X), y=float(p.Y)) for p in instance.polygon.points]
        polygon_dto = PolygonDTO(points=pts)

    return AnnotationItemDTO(
        id=instance.id,
        class_id=instance.class_id,
        box=box_dto,
        obb=obb_dto,
        polygon=polygon_dto,
    )


def _unit(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"Координата {name} должна быть от 0 до 1")
    return number


def _positive_unit(value: float, name: str) -> float:
    number = _unit(value, name)
    if number <= 0.0:
        raise ValueError(f"Размер {name} должен быть больше 0")
    return number


def dto_to_instance(dto: AnnotationItemDTO,
                    task: TaskType,
                    class_names: Sequence[str]) -> Instance:
    """Собирает Instance из DTO. Класс и координаты проверяются, ничего не подменяется."""
    if not class_names or not isinstance(dto.class_id, int) or isinstance(dto.class_id, bool):
        raise ValueError("Некорректный класс")
    if dto.class_id < 0 or dto.class_id >= len(class_names):
        raise ValueError("Неизвестный класс")

    category_enum = make_category_enum(class_names)
    members_by_val = {item.value: item for item in category_enum}
    label_enum = members_by_val.get(dto.class_id)
    if label_enum is None:
        raise ValueError("Неизвестный класс")
    placeholder_box = Box()

    if task == TaskType.DETECT and dto.box is not None:
        real_box = Box.from_xywhn([
            _unit(dto.box.x, "x"),
            _unit(dto.box.y, "y"),
            _positive_unit(dto.box.width, "width"),
            _positive_unit(dto.box.height, "height"),
        ])
        return Instance(
            id=dto.id,
            class_id=dto.class_id,
            label=label_enum,
            conf=1.0,
            box=real_box,
            obb=None,
            polygon=None,
        )

    if task == TaskType.OBB and dto.obb is not None:
        if not math.isfinite(float(dto.obb.angle_deg)):
            raise ValueError("Некорректный угол")
        yaw_rad = math.radians(float(dto.obb.angle_deg))
        real_obb = Obb.from_xywhrn([
            _unit(dto.obb.x, "x"),
            _unit(dto.obb.y, "y"),
            _positive_unit(dto.obb.width, "width"),
            _positive_unit(dto.obb.height, "height"),
            yaw_rad,
        ])
        return Instance(
            id=dto.id,
            class_id=dto.class_id,
            label=label_enum,
            conf=1.0,
            box=placeholder_box,
            obb=real_obb,
            polygon=None,
        )

    if task == TaskType.SEGMENT and dto.polygon is not None:
        if len(dto.polygon.points) < 3 or len(dto.polygon.points) > 5000:
            raise ValueError("У полигона должно быть от 3 до 5000 точек")
        points = [
            Point.safe(x=_unit(pt.x, "x"), y=_unit(pt.y, "y"))
            for pt in dto.polygon.points
        ]
        real_poly = Polygon(points=points)
        return Instance(
            id=dto.id,
            class_id=dto.class_id,
            label=label_enum,
            conf=1.0,
            box=placeholder_box,
            obb=None,
            polygon=real_poly,
        )

    raise ValueError(f"Некорректные данные геометрии для задачи {task.value}")


def instances_to_dtos(instances: List[Instance],
                      task: TaskType) -> List[AnnotationItemDTO]:
    """Конвертирует список Instance в список DTO."""
    return [instance_to_dto(inst, task) for inst in instances]


def dtos_to_instances(dtos: List[AnnotationItemDTO],
                      task: TaskType,
                      class_names: Sequence[str]) -> List[Instance]:
    """Конвертирует список DTO в список Instance."""
    return [dto_to_instance(d, task, class_names) for d in dtos]
