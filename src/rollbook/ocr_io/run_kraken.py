import subprocess
from pathlib import Path
from pdf2image import convert_from_path
from collections.abc import Callable

def build_kraken_command(image_path: Path,
                         output_path:Path,
                         seg_model_path: Path,
                         ocr_model_path: Path,
                         extra_args: list[str] | None = None) -> list[str]:
    command = [
        "kraken",
        "-i",
        str(image_path),
        str(output_path),
        "segment",
        "-bl",
        "-i",
        str(seg_model_path),
        "ocr",
        "-m",
        str(ocr_model_path),
    ]
    if extra_args:
        command += extra_args
    return command


def run_kraken(command: list[str]) -> None:
    subprocess.run(command, check=True)


def render_pdf_pages(pdf_path: Path, output_dir: Path, dpi: int = 400) -> tuple[Path, ...]:
    images = convert_from_path(str(pdf_path), dpi=dpi, fmt="png",
                               output_folder=str(output_dir), thread_count=2)

    img_tuple: tuple[Path, ...] = ()

    for i, img in enumerate(images, start=1):
        img_path = output_dir / f"page_{i:04d}.png"
        img.save(img_path, format="PNG")
        img_tuple += img_path,

    return img_tuple


def run_kraken_per_page(image_paths: tuple[Path, ...],
                        output_dir: Path,
                        seg_model_path: Path,
                        ocr_model_path: Path,
                        extra_args: list[str] | None = None,
                        on_page_done: Callable[[int, int], None] | None = None,) -> tuple[Path, ...]:
    txt_tuple: tuple[Path, ...] = ()
    for i, image_path in enumerate(image_paths, start=1):
        output_path = output_dir / f"{image_path.stem}.txt"
        cmd = build_kraken_command(
            image_path=image_path,
            output_path=output_path,
            seg_model_path=seg_model_path,
            ocr_model_path=ocr_model_path,
            extra_args=extra_args
        )
        run_kraken(cmd)
        txt_tuple += output_path,
        if on_page_done:
            on_page_done(i, len(image_paths))
    return txt_tuple


def concatenate_pages(page_paths: tuple[Path, ...],
                      filename: str,
                      output_dir: Path,
                      separator: str = "\n\n") -> Path:
    out_path = output_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        for page in page_paths:
            f.write(separator)
            f.write(page.read_text(encoding="utf-8"))
    return out_path









