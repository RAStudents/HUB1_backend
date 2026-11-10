import json
import unittest
from types import SimpleNamespace

from acmenra_cv import TaskType

from apps.api.app.schemas.dataset_statistics import DatasetStatisticsDTO
from core.application.dataset_statistics_service import DatasetStatisticsService


class _SampleRepository:
    def __init__(self, rows):
        self.rows = rows

    def list_missing_geometries(self, dataset_id):
        return []

    def iter_statistics_rows(self, dataset_id):
        return iter(self.rows)


class _ClassRepository:
    def get_names(self, dataset_id):
        return ["cat", "dog"]


class _S3Client:
    def get_bytes(self, key):
        return b"0 0.5 0.5 0.2 0.2\n"


class _LegacySampleRepository(_SampleRepository):
    def __init__(self):
        self.missing = [SimpleNamespace(id=6, label_key="labels/legacy.txt")]
        self.rows = []

    def list_missing_geometries(self, dataset_id):
        return self.missing

    def set_geometries(self, sample_id, geometries, commit=False):
        self.rows = [
            SimpleNamespace(
                id=sample_id,
                split="train",
                geometry_json=json.dumps(geometries),
            )
        ]

    def commit(self):
        pass


class DatasetStatisticsServiceTests(unittest.TestCase):
    def setUp(self):
        rows = [
            SimpleNamespace(
                id=1,
                split="train",
                geometry_json=(
                    '[{"class_id":0,"box":{"x":0.1,"y":0.1}},'
                    '{"class_id":1,"obb":{"x":0.5,"y":0.5}}]'
                ),
            ),
            SimpleNamespace(
                id=2,
                split="valid",
                geometry_json=(
                    '[{"class_id":0,"polygon":{"points":'
                    '[{"x":0.2,"y":0.2},{"x":0.4,"y":0.4}]}}]'
                ),
            ),
            SimpleNamespace(
                id=3,
                split="test",
                geometry_json='[{"class_id":1,"box":{"x":1.0,"y":1.0}}]',
            ),
        ]
        self.service = DatasetStatisticsService(
            sample_repo=_SampleRepository(rows),
            class_repo=_ClassRepository(),
            s3_client=None,
        )

    def test_builds_overall_and_per_class_heatmaps(self):
        result = self.service.get_statistics(
            dataset_id=42,
            task=TaskType.DETECT,
            grid_size=2,
        )

        self.assertEqual(result["images_by_split"], {
            "all": 3,
            "train": 1,
            "val": 1,
            "test": 1,
        })
        self.assertEqual(result["annotation_count"], 4)
        self.assertEqual(
            [item["count"] for item in result["annotations_per_class"]],
            [2, 2],
        )
        self.assertEqual(result["annotation_locations"]["all"], [
            [2, 0],
            [0, 2],
        ])
        self.assertEqual(
            result["annotation_locations"]["classes"][0]["heatmap"],
            [[2, 0], [0, 0]],
        )
        self.assertEqual(
            result["annotation_locations"]["classes"][1]["heatmap"],
            [[0, 0], [0, 2]],
        )
        DatasetStatisticsDTO.model_validate(result)

    def test_rejects_centers_outside_normalized_image(self):
        self.service.samples.rows = [
            SimpleNamespace(
                id=4,
                split="train",
                geometry_json='[{"class_id":0,"box":{"x":1.1,"y":0.5}}]',
            )
        ]

        with self.assertRaisesRegex(ValueError, "выходит за границы"):
            self.service.get_statistics(
                dataset_id=42,
                task=TaskType.DETECT,
                grid_size=20,
            )

    def test_rejects_unknown_class_ids(self):
        self.service.samples.rows = [
            SimpleNamespace(
                id=5,
                split="train",
                geometry_json='[{"class_id":8,"box":{"x":0.5,"y":0.5}}]',
            )
        ]

        with self.assertRaisesRegex(ValueError, "неизвестная категория"):
            self.service.get_statistics(
                dataset_id=42,
                task=TaskType.DETECT,
                grid_size=20,
            )

    def test_builds_and_persists_missing_legacy_geometries(self):
        sample_repo = _LegacySampleRepository()
        service = DatasetStatisticsService(
            sample_repo=sample_repo,
            class_repo=_ClassRepository(),
            s3_client=_S3Client(),
        )

        result = service.get_statistics(
            dataset_id=42,
            task=TaskType.DETECT,
            grid_size=4,
        )

        self.assertEqual(result["annotation_count"], 1)
        self.assertEqual(
            result["annotation_locations"]["classes"][0]["heatmap"][2][2],
            1,
        )


if __name__ == "__main__":
    unittest.main()
