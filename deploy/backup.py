"""Create a PostgreSQL and uploads backup on the Docker host.

Run from the Innovaapps workspace: python deploy/backup.py BACKUP_DIRECTORY
This script does not stop or restart the stack.
"""

import argparse
import hashlib
import json
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
UPLOAD_TAR = (
    "import sys,tarfile; "
    "archive=tarfile.open(fileobj=sys.stdout.buffer,mode='w|'); "
    "archive.add('/data/uploads',arcname='uploads'); archive.close()"
)


def capture(command: list[str], path: Path) -> None:
    partial = path.with_name(path.name + ".partial")
    with partial.open("xb") as output:
        result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Falha ao criar {path.name}; código de saída {result.returncode}. Arquivo parcial: {partial}")
    if partial.stat().st_size == 0:
        raise RuntimeError(f"Backup vazio: {partial}")
    partial.rename(path)


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup do banco e uploads do LeadEngine360")
    parser.add_argument("backup_directory", type=Path)
    args = parser.parse_args()
    output_dir = args.backup_directory.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y%m%d-%H%M%S")
    dump = output_dir / f"leadengine360-{stamp}.dump"
    uploads = output_dir / f"leadengine360-{stamp}-uploads.tar"
    manifest = output_dir / f"leadengine360-{stamp}.json"
    if any(path.exists() or path.with_name(path.name + ".partial").exists() for path in (dump, uploads, manifest)):
        raise RuntimeError("Já existe um backup com este horário; tente novamente em alguns segundos")

    capture(["docker", "compose", "exec", "-T", "db", "sh", "-c", 'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_dump -U leadengine -d leadengine360 -Fc'], dump)
    with dump.open("rb") as stream:
        if stream.read(5) != b"PGDMP":
            raise RuntimeError(f"O arquivo {dump} não tem o cabeçalho esperado do pg_dump")
    capture(["docker", "compose", "exec", "-T", "api", "python", "-c", UPLOAD_TAR], uploads)
    with tarfile.open(uploads, "r") as archive:
        if not any(member.name == "uploads" for member in archive.getmembers()):
            raise RuntimeError("O arquivo de uploads não contém a pasta esperada")
    contents = {path.name: {"bytes": path.stat().st_size, "sha256": checksum(path)} for path in (dump, uploads)}
    manifest.write_text(json.dumps({"created_at": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(), "files": contents}, indent=2), encoding="utf-8")
    print(f"Backup criado em {output_dir}: {dump.name}, {uploads.name}, {manifest.name}")


if __name__ == "__main__":
    main()
