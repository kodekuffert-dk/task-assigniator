import importlib.util
import os
import tempfile
import uuid
import zipfile
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

APP_ROOT = Path(__file__).resolve().parent
TASKS_DIR = (APP_ROOT / os.getenv("TASKS_DIR", "tasks")).resolve()
ALLOWED_DOWNLOADS = {
    "assigned_tasks.html",
    "assigned_tasks_audit.json",
    "assigned_tasks_audit.sig",
    "reassigned_tasks.html",
    "reassigned_tasks_audit.json",
    "reassigned_tasks_audit.sig",
}
MAX_TASKS_ZIP_SIZE_BYTES = 20 * 1024 * 1024
MAX_TASKS_FILE_COUNT = 500


def load_assignment_module():
    module_path = APP_ROOT / "task-assigniator.py"
    spec = importlib.util.spec_from_file_location("task_assigniator_cli", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load task-assigniator.py module")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


assignment_module = load_assignment_module()

app = Flask(__name__)


@app.errorhandler(HTTPException)
def handle_http_exception(error):
    return jsonify({"error": error.description}), error.code


def save_upload(file_storage, suffix):
    temp_dir = Path(tempfile.gettempdir()) / "task-assigniator-uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)

    safe_name = secure_filename(file_storage.filename or "upload")
    unique_name = f"{uuid.uuid4().hex}-{safe_name}"
    if suffix and not unique_name.lower().endswith(suffix):
        unique_name += suffix

    destination = temp_dir / unique_name
    file_storage.save(destination)
    return destination


def clear_existing_task_files(tasks_dir):
    preserved = ALLOWED_DOWNLOADS | {"assigned_tasks.md"}
    for path in tasks_dir.iterdir():
        if path.is_file() and path.name not in preserved:
            path.unlink()


def extract_tasks_zip(zip_path, tasks_dir):
    if zip_path.stat().st_size > MAX_TASKS_ZIP_SIZE_BYTES:
        raise ValueError("Tasks ZIP is too large (max 20 MB).")

    extracted_count = 0
    extracted_total_size = 0
    with zipfile.ZipFile(zip_path, "r") as archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        if not members:
            raise ValueError("Tasks ZIP has no files.")
        if len(members) > MAX_TASKS_FILE_COUNT:
            raise ValueError("Tasks ZIP contains too many files.")

        clear_existing_task_files(tasks_dir)
        for member in members:
            member_name = member.filename.replace("\\", "/").strip()
            if not member_name or member_name.startswith("/") or member_name.startswith("../"):
                raise ValueError("Tasks ZIP contains unsafe paths.")
            if "/../" in member_name:
                raise ValueError("Tasks ZIP contains unsafe paths.")

            normalized_name = Path(member_name).name
            if not normalized_name:
                continue
            if normalized_name in ALLOWED_DOWNLOADS or normalized_name == "assigned_tasks.md":
                continue

            safe_name = secure_filename(normalized_name)
            if not safe_name:
                continue

            destination = tasks_dir / safe_name
            if destination.resolve().parent != tasks_dir.resolve():
                raise ValueError("Tasks ZIP contains unsafe destination paths.")

            data = archive.read(member)
            extracted_total_size += len(data)
            if extracted_total_size > MAX_TASKS_ZIP_SIZE_BYTES:
                raise ValueError("Tasks ZIP extracted content is too large.")

            with open(destination, "wb") as output_file:
                output_file.write(data)
            extracted_count += 1

    if extracted_count == 0:
        raise ValueError("Tasks ZIP did not contain usable task files.")

    return extracted_count


def apply_tasks_zip_upload():
    """Extract tasks ZIP from the current request if provided. Returns error response or None."""
    tasks_zip_file = request.files.get("tasks_zip")
    if not tasks_zip_file or not tasks_zip_file.filename:
        return None

    if not tasks_zip_file.filename.lower().endswith(".zip"):
        return jsonify({"error": "tasks_zip must be a .zip file."}), 422

    tasks_zip_path = save_upload(tasks_zip_file, ".zip")
    try:
        count = extract_tasks_zip(tasks_zip_path, TASKS_DIR)
    except (ValueError, zipfile.BadZipFile) as error:
        return jsonify({"error": f"Invalid tasks ZIP: {error}"}), 422

    return count


def file_download_urls():
    return {
        filename: f"/files/{filename}"
        for filename in sorted(ALLOWED_DOWNLOADS)
        if (TASKS_DIR / filename).exists()
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Liveness probe for container orchestration."""
    return jsonify({"status": "ok"})


@app.post("/tasks")
def upload_tasks():
    """
    Replace the current task files with the contents of a ZIP archive.

    multipart/form-data fields:
      tasks_zip  (file, required)  ZIP archive containing task files.
    """
    tasks_zip_file = request.files.get("tasks_zip")
    if not tasks_zip_file or not tasks_zip_file.filename:
        return jsonify({"error": "tasks_zip file is required."}), 422

    if not tasks_zip_file.filename.lower().endswith(".zip"):
        return jsonify({"error": "tasks_zip must be a .zip file."}), 422

    tasks_zip_path = save_upload(tasks_zip_file, ".zip")
    try:
        count = extract_tasks_zip(tasks_zip_path, TASKS_DIR)
    except (ValueError, zipfile.BadZipFile) as error:
        return jsonify({"error": str(error)}), 422

    task_files = [
        path.name for path in sorted(TASKS_DIR.iterdir())
        if path.is_file() and path.name not in ALLOWED_DOWNLOADS
    ]
    return jsonify({"message": f"Extracted {count} task file(s).", "task_files": task_files}), 200


@app.post("/assignments")
def create_assignment():
    """
    Assign tasks to students and return download links for the generated files.

    multipart/form-data fields:
      students_csv  (file, required)  Semicolon-separated CSV with student data.
      tasks_zip     (file, optional)  ZIP archive that replaces current task files first.
    """
    if not TASKS_DIR.exists() or not TASKS_DIR.is_dir():
        return jsonify({"error": f"Tasks folder not found: {TASKS_DIR}"}), 500

    students_file = request.files.get("students_csv")
    if not students_file or not students_file.filename:
        return jsonify({"error": "students_csv file is required."}), 422
    if not students_file.filename.lower().endswith(".csv"):
        return jsonify({"error": "students_csv must be a .csv file."}), 422

    zip_result = apply_tasks_zip_upload()
    if isinstance(zip_result, tuple):
        return zip_result

    students_csv_path = save_upload(students_file, ".csv")
    try:
        assignment_module.assign_tasks(str(students_csv_path), str(TASKS_DIR))
    except ValueError as error:
        return jsonify({"error": str(error)}), 422

    return jsonify({
        "message": "Assignment completed.",
        "files": file_download_urls(),
    }), 200


@app.post("/reassignments")
def create_reassignment():
    """
    Reassign tasks for re-exam students and return download links.

    multipart/form-data fields:
      students_csv   (file, required)  CSV with the students receiving new tasks.
      source_audit   (file, required)  Audit JSON from the original assignment run.
      tasks_zip      (file, optional)  ZIP archive that replaces current task files first.
    """
    if not TASKS_DIR.exists() or not TASKS_DIR.is_dir():
        return jsonify({"error": f"Tasks folder not found: {TASKS_DIR}"}), 500

    students_file = request.files.get("students_csv")
    if not students_file or not students_file.filename:
        return jsonify({"error": "students_csv file is required."}), 422
    if not students_file.filename.lower().endswith(".csv"):
        return jsonify({"error": "students_csv must be a .csv file."}), 422

    source_audit_file = request.files.get("source_audit")
    if not source_audit_file or not source_audit_file.filename:
        return jsonify({"error": "source_audit file is required."}), 422
    if not source_audit_file.filename.lower().endswith(".json"):
        return jsonify({"error": "source_audit must be a .json file."}), 422

    zip_result = apply_tasks_zip_upload()
    if isinstance(zip_result, tuple):
        return zip_result

    students_csv_path = save_upload(students_file, ".csv")
    source_audit_path = save_upload(source_audit_file, ".json")
    try:
        assignment_module.reassign_tasks(
            str(students_csv_path),
            str(TASKS_DIR),
            str(source_audit_path),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 422

    return jsonify({
        "message": "Reassignment completed.",
        "files": file_download_urls(),
    }), 200


@app.get("/files")
def list_files():
    """List all generated output files that are available for download."""
    return jsonify({"files": file_download_urls()}), 200


@app.get("/files/<path:filename>")
def download_file(filename):
    """Download a specific generated output file."""
    if filename not in ALLOWED_DOWNLOADS:
        return jsonify({"error": "File not found."}), 404

    file_path = TASKS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        return jsonify({"error": "File not found."}), 404

    return send_from_directory(TASKS_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
