"""Собрать переносимый архив из белого списка исходников, без рабочих каталогов."""
import argparse
import gzip
import tarfile
import tempfile
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = {
    "app/web/static/brand-kit/assets/fonts/DejaVuSans.ttf",
    "app/web/static/brand-kit/assets/fonts/DejaVuSans-Bold.ttf",
    "app/web/static/brand-kit/assets/fonts/LICENSE-DejaVu.txt",
    ".dockerignore", ".env.example", "Dockerfile", "docker-compose.yml",
    "requirements/web.txt", "requirements/cloud.txt", "deploy/cloud.py",
    "deploy/proxy/nginx.conf", "deploy/scripts/ops.sh", "deploy/scripts/pack.py",
    "deploy/scripts/smoke.py", "docs/v2_yandex_cloud_deployment.md", "deploy/README.md",
}
PATTERNS = ("app/**/*.py", "app/web/templates/*.html", "app/web/static/**/*.css",
            "app/web/static/**/*.js", "app/web/static/**/*.svg", "app/web/static/**/*.woff2",
            "migrations/*.sql")


def pack(destination):
    names = FILES | {str(p.relative_to(ROOT)) for pattern in PATTERNS for p in ROOT.glob(pattern)}
    # В случае сбоя конечное имя не указывает на незаконченную поставку.
    with tempfile.NamedTemporaryFile(dir=destination.resolve().parent) as output:
        with gzip.GzipFile(fileobj=output, filename="", mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for name in sorted(names):
                    path = ROOT / name
                    if not path.is_file() or path.resolve() != path:
                        raise ValueError(f"Отсутствует обычный файл поставки: {path}")
                    # В корне дистрибутива также лежит краткая инструкция.
                    entries = [name, "README.md"] if name == "deploy/README.md" else [name]
                    for entry in entries:
                        info = tarfile.TarInfo(f"plankton-time-cloud/{entry}")
                        info.mode = 0o755 if name.endswith(".sh") else 0o644
                        info.size = path.stat().st_size
                        with path.open("rb") as resource:
                            archive.addfile(info, resource)
        output.flush()
        os.link(output.name, destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Новый файл .tar.gz")
    pack(parser.parse_args().archive)
