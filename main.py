
import os
import cv2
import time
import logging
import threading
import numpy as np

from tqdm import tqdm
from enum import Enum, EnumType
from pathlib import Path
from ultralytics import YOLO
from typing import Any, List, Dict, Optional

from acmenra_cv import Tracker, TrackedObject
from acmenra_cv import Font, Fill, Stroke, Style, Drawer, LabelPosition
from acmenra_cv import Point, Obb, Box, Polygon, Instance, DeviceType, TaskType
from acmenra_yolo import YOLOBackend

from acmenra_ds import Config
from acmenra_ds.data import Dataset
from acmenra_ds.augmentation import (
    Compose,
    HorizontalFlip,
    VerticalFlip,
    Brightness,
    ChannelBrightness,
    Blur,
    Noise,
    Pixelate,
    Gray,
)

# before first run exceute this
# pip install acmenra-cv==0.2.0.2
# pip install acmenra-yolo==0.1.0.0
# pip install acmenra-ds==0.3.2.0


YAML_PATH = "/Users/stepanborodin/Downloads/indastrial/data.yaml"
WAIT_MS = 0          # 0 = смотришь каждый кадр, 30 = автоплей
PREVIEW_H = 720
SAVE_DIR = Path(os.getcwd()) / "aug_preview"

os.makedirs(os.path.join(os.getcwd(), "logs"), exist_ok=True)
formatter = "[%(asctime)s] #%(levelname)-8s %(filename)s:%(lineno)d - %(name)s - %(message)s"
logging.basicConfig(level=logging.WARNING, format=formatter)
logger = logging.getLogger(__name__)
file_handler = logging.FileHandler(os.path.join(os.getcwd(), "logs", "logs.log"))
file_handler.setFormatter(logging.Formatter(formatter))
logger.root.addHandler(file_handler)


style = Style(palette=np.random.randint(0, 255, (80, 3)).tolist(), # Задаем стиль
              font=Font(color=(255, 100, 150),
                        font=cv2.FONT_HERSHEY_PLAIN,
                        font_scale=1,
                        thickness=2), # Настройки текста
              stroke=Stroke(thickness=1,
                            segment=0.08,
                            alpha=0.80), # Настройки "обводки"
              fill=Fill(alpha=0.15), # Настройки "заливки"
              smooth=0,
              alpha=0.99,
              show=True, # Врубает/Врубает отображение заливки
              rounding=0.05,
              label=LabelPosition.OFF,
)

class Mock(Enum):  # Тестовый Енам
    inclusion = 0
    patches = 1
    pitted = 2
    scratch = 3
    crack = 4
    corrosion = 5


pipeline = Compose([
    HorizontalFlip(p=0.5),
    VerticalFlip(p=0.5),
    Brightness(min_factor=0.55, max_factor=1.45, p=0.5),
    ChannelBrightness(p=0.5),
    Blur(max_ksize=10, p=0.5),
    Noise(max_ratio=0.02, p=0.5),
    Pixelate(max_pixel_size=4, p=0.5),
    Gray(p=0.5),
]) # Послеловательность преобразований для каждорй картинки


def smoke_compose() -> None:
    dummy = np.random.randint(0, 256, (64, 80, 3), dtype=np.uint8)
    out, labels = pipeline(dummy, [])
    if out.dtype != np.uint8:
        raise RuntimeError(f"Compose returned {out.dtype}, expected uint8")
    if labels != []:
        raise RuntimeError("Empty labels must stay empty")
    print(f"Compose smoke OK  |  {pipeline}")


def letterbox_h(image: np.ndarray, height: int = PREVIEW_H) -> np.ndarray:
    h, w = image.shape[:2]
    if h == height:
        return image
    scale = height / float(h)
    return cv2.resize(image, (max(1, int(round(w * scale))), height), interpolation=cv2.INTER_LINEAR)


def caption(image: np.ndarray, text: str) -> np.ndarray:
    out = image.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 36), (0, 0, 0), -1)
    cv2.putText(out, text, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return out


def draw(image: np.ndarray, instances, task: TaskType) -> np.ndarray:
    frame = image.copy()
    if not instances:
        return frame
    return Drawer(style=style).draw_instances(frame=frame,
                                              instances=instances,
                                              is_box=task == TaskType.DETECT,
                                              is_obb=task == TaskType.OBB,
                                              is_polygon=task == TaskType.SEGMENT)


def pair_canvas(original, augmented, left, right) -> np.ndarray:
    a = caption(letterbox_h(original), left)
    b = caption(letterbox_h(augmented), right)
    return np.hstack([a, b])


def preview_split(split, task: TaskType, title: str):
    if split is None or len(split) == 0:
        print(f"skip {title}: empty")
        return True
    idx = 0
    bar = tqdm(total=len(split), desc=f"aug/{title}")
    while 0 <= idx < len(split):
        sample = split[idx]
        image = split.image_parser.parse(path=sample.image_path, is_strict=False)
        if image is None:
            idx += 1
            bar.update(1)
            continue
        labels = split.get_instances(idx)
        aug_image, aug_labels = pipeline(image, labels)
        canvas = pair_canvas(
            draw(image, labels, task),
            draw(aug_image, aug_labels, task),
            f"{title}  {sample.stem}  n={len(labels)}",
            f"AUG  n={len(aug_labels)}  steps={len(pipeline)}",
        )
        cv2.imshow("Acmenra Augmentation  |  original LEFT  /  aug RIGHT", canvas)
        key = cv2.waitKey(WAIT_MS) & 0xFF
        if key == ord("q"):
            bar.close()
            return False
        if key == ord("r"):
            continue
        if key == ord("s"):
            SAVE_DIR.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(SAVE_DIR / f"{title}_{sample.stem}.jpg"), canvas)
            continue
        if key == ord("1"):
            bar.close(); return "train"
        if key == ord("2"):
            bar.close(); return "test"
        if key == ord("3"):
            bar.close(); return "val"
        idx += 1
        bar.update(1)
    bar.close()
    return True


def main() -> None:
    smoke_compose()
    config = Config.from_yaml(yaml_path=YAML_PATH)
    # print(config)
    dataset = Dataset(config=config, category=Mock)
    print(dataset)

    order = ["train", "test", "val"]
    i = 0
    while i < len(order):
        result = preview_split(dataset.split(order[i]), dataset.task, order[i])
        if result is False:
            break
        if result in order:
            i = order.index(result)
            continue
        i += 1
    cv2.destroyAllWindows()


config = Config.from_yaml(yaml_path="/Users/stepanborodin/Downloads/test123/data.yaml") # грузимя с .yaml с папки датасета

dataset = Dataset(config=config, category=Mock) # Инитим дататсет

print(config) # Конфиг ДЛЯ датасета

print(config.task)

print(dataset)
print(dataset.train)
print(dataset.health())

for item in dataset.train:

    cv2.imshow("frame", dataset.visualize(sample=item, style=style))
    if cv2.waitKey(1):
        pass

cv2.destroyAllWindows()

print(dataset.health())

print()
print(dataset.train[0].stem)
print(dataset.train[0].image_path)
print(dataset.train[0].label_path)


print()
parser = dataset.label_parser # Сам парссер, который жрет путь к файлу
print(dataset.label_parser)
print()
instances = parser.parse(path=Path(dataset.train[0].label_path))  # Сам списсок (так как на одной картинке может быть несколько меток)
print(instances[0].box)
print(instances[0].obb)
print(instances[0].polygon)

print()
print(instances[0].box.to_xyxyn())
print(instances[0].polygon.to_xyxyn())
