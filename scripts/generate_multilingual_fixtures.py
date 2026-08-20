"""Generate tiny synthetic MKV fixtures with reviewed language metadata."""

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory


@dataclass(frozen=True, slots=True)
class FixtureSpec:
    """One generated episode and its subtitle language tags."""

    filename: str
    subtitle_languages: tuple[str, str]


FIXTURES = (
    FixtureSpec("episode-06.mkv", ("eng", "tur")),
    FixtureSpec("episode-07.mkv", ("eng", "spa")),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", type=Path, default=Path("ffmpeg"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/multilingual-fixtures"),
    )
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    try:
        with TemporaryDirectory(prefix="mpv-enhancer-fixtures-") as directory:
            subtitle_root = Path(directory)
            for spec in FIXTURES:
                _generate_fixture(
                    arguments.ffmpeg,
                    arguments.output,
                    subtitle_root,
                    spec,
                )
    except (OSError, subprocess.CalledProcessError) as error:
        parser.error(f"Fixture generation failed: {error}")
    print(f"Generated {len(FIXTURES)} fixtures in {arguments.output.resolve()}")
    return 0


def _generate_fixture(
    ffmpeg: Path,
    output: Path,
    subtitle_root: Path,
    spec: FixtureSpec,
) -> None:
    subtitle_paths = []
    for language in spec.subtitle_languages:
        subtitle_path = subtitle_root / f"{spec.filename}-{language}.srt"
        subtitle_path.write_text(
            f"1\n00:00:00,000 --> 00:00:01,500\nSynthetic {language} subtitle\n",
            encoding="utf-8",
        )
        subtitle_paths.append(subtitle_path)
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=320x180:r=24:d=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=2",
        "-i",
        str(subtitle_paths[0]),
        "-i",
        str(subtitle_paths[1]),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-map",
        "2:s:0",
        "-map",
        "3:s:0",
        "-metadata:s:a:0",
        "language=eng",
        "-metadata:s:s:0",
        f"language={spec.subtitle_languages[0]}",
        "-metadata:s:s:1",
        f"language={spec.subtitle_languages[1]}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-c:s",
        "srt",
        "-shortest",
        str(output / spec.filename),
    ]
    subprocess.run(command, check=True, shell=False)


if __name__ == "__main__":
    raise SystemExit(main())
