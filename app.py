import importlib.util
import os
import tempfile
import uuid
import zipfile
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template_string, request, send_from_directory, url_for
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

TEMPLATE = """
<!doctype html>
<html lang="da">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Task Assigniator Web</title>
  <style>
    :root {
      --bg: #f8f6f2;
      --card: #fffdf9;
      --text: #1f2a32;
      --muted: #5f6b73;
      --primary: #0f766e;
      --primary-strong: #115e59;
      --danger: #b42318;
      --border: #d9d2c7;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--text);
      background:
        radial-gradient(circle at 10% 20%, #f4e8d4 0, transparent 40%),
        radial-gradient(circle at 90% 80%, #d9efe8 0, transparent 35%),
        var(--bg);
      min-height: 100vh;
    }

    .page {
      max-width: 980px;
      margin: 28px auto;
      padding: 0 18px 30px;
    }

    .hero {
      background: linear-gradient(140deg, #153747 0%, #0f766e 70%);
      color: #fff;
      border-radius: 16px;
      padding: 22px 24px;
      box-shadow: 0 12px 30px rgba(0, 0, 0, 0.18);
      animation: reveal 450ms ease-out;
    }

    .hero h1 {
      margin: 0;
      letter-spacing: 0.4px;
      font-size: 2rem;
    }

    .hero p {
      margin: 8px 0 0;
      color: #d8f6ef;
    }

    .grid {
      margin-top: 18px;
      display: grid;
      gap: 16px;
      grid-template-columns: 1fr;
    }

    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px;
      box-shadow: 0 7px 18px rgba(33, 33, 33, 0.07);
      animation: reveal 550ms ease-out;
    }

    h2 {
      margin: 0 0 12px;
      font-size: 1.3rem;
    }

    label {
      display: block;
      margin-top: 10px;
      color: var(--muted);
      font-size: 0.92rem;
    }

    input[type="file"],
    select {
      width: 100%;
      margin-top: 6px;
      padding: 8px;
      border: 1px solid #b8b0a4;
      border-radius: 8px;
      background: #fff;
    }

    button {
      margin-top: 14px;
      background: var(--primary);
      color: #fff;
      border: 0;
      padding: 10px 14px;
      border-radius: 8px;
      font-weight: 700;
      cursor: pointer;
      transition: transform 120ms ease, background 120ms ease;
    }

    button:hover {
      transform: translateY(-1px);
      background: var(--primary-strong);
    }

    .notes {
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
    }

    .files {
      margin-top: 10px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 8px;
    }

    .file-link {
      display: inline-block;
      text-decoration: none;
      background: #fff7ed;
      color: #9a3412;
      border: 1px solid #fed7aa;
      padding: 9px 10px;
      border-radius: 9px;
      font-weight: 600;
    }

    .flash {
      margin: 10px 0 0;
      padding: 9px 10px;
      border-radius: 8px;
      border: 1px solid;
    }

    .flash.error {
      color: var(--danger);
      border-color: #f7b4ae;
      background: #fef3f2;
    }

    .flash.success {
      color: #14532d;
      border-color: #bbf7d0;
      background: #f0fdf4;
    }

    @keyframes reveal {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }

    @media (min-width: 900px) {
      .grid {
        grid-template-columns: 1.2fr 0.8fr;
      }
    }
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>Task Assigniator Web</h1>
      <p>Run assignment and re-assignment in browser and download output files directly.</p>
    </section>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <div class="flash {{ category }}">{{ message }}</div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <section class="grid">
      <article class="card">
        <h2>Generate output</h2>
        <form method="post" action="{{ url_for('run_assignment') }}" enctype="multipart/form-data">
          <label for="mode">Mode</label>
          <select id="mode" name="mode" required>
            <option value="assign">assign (first assignment)</option>
            <option value="reassign">reassign (new assignment)</option>
          </select>

          <label for="students_csv">Students CSV</label>
          <input id="students_csv" name="students_csv" type="file" accept=".csv" required>

          <label for="source_audit">Original audit JSON (reassign only)</label>
          <input id="source_audit" name="source_audit" type="file" accept=".json">

          <label for="tasks_zip">Tasks ZIP (optional, replaces current task files)</label>
          <input id="tasks_zip" name="tasks_zip" type="file" accept=".zip">

          <button type="submit">Run</button>
        </form>
      </article>

      <article class="card">
        <h2>Downloads</h2>
        <p style="margin-top: 0; color: var(--muted);">These files update after each run:</p>
        <div class="files">
          {% for filename in downloadable_files %}
            <a class="file-link" href="{{ url_for('download', filename=filename) }}">{{ filename }}</a>
          {% endfor %}
        </div>
      </article>
    </section>

    <section class="card" style="margin-top: 16px;">
      <h2>Requirements</h2>
      <ul class="notes">
        <li>Set TASK_ASSIGNMENT_AUDIT_KEY in app/container environment.</li>
        <li>Task files must exist in tasks/ folder or folder from TASKS_DIR.</li>
      </ul>
    </section>
  </main>
</body>
</html>
"""


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
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")


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
            destination_resolved = destination.resolve()
            if destination_resolved.parent != tasks_dir.resolve():
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


@app.get("/")
def index():
    existing_files = [
        filename for filename in sorted(ALLOWED_DOWNLOADS)
        if (TASKS_DIR / filename).exists()
    ]
    return render_template_string(TEMPLATE, downloadable_files=existing_files)


@app.post("/run")
def run_assignment():
    if not TASKS_DIR.exists() or not TASKS_DIR.is_dir():
        flash(f"Tasks folder not found: {TASKS_DIR}", "error")
        return redirect(url_for("index"))

    students_file = request.files.get("students_csv")
    if students_file is None or not students_file.filename:
        flash("Choose a students CSV file.", "error")
        return redirect(url_for("index"))

    mode = request.form.get("mode", "assign").strip().lower()
    if mode not in {"assign", "reassign"}:
        flash("Invalid mode.", "error")
        return redirect(url_for("index"))

    if not students_file.filename.lower().endswith(".csv"):
        flash("Students file must be .csv", "error")
        return redirect(url_for("index"))

    tasks_zip_file = request.files.get("tasks_zip")
    if tasks_zip_file and tasks_zip_file.filename:
      if not tasks_zip_file.filename.lower().endswith(".zip"):
        flash("Tasks ZIP file must be .zip", "error")
        return redirect(url_for("index"))

      tasks_zip_path = save_upload(tasks_zip_file, ".zip")
      try:
        extract_tasks_zip(tasks_zip_path, TASKS_DIR)
      except (ValueError, zipfile.BadZipFile) as error:
        flash(f"Invalid tasks ZIP: {error}", "error")
        return redirect(url_for("index"))

    students_csv_path = save_upload(students_file, ".csv")

    try:
        if mode == "assign":
            assignment_module.assign_tasks(str(students_csv_path), str(TASKS_DIR))
            flash("Assign completed. Files are ready for download.", "success")
        else:
            source_audit_file = request.files.get("source_audit")
            if source_audit_file is None or not source_audit_file.filename:
                flash("Upload original audit JSON for reassign.", "error")
                return redirect(url_for("index"))
            if not source_audit_file.filename.lower().endswith(".json"):
                flash("Audit file must be .json", "error")
                return redirect(url_for("index"))

            source_audit_path = save_upload(source_audit_file, ".json")
            assignment_module.reassign_tasks(
                str(students_csv_path),
                str(TASKS_DIR),
                str(source_audit_path),
            )
            flash("Reassign completed. Files are ready for download.", "success")

    except ValueError as error:
        flash(str(error), "error")

    return redirect(url_for("index"))


@app.get("/download/<path:filename>")
def download(filename):
    if filename not in ALLOWED_DOWNLOADS:
        abort(404)

    file_path = TASKS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        abort(404)

    return send_from_directory(TASKS_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
