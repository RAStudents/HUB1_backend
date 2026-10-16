import math
from typing import List, Sequence

from acmenra_cv import Box, Instance, Obb, Point, Polygon, TaskType
from apps.api.app.schemas.annotation import (
    AnnotationItemDTO,
    BoxDTO,
    ObbDTO,
    PointDTO,
    PolygonDTO,
)
from core.infrastructure.cv.labels import build_category_enum


def instance_to_dto(instance: Instance, task: TaskType) -> AnnotationItemDTO:
    """
    Переводит Instance из acmenra-cv в DTO для API.
    Плейсхолдер-бокс для OBB и SEGMENT наружу НЕ отдаётся!
    Угол OBB переводится из радиан в градусы.
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


def dto_to_instance(
    dto: AnnotationItemDTO,
    task: TaskType,
    class_names: Sequence[str],
) -> Instance:
    """
    Собирает Instance из DTO фронтенда для сохранения в .txt и отрисовки Drawer-ом.
    Для OBB и SEGMENT создаёт технический пустой Box(), как того требует конструктор Instance.
    Угол OBB переводится из градусов в радианы.
    """
    category_enum = build_category_enum(class_names)
    members_by_val = {item.value: item for item in category_enum}
    label_enum = members_by_val.get(dto.class_id, list(category_enum)[0])

    # Плейсхолдер-бокс по умолчанию (обязателен для Instance.__init__)
    placeholder_box = Box()

    if task == TaskType.DETECT and dto.box is not None:
        real_box = Box.from_xywhn([dto.box.x, dto.box.y, dto.box.width, dto.box.height])
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
        yaw_rad = math.radians(dto.obb.angle_deg)
        real_obb = Obb.from_xywhrn(
            [dto.obb.x, dto.obb.y, dto.obb.width, dto.obb.height, yaw_rad]
        )
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
        points = [Point.safe(x=pt.x, y=pt.y) for pt in dto.polygon.points]
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


def instances_to_dtos(instances: List[Instance], task: TaskType) -> List[AnnotationItemDTO]:
    return [instance_to_dto(inst, task) for inst in instances]


def dtos_to_instances(
    dtos: List[AnnotationItemDTO],
    task: TaskType,
    class_names: Sequence[str],
) -> List[Instance]:
    return [dto_to_instance(d, task, class_names) for d in dtos]