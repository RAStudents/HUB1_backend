
from enum import Enum

import cv2
import numpy as np
from acmenra_cv import Style, Font, Stroke, Fill, LabelPosition
from acmenra_ds import Dataset, Config, Compose, Resize

style = Style(palette=np.random.randint(0, 255, (80, 3)).tolist(),
              font=Font(color=(255, 100, 150),
                        font=cv2.FONT_HERSHEY_PLAIN,
                        font_scale=1,
                        thickness=2),
              stroke=Stroke(thickness=6,
                            segment=0.08,
                            alpha=0.90),
              fill=Fill(alpha=0.4 ),
              smooth=0,
              alpha=0.99,
              show=True,
              rounding=0.05,
              label=LabelPosition.OFF)


class Mock(Enum):
    inclusion = 0
    patches = 1
    pitted = 2
    scratch = 3
    crack = 4
    corrosion = 5


config = Config.from_yaml(yaml_path="**Path to dataset dir**/data.yaml")

dataset = Dataset(config=config, category=Mock)

print(dataset)

print(dataset.train[0])

cv2.imwrite("test.png", dataset.visualize(sample=dataset.train[0], style=style))
cv2.imwrite("test1.png", cv2.resize(dataset.visualize(sample=dataset.train[0], style=style), (320, 320)))