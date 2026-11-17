# core/application/dataset_statistics_service.py

import json
from pathlib import Path
from typing import Any

from acmenra_cv import TaskType
from acmenra_ds import Config, Dataset, DatasetLayout, LabelWriter, Sample, make_category_enum
from acmenra_ds.data.enums import DataSplit
from acmenra_ds.statistics import Statistics

from apps.api.app.schemas.annotation import AnnotationItemDTO
from core.infrastructure.cv.labels import parse_label_file
from core.infrastructure.cv.mapper import dtos_to_instances, instances_to_dtos
from core.infrastructure.media.scratch import scratch_dir, scratch_file


class DatasetStatisticsService:
    def __init__(self,
                 sample_repo: Any,
                 class_repo: Any,
                 s3_client: Any):
        self.samples = sample_repo
        self.classes = class_repo
        self.s3 = s3_client

    def get_statistics(self,
                       dataset_id: int,
                       task: TaskType,
                       grid_size: int = 20) -> dict:
        if (isinstance(grid_size, bool) or not isinstance(grid_size, int) or grid_size < 1):
            raise ValueError("Размер сетки должен быть положительным целым числом")

        class_names = self.classes.get_names(dataset_id)
        self._populate_missing_geometries(dataset_id, class_names, task)

        names_for_library = [
            f"dataset_class_{class_id}" for class_id in range(len(class_names))
        ] or ["dataset_class_empty"]
        category = make_category_enum(names_for_library)
        with scratch_dir(prefix=f"hub_statistics_{dataset_id}_") as root:
            samples_by_split = self._build_library_dataset(
                root=root,
                dataset_id=dataset_id,
                task=task,
                names=names_for_library,
                category=category,
                class_count=len(class_names),
            )
            config = Config(
                root=root,
                train="train",
                val="val",
                test="test",
                names=names_for_library,
                task=task,
                layout=DatasetLayout.DIRECT,
                val_leaf="val",
            )
            dataset = Dataset(
                config=config,
                category=category,
                is_cache=False,
                is_strict=False,
            )
            dataset.train.samples.extend(samples_by_split[DataSplit.TRAIN])
            dataset.val.samples.extend(samples_by_split[DataSplit.VAL])
            dataset.test.samples.extend(samples_by_split[DataSplit.TEST])

            statistics = Statistics(dataset=dataset, grid=grid_size)
            image_counts = statistics.get_split_distribution()
            label_counts = statistics.labels_per_class
            heatmaps = statistics.labels_heat_map

            class_statistics = [
                {
                    "class_id": class_id,
                    "class_name": name,
                    "count": label_counts[names_for_library[class_id]],
                }
                for class_id, name in enumerate(class_names)
            ]
            class_heatmaps = [
                {
                    **class_statistics[class_id],
                    "heatmap": heatmaps[names_for_library[class_id]].tolist(),
                }
                for class_id in range(len(class_names))
            ]
            split_statistics = {
                "train": self._serialize_split_statistics(
                    statistics.train,
                    class_names,
                    names_for_library,
                ),
                "val": self._serialize_split_statistics(
                    statistics.val,
                    class_names,
                    names_for_library,
                ),
                "test": self._serialize_split_statistics(
                    statistics.test,
                    class_names,
                    names_for_library,
                ),
            }

            return {
                "dataset_id": dataset_id,
                "task": task.value,
                "grid_size": grid_size,
                "image_count": image_counts["all"],
                "images_by_split": image_counts,
                "annotation_count": label_counts["all"],
                "annotations_per_class": class_statistics,
                "annotation_locations": {
                    "all": heatmaps["all"].tolist(),
                    "classes": class_heatmaps,
                },
                "splits": split_statistics,
            }

    @staticmethod
    def _serialize_split_statistics(split_statistics: Any,
                                    class_names: list[str],
                                    names_for_library: list[str]) -> dict | None:
        if split_statistics is None:
            return None

        label_counts = split_statistics.labels_per_class
        heatmaps = split_statistics.labels_heat_map
        classes = [
            {
                "class_id": class_id,
                "class_name": name,
                "count": label_counts[names_for_library[class_id]],
                "heatmap": heatmaps[names_for_library[class_id]].tolist(),
            }
            for class_id, name in enumerate(class_names)
        ]

        return {
            "image_count": split_statistics.count,
            "annotation_count": label_counts["all"],
            "annotations_per_class": [
                {key: value for key, value in item.items() if key != "heatmap"}
                for item in classes
            ],
            "annotation_locations": {
                "all": heatmaps["all"].tolist(),
                "classes": classes,
            },
        }

    def _build_library_dataset(self,
                               root: Path,
                               dataset_id: int,
                               task: TaskType,
                               names: list[str],
                               category: type,
                               class_count: int) -> dict[DataSplit, list[Sample]]:
        directories: dict[str, tuple[Path, Path]] = {}
        for split_name in ("train", "val", "test"):
            images_dir = root / split_name / "images"
            labels_dir = root / split_name / "labels"
            images_dir.mkdir(parents=True)
            labels_dir.mkdir(parents=True)
            directories[split_name] = images_dir, labels_dir

        writer = LabelWriter(nc=len(names), task_type=task, category=category)
        samples_by_split = {
            DataSplit.TRAIN: [],
            DataSplit.VAL: [],
            DataSplit.TEST: [],
        }

        for row in self.samples.iter_statistics_rows(dataset_id):
            split_name = "val" if row.split == "valid" else row.split
            split = {
                "train": DataSplit.TRAIN,
                "val": DataSplit.VAL,
                "test": DataSplit.TEST,
            }.get(split_name)
            if split is None:
                raise ValueError(f"Неизвестный сплит датасета: {row.split}")

            geometries = json.loads(row.geometry_json) if row.geometry_json else []
            if not isinstance(geometries, list):
                raise ValueError(f"Некорректная геометрия у кадра {row.id}")

            annotation_dtos = []
            for geometry in geometries:
                if not isinstance(geometry, dict):
                    raise ValueError(f"Некорректная геометрия у кадра {row.id}")
                annotation = AnnotationItemDTO.model_validate(geometry)
                if annotation.class_id < 0 or annotation.class_id >= class_count:
                    raise ValueError(
                        f"У кадра {row.id} указана неизвестная категория: "
                        f"{annotation.class_id}"
                    )
                coordinates: list[tuple[float, float]] = []
                if task == TaskType.DETECT and annotation.box is not None:
                    coordinates = [(annotation.box.x, annotation.box.y)]
                elif task == TaskType.OBB and annotation.obb is not None:
                    coordinates = [(annotation.obb.x, annotation.obb.y)]
                elif task == TaskType.SEGMENT and annotation.polygon is not None:
                    coordinates = [
                        (point.x, point.y) for point in annotation.polygon.points
                    ]
                if any(
                    not 0 <= coordinate <= 1
                    for point in coordinates
                    for coordinate in point
                ):
                    raise ValueError(
                        f"Координаты разметки кадра {row.id} выходят за границы изображения"
                    )
                annotation_dtos.append(annotation)

            instances = dtos_to_instances(
                annotation_dtos,
                task=task,
                class_names=names,
            )
            images_dir, labels_dir = directories[split_name]
            label_path = labels_dir / f"{row.id}.txt"
            if instances:
                writer.write(path=label_path, instances=instances, is_strict=True)
                label_path = label_path.resolve()
            else:
                label_path = None

            samples_by_split[split].append(
                Sample(
                    stem=str(row.id),
                    image_path=images_dir / f"{row.id}.jpg",
                    label_path=label_path,
                )
            )

        return samples_by_split

    def _populate_missing_geometries(self,
                                     dataset_id: int,
                                     class_names: list[str],
                                     task: TaskType) -> None:
        missing_rows = self.samples.list_missing_geometries(dataset_id)
        for index, sample in enumerate(missing_rows, start=1):
            raw_label = self.s3.get_bytes(sample.label_key) or b""
            if raw_label and not class_names:
                raise ValueError("Нельзя восстановить разметку без классов датасета")
            if raw_label:
                with scratch_file(suffix=".txt", data=raw_label) as label_path:
                    instances = parse_label_file(
                        path=label_path,
                        class_names=class_names,
                        task=task,
                        is_strict=True,
                    )
            else:
                instances = []
            geometries = [
                item.model_dump(mode="json")
                for item in instances_to_dtos(instances, task)
            ]
            self.samples.set_geometries(sample.id, geometries, commit=False)
            if index % 100 == 0:
                self.samples.commit()
        if missing_rows:
            self.samples.commit()
