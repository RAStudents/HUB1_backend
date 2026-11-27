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


class DatasetSplitStatisticsDTO(BaseModel):
    image_count: int
    labeled_count: int
    status_counts: dict[str, int]
    annotation_count: int
    annotations_per_class: list[DatasetClassCountDTO]
    annotation_locations: DatasetAnnotationLocationsDTO


class DatasetStatisticsDTO(DatasetSplitStatisticsDTO):
    dataset_id: str
    task: str
    grid_size: int
    images_by_split: dict[str, int]
    splits: dict[str, DatasetSplitStatisticsDTO | None]
