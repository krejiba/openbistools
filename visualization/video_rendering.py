# Copyright 2024 Khalil Rejiba, Dhamini Mahendran
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import cv2
from io import BytesIO


class VideoRenderer:
    """
    A class to create a GIF animation from a video file using using OpenCV.

    Attributes:
        num_frames (int): The number of frames to extract from the video.
        frame_duration (float): The duration (in seconds) each frame will be displayed in the GIF.

    Methods:
        read_frames(path: str | Path) -> list[Image]: Reads and extracts frames from the video file.
        get_image(path: str | Path, name: str = "", height: int = 480) -> Image: Generates a GIF from the video.
    """

    ALLOWED_EXTENSIONS = "mp4,avi".split(",")

    def __init__(self, num_frames: int = 50, frame_duration_s: float = 10):
        """
        Initializes the VideoRenderer instance.

        Args:
            num_frames (int): The number of frames to extract from the video. Default is 50.
            frame_duration_s (float): The duration (in seconds) for each frame in the GIF. Default is 10.
        """
        super(VideoRenderer, self).__init__()
        self.num_frames = num_frames
        self.frame_duration = frame_duration_s

    def read_frames(self, path: str | Path) -> list[Image]:
        """
        Extracts frames from the video at evenly spaced intervals.

        Args:
            path (str | Path): The path to the video file from which frames should be extracted.

        Returns:
            list[Image]: A list of PIL Image objects representing the extracted frames.

        Raises:
            ValueError: If the video file cannot be opened or has no frames.
        """
        frames = []
        video_capture = cv2.VideoCapture(path)

        if not video_capture.isOpened():
            raise ValueError(f"Unable to open video file: {path}")
        total_frames = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames == 0:
            raise ValueError(f"No frames detected in {path}")
        frame_indices = [
            i * total_frames // self.num_frames for i in range(self.num_frames)
        ]

        for frame_index in frame_indices:
            video_capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ret, image_cv2 = video_capture.read()
            if not ret:
                continue
            image_cv2_rgb = cv2.cvtColor(image_cv2, cv2.COLOR_BGR2RGB)
            image_pil = Image.fromarray(image_cv2_rgb)
            frames.append(image_pil)
        video_capture.release()

        return frames

    def _overlay_text_on_frames(self, frames: list[Image], text: str) -> list[Image]:
        """
        Overlays text on all frames.

        Args:
            frames (list[Image]): The list of PIL Image objects representing the video frames.
            text (str): The text to overlay on each frame.

        Returns:
            list[Image]: A list of PIL Image objects with the text overlayed.
        """
        frames_with_text = []
        font = ImageFont.load_default()
        x, y = 0, 0  # Text position

        for frame in frames:
            draw = ImageDraw.Draw(frame)
            text_left, text_top, text_right, text_bottom = draw.textbbox(
                (x, y), text, font=font
            )
            draw.rectangle((x, y, text_right, text_bottom), fill="black")
            draw.text((x, y), text, font=font, fill="white")
            frames_with_text.append(frame)
        return frames_with_text

    def get_image(
        self,
        path: str | Path,
        name: str = "",
        height: int = 480,
    ) -> Image:
        """
        Generates an animated image from a video file using OpenCV.

        Args:
            path (str | Path): The path to the video file.
            name (str): Text to overlay on the frames. Default is an empty string (no text).
            height (int, optional): The height of the output image in pixels. Defaults to 480.

        Returns:
            Image: A PIL Image representing the generated animated GIF.
        """
        if isinstance(path, str):
            path = Path(path)
        # Validate file extension

        extension = path.suffix[1:].lower()
        if not extension in self.ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file extension '{extension}'. Allowed extensions: {', '.join(self.ALLOWED_EXTENSIONS)}."
            )
        # Read frames from video file

        frames = self.read_frames(path=path)
        if not frames:
            raise ValueError(f"No frames extracted from the video {path}")
        # Resize frames while maintaining aspect ratio

        width_orig, height_orig = frames[0].size
        width = int(height * width_orig / height_orig)
        frames = [frame.resize((width, height)) for frame in frames]

        # Overlay text on frames (if required)

        if name:
            frames = self._overlay_text_on_frames(frames, name)
        # Create GIF in memory

        buffer = BytesIO()
        frames[0].save(
            buffer,
            format="GIF",
            append_images=frames[1:],
            save_all=True,
            duration=self.frame_duration,
            loop=0,
        )
        buffer.seek(0)

        return Image.open(buffer)


# export OPENCV_LOG_LEVEL='OFF'
# export OPENCV_FFMPEG_LOGLEVEL='-8'
# $env:OPENCV_LOG_LEVEL='OFF'
# $env:OPENCV_FFMPEG_LOGLEVEL='-8'
