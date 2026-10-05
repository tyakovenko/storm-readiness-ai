"""Google Cloud Storage Data Sync Utility for Storm Readiness AI.

Manages synchronization between local `data/raw/` directory and Google Cloud
Storage bucket (gs://uc3-storm-impact-intelligence-data).

Usage:
    # Pull all datasets from Google Cloud Storage
    python data/sync_cloud_data.py pull

    # Pull a specific dataset (nri, svi, hurdat2, oni, atcf, census, eaglei, dallas, national)
    python data/sync_cloud_data.py pull --dataset nri

    # Check status of local vs cloud data
    python data/sync_cloud_data.py status

    # List datasets stored in the cloud bucket
    python data/sync_cloud_data.py list

    # Push local datasets to cloud bucket
    python data/sync_cloud_data.py push --dataset nri
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_BUCKET = os.getenv("STORM_DATA_BUCKET", "uc3-storm-impact-intelligence-data")
REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_DATA_DIR = REPO_ROOT / "data"

DATASET_MAP = {
    "all": "raw",
    "nri": "raw/nri",
    "svi": "raw/svi",
    "hurdat2": "raw/hurdat2",
    "oni": "raw/oni",
    "atcf": "raw/atcf",
    "census": "raw/census",
    "eaglei": "raw/census/EAGLE I",
    "dallas": "raw/dallas",  # Dallas County (48113) pivot data; see raw/dallas/MANIFEST.md
    "national": "raw/national",  # national baseline for hurricane extension; see raw/national/MANIFEST.md
}


def _find_storage_cmd():
    """Detect whether gcloud or gsutil is available."""
    gcloud_path = shutil.which("gcloud")
    if gcloud_path:
        return [gcloud_path, "storage"]
    gsutil_path = shutil.which("gsutil")
    if gsutil_path:
        return [gsutil_path]
    return None


def _run_storage_cmd(args, capture_output=False):
    """Executes storage command with Windows shell compatibility."""
    is_windows = os.name == "nt"
    return subprocess.run(args, capture_output=capture_output, text=True, shell=is_windows)


def list_cloud_files(bucket=DEFAULT_BUCKET, prefix="raw"):
    """Lists files available in the GCS bucket."""
    cmd = _find_storage_cmd()
    if not cmd:
        print("Error: neither 'gcloud' nor 'gsutil' CLI was found in PATH.")
        sys.exit(1)

    target_uri = f"gs://{bucket}/{prefix}/"
    print(f"Listing objects in {target_uri} ...")
    if "storage" in cmd:
        full_cmd = cmd + ["ls", "--recursive", target_uri]
    else:
        full_cmd = cmd + ["ls", "-r", target_uri]

    result = _run_storage_cmd(full_cmd, capture_output=True)

    if result.returncode != 0:
        print(f"Error listing bucket objects: {result.stderr}")
        return []

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip() and not line.strip().endswith(":")]
    return lines


def pull_dataset(dataset="all", bucket=DEFAULT_BUCKET):
    """Downloads dataset(s) from GCS to local data/ directory."""
    if dataset not in DATASET_MAP:
        print(f"Unknown dataset '{dataset}'. Valid choices: {list(DATASET_MAP.keys())}")
        sys.exit(1)

    rel_subpath = DATASET_MAP[dataset]
    src_uri = f"gs://{bucket}/{rel_subpath}/"
    dest_dir = LOCAL_DATA_DIR / rel_subpath
    dest_dir.mkdir(parents=True, exist_ok=True)

    cmd = _find_storage_cmd()
    if not cmd:
        print("Error: neither 'gcloud' nor 'gsutil' CLI was found in PATH.")
        print(f"Install Google Cloud SDK to download data from gs://{bucket}/")
        sys.exit(1)

    print(f"Pulling {dataset} data from {src_uri} to {dest_dir} ...")
    if "storage" in cmd:
        run_cmd = cmd + ["cp", "-r", f"{src_uri}*", str(dest_dir)]
    else:
        run_cmd = cmd + ["-m", "cp", "-r", f"{src_uri}*", str(dest_dir)]

    res = _run_storage_cmd(run_cmd)
    if res.returncode == 0:
        print(f"Successfully downloaded {dataset} to {dest_dir}")
    else:
        print(f"Download failed with exit code {res.returncode}")
    return res.returncode == 0


def push_dataset(dataset="all", bucket=DEFAULT_BUCKET):
    """Uploads local dataset(s) to GCS bucket."""
    if dataset not in DATASET_MAP:
        print(f"Unknown dataset '{dataset}'. Valid choices: {list(DATASET_MAP.keys())}")
        sys.exit(1)

    rel_subpath = DATASET_MAP[dataset]
    src_dir = LOCAL_DATA_DIR / rel_subpath
    if not src_dir.exists():
        print(f"Local source directory does not exist: {src_dir}")
        sys.exit(1)

    dest_uri = f"gs://{bucket}/{rel_subpath}/"

    cmd = _find_storage_cmd()
    if not cmd:
        print("Error: neither 'gcloud' nor 'gsutil' CLI was found in PATH.")
        sys.exit(1)

    print(f"Pushing {dataset} data from {src_dir} to {dest_uri} ...")
    if "storage" in cmd:
        run_cmd = cmd + ["cp", "-r", f"{str(src_dir)}/*", dest_uri]
    else:
        run_cmd = cmd + ["-m", "cp", "-r", f"{str(src_dir)}/*", dest_uri]

    res = _run_storage_cmd(run_cmd)
    if res.returncode == 0:
        print(f"Successfully uploaded {dataset} to {dest_uri}")
    else:
        print(f"Upload failed with exit code {res.returncode}")
    return res.returncode == 0


def show_status(bucket=DEFAULT_BUCKET):
    """Compares local files with cloud files."""
    print(f"Bucket: gs://{bucket}/raw")
    print(f"Local Data Directory: {LOCAL_DATA_DIR / 'raw'}\n")

    cloud_files = list_cloud_files(bucket=bucket)
    cloud_rel = set()
    for f in cloud_files:
        if f.startswith(f"gs://{bucket}/"):
            cloud_rel.add(f.replace(f"gs://{bucket}/", "").replace("/", os.sep))

    local_files = [str(p.relative_to(LOCAL_DATA_DIR)) for p in (LOCAL_DATA_DIR / "raw").rglob("*") if p.is_file()] if (LOCAL_DATA_DIR / "raw").exists() else []
    local_set = set(local_files)

    print(f"Cloud object count: {len(cloud_rel)}")
    print(f"Local file count:  {len(local_set)}")

    common = local_set.intersection(cloud_rel)
    only_cloud = cloud_rel - local_set
    only_local = local_set - cloud_rel

    print(f"Synced files:      {len(common)}")
    if only_cloud:
        print(f"Available on Cloud (not downloaded locally): {len(only_cloud)}")
        for f in sorted(list(only_cloud))[:5]:
            print(f"   + {f}")
        if len(only_cloud) > 5:
            print(f"   ... and {len(only_cloud) - 5} more")

    if only_local:
        print(f"Local only (not yet in Cloud): {len(only_local)}")
        for f in sorted(list(only_local))[:5]:
            print(f"   - {f}")


def ensure_data(rel_path: str, bucket=DEFAULT_BUCKET) -> Path:
    """Convenience helper for models and pipelines.

    Ensures that a relative path (e.g. 'raw/nri/nri_counties.csv') exists
    locally. If missing, it downloads it directly from Google Cloud Storage.
    """
    local_path = LOCAL_DATA_DIR / rel_path
    if local_path.exists():
        return local_path

    print(f"File {local_path} not found locally. Fetching from gs://{bucket}/{rel_path} ...")
    local_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = _find_storage_cmd()
    if not cmd:
        raise FileNotFoundError(f"Missing {local_path} and 'gcloud'/'gsutil' not available.")

    src_uri = f"gs://{bucket}/{rel_path.replace(os.sep, '/')}"
    run_cmd = cmd + ["cp", src_uri, str(local_path)]
    res = _run_storage_cmd(run_cmd)

    if res.returncode != 0 or not local_path.exists():
        raise FileNotFoundError(f"Failed to fetch {src_uri} to {local_path}")

    return local_path


def main():
    parser = argparse.ArgumentParser(description="Sync storm readiness data with Google Cloud Storage")
    parser.add_argument("action", choices=["pull", "push", "list", "status"], help="Action to perform")
    parser.add_argument("--dataset", choices=list(DATASET_MAP.keys()), default="all", help="Dataset subset")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET, help=f"GCS bucket name (default: {DEFAULT_BUCKET})")

    args = parser.parse_args()

    if args.action == "pull":
        pull_dataset(dataset=args.dataset, bucket=args.bucket)
    elif args.action == "push":
        push_dataset(dataset=args.dataset, bucket=args.bucket)
    elif args.action == "list":
        files = list_cloud_files(bucket=args.bucket)
        for f in sorted(files):
            print(f)
    elif args.action == "status":
        show_status(bucket=args.bucket)


if __name__ == "__main__":
    main()
