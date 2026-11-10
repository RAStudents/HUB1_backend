import json
import math
from typing import Any

from acmenra_cv import TaskType

from core.infrastructure.cv.labels import parse_label_file
from core.infrastructure.cv.mapper import instances_to_dtos
from core.infrastructure.media.scratch import scratch_file


class DatasetStatisticsService:
    def __init__(self, sample_repo: Any, class_repo: Any, s3_client: Any):
        self.samples = sample_repo
        self.classes = class_repo
        self.s3 = s3_client

    def get_statistics(
        self,
        dataset_id: int,
        task: TaskType,
        grid_size: int = 20,
    ) -> dict:
        if (
            isinstance(grid_size, bool)
            or not isinstance(grid_size, int)
            or grid_size < 1
        ):
            raise ValueError("Размер сетки должен быть положительным целым числом")

        class_names = self.classes.get_names(dataset_id)
        self._populate_missing_geometries(dataset_id, class_names, task)

        class_heatmaps = {
            class_id: [[0 for _ in range(grid_size)] for _ in range(grid_size)]
            for class_id in range(len(class_names))
        }
        all_heatmap = [[0 for _ in range(grid_size)] for _ in range(grid_size)]
        class_counts = [0 for _ in class_names]
        split_counts = {"train": 0, "val": 0, "test": 0}
        image_count = 0
        annotation_count = 0

        for row in self.samples.iter_statistics_rows(dataset_id):
            image_count += 1
            split_name = "val" if row.split == "valid" else row.split
            split_counts[split_name] = split_counts.get(split_name, 0) + 1

            geometries = json.loads(row.geometry_json) if row.geometry_json else []
            if not isinstance(geometries, list):
                raise ValueError(f"Некорректная геометрия у кадра {row.id}")

            for geometry in geometries:
                if not isinstance(geometry, dict):
                    raise ValueError(f"Некорректная геометрия у кадра {row.id}")
                class_id = geometry.get("class_id")
                if (
                    isinstance(class_id, bool)
                    or not isinstance(class_id, int)
                    or class_id not in class_heatmaps
                ):
                    raise ValueError(
                        f"У кадра {row.id} указана неизвестная категория: {class_id}"
                    )

                x, y = self._annotation_center(geometry, row.id)
                if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
                    raise ValueError(
                        f"Центр объекта у кадра {row.id} выходит за границы изображения"
                    )

                column = min(int(x * grid_size), grid_size - 1)
                line = min(int(y * grid_size), grid_size - 1)
                class_heatmaps[class_id][line][column] += 1
                all_heatmap[line][column] += 1
                class_counts[class_id] += 1
                annotation_count += 1

        return {
            "dataset_id": dataset_id,
            "task": task.value,
            "grid_size": grid_size,
            "image_count": image_count,
            "images_by_split": {
                "all": image_count,
                "train": split_counts.get("train", 0),
                "val": split_counts.get("val", 0),
                "test": split_counts.get("test", 0),
            },
            "annotation_count": annotation_count,
            "annotations_per_class": [
                {
                    "class_id": class_id,
                    "class_name": name,
                    "count": class_counts[class_id],
                }
                for class_id, name in enumerate(class_names)
            ],
            "annotation_locations": {
                "all": all_heatmap,
                "classes": [
                    {
                        "class_id": class_id,
                        "class_name": name,
                        "count": class_counts[class_id],
                        "heatmap": class_heatmaps[class_id],
                    }
                    for class_id, name in enumerate(class_names)
                ],
            },
        }

    def _populate_missing_geometries(
        self,
        dataset_id: int,
        class_names: list[str],
        task: TaskType,
    ) -> None:
        missing_rows = self.samples.list_missing_geometries(dataset_id)
        for index, sample in enumerate(missing_rows, start=1):
            raw_label = self.s3.get_bytes(sample.label_key) or b""
            with scratch_file(suffix=".txt", data=raw_label) as label_path:
                instances = parse_label_file(
                    path=label_path,
                    class_names=class_names,
                    task=task,
                    is_strict=False,
                )
            geometries = [
                item.model_dump(mode="json")
                for item in instances_to_dtos(instances, task)
            ]
            self.samples.set_geometries(sample.id, geometries, commit=False)
            if index % 100 == 0:
                self.samples.commit()
        if missing_rows:
            self.samples.commit()

    @staticmethod
    def _annotation_center(geometry: dict, sample_id: int) -> tuple[float, float]:
        box = geometry.get("box")
        obb = geometry.get("obb")
        polygon = geometry.get("polygon")

        if isinstance(box, dict):
            center = (box.get("x"), box.get("y"))
        elif isinstance(obb, dict):
            center = (obb.get("x"), obb.get("y"))
        elif isinstance(polygon, dict):
            points = polygon.get("points")
            if not isinstance(points, list) or not points:
                raise ValueError(f"У объекта кадра {sample_id} нет точек полигона")
            point_xs = [point.get("x") for point in points if isinstance(point, dict)]
            point_ys = [point.get("y") for point in points if isinstance(point, dict)]
            if len(point_xs) != len(points) or len(point_ys) != len(points):
                raise ValueError(f"Некорректные точки полигона у кадра {sample_id}")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in point_xs + point_ys
            ):
                raise ValueError(f"Некорректные точки полигона у кадра {sample_id}")
            center = (
                sum(point_xs) / len(point_xs),
                sum(point_ys) / len(point_ys),
            )
        else:
            raise ValueError(f"У объекта кадра {sample_id} нет поддерживаемой геометрии")

        x, y = center
        if (
            isinstance(x, bool)
            or isinstance(y, bool)
            or not isinstance(x, (int, float))
            or not isinstance(y, (int, float))
            or not math.isfinite(x)
            or not math.isfinite(y)
        ):
            raise ValueError(f"Некорректный центр объекта у кадра {sample_id}")
        return float(x), float(y)
