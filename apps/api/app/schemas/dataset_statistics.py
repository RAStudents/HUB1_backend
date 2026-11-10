from pydantic import BaseModel


class DatasetClassCountDTO(BaseModel):
    class_id: int
    class_name: str
    count: int


class DatasetClassHeatmapDTO(DatasetClassCountDTO):
    heatmap: list[list[int]]


class DatasetAnnotationLocationsDTO(BaseModel):
    all: list[list[int]]
    classes: list[DatasetClassHeatmapDTO]


class DatasetStatisticsDTO(BaseModel):
    dataset_id: int
    task: str
    grid_size: int
    image_count: int
    images_by_split: dict[str, int]
    annotation_count: int
    annotations_per_class: list[DatasetClassCountDTO]
    annotation_locations: DatasetAnnotationLocationsDTO
