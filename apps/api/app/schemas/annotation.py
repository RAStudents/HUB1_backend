from typing import List, Optional
from pydantic import BaseModel, Field


class BoxDTO(BaseModel):
    # Нормализованные координаты (0.0 .. 1.0)
    x: float = Field(..., description="Центр X")
    y: float = Field(..., description="Центр Y")
    width: float
    height: float


class ObbDTO(BaseModel):
    # В API угол передаётся в ГРАДУСАХ, в txt хранится в радианах
    x: float
    y: float
    width: float
    height: float
    angle_deg: float = Field(0.0, description="Угол поворота (yaw) в градусах")


class PointDTO(BaseModel):
    x: float
    y: float


class PolygonDTO(BaseModel):
    points: List[PointDTO]


class AnnotationItemDTO(BaseModel):
    id: Optional[int] = None
    class_id: int
    # В зависимости от task датасета заполняется ровно одно поле (плейсхолдер-бокс сюда не попадает!)
    box: Optional[BoxDTO] = None
    obb: Optional[ObbDTO] = None
    polygon: Optional[PolygonDTO] = None


class FrameAnnotationsDTO(BaseModel):
    sample_id: int
    items: List[AnnotationItemDTO]