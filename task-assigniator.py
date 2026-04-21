import sys
import csv
import secrets
import html
import json
import hashlib
import hmac
import os
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

# Reads task files from a directory and returns their filenames.
def load_task_filenames(tasks_dir):
    task_dir_path = Path(tasks_dir)
    if not task_dir_path.exists() or not task_dir_path.is_dir():
        raise ValueError(f"Task directory does not exist: {tasks_dir}")

    task_files = [
        path.name
        for path in task_dir_path.iterdir()
        if path.is_file() and path.name not in {
            "assigned_tasks.md",
            "assigned_tasks.html",
            "assigned_tasks_audit.json",
        }
    ]
    if not task_files:
        raise ValueError(f"No task files found in directory: {tasks_dir}")

    return task_files


def generate_assignments(student_count, task_files):
    rng = secrets.SystemRandom()
    assignments = []

    # Shuffle in rounds so each task is used once before being reused.
    while len(assignments) < student_count:
        round_tasks = task_files[:]
        rng.shuffle(round_tasks)
        for task in round_tasks:
            assignments.append(task)
            if len(assignments) >= student_count:
                break

    return assignments


def find_column_index(headers, keywords, fallback_index):
    for idx, header in enumerate(headers):
        normalized = header.strip().lower()
        if normalized in keywords:
            return idx
    return fallback_index


def read_csv_rows(csv_path):
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with open(csv_path, mode='r', newline='', encoding=encoding) as file:
                reader = csv.reader(file, delimiter=';')
                return list(reader)
        except UnicodeDecodeError:
            continue

    raise ValueError(f"Could not decode CSV file with supported encodings: {csv_path}")


def sha256_file(file_path):
    digest = hashlib.sha256()
    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def get_audit_hmac_key():
    key = os.getenv("TASK_ASSIGNMENT_AUDIT_KEY")
    if not key:
        raise ValueError(
            "Missing audit key. Set environment variable TASK_ASSIGNMENT_AUDIT_KEY."
        )
    return key.encode("utf-8")


def canonical_json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sign_audit_payload(audit_payload, key_bytes):
    payload_to_sign = dict(audit_payload)
    payload_to_sign.pop("audit_hmac_sha256", None)
    message = canonical_json(payload_to_sign).encode("utf-8")
    return hmac.new(key_bytes, message, hashlib.sha256).hexdigest()


def verify_audit_file(audit_path):
    key_bytes = get_audit_hmac_key()

    with open(audit_path, mode='r', encoding='utf-8-sig') as file:
        audit_payload = json.load(file)

    signature_in_file = audit_payload.get("audit_hmac_sha256", "")
    if not signature_in_file:
        return False, "Missing audit_hmac_sha256 in audit file"

    expected_signature = sign_audit_payload(audit_payload, key_bytes)
    if not hmac.compare_digest(signature_in_file, expected_signature):
        return False, "Audit JSON signature mismatch"

    sig_path = audit_path.with_suffix(".sig")
    if sig_path.exists():
        with open(sig_path, mode='r', encoding='utf-8-sig') as file:
            signature_in_sig_file = file.read().strip()
        if not hmac.compare_digest(signature_in_sig_file, expected_signature):
            return False, "Signature file mismatch"

    return True, "Audit signature verified"


def write_audit_log(
    audit_path,
    input_csv_path,
    tasks_path,
    output_path,
    task_files,
    all_task_counts,
    student_assignments,
):
    key_bytes = get_audit_hmac_key()

    task_file_hashes = {
        task: sha256_file(tasks_path / task)
        for task in sorted(task_files)
    }

    assignment_digest = hashlib.sha256(
        json.dumps(student_assignments, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    audit_payload = {
        "audit_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": {
            "csv_file": input_csv_path.name,
            "csv_sha256": sha256_file(input_csv_path),
            "tasks_folder": tasks_path.name,
            "task_files_sha256": task_file_hashes,
        },
        "output": {
            "assigned_tasks_html_file": output_path.name,
            "assigned_tasks_html_sha256": sha256_file(output_path),
            "audit_file": audit_path.name,
        },
        "summary": {
            "student_count": len(student_assignments),
            "task_count": len(task_files),
            "assignment_count_per_task": all_task_counts,
            "assignment_list_sha256": assignment_digest,
            "student_number_hash_algorithm": "sha256",
        },
        "assignments": student_assignments,
    }

    audit_signature = sign_audit_payload(audit_payload, key_bytes)
    audit_payload["audit_hmac_sha256"] = audit_signature

    with open(audit_path, mode='w', encoding='utf-8-sig', newline='') as file:
        json.dump(audit_payload, file, ensure_ascii=False, indent=2)
        file.write("\n")

    sig_path = audit_path.with_suffix(".sig")
    with open(sig_path, mode='w', encoding='utf-8-sig', newline='') as file:
        file.write(audit_signature + "\n")

    return sig_path


def assign_tasks(input_filename, tasks_dir):
    task_files = load_task_filenames(tasks_dir)
    tasks_path = Path(tasks_dir).resolve()
    input_csv_path = Path(input_filename).resolve()
    output_path = tasks_path / "assigned_tasks.html"
    audit_path = tasks_path / "assigned_tasks_audit.json"

    lines = read_csv_rows(input_csv_path)

    if len(lines) <= 1:
        raise ValueError("Input CSV must contain a header and at least one student row")

    headers = lines[0]
    number_index = find_column_index(
        headers,
        {"nummer", "studentnr", "studienummer", "nr", "id", "number"},
        0,
    )
    name_index = find_column_index(
        headers,
        {"navn", "name", "fulde navn", "full name"},
        1 if len(headers) > 1 else 0,
    )

    assignments = generate_assignments(len(lines) - 1, task_files)

    html_lines = [
        "<!doctype html>",
        "<html lang=\"da\">",
        "<head>",
        "  <meta charset=\"utf-8\">",
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        "  <title>Tildelte eksamensopgaver</title>",
        "  <style>",
        "    body { font-family: Segoe UI, Arial, sans-serif; margin: 24px; color: #1f2937; }",
        "    h1 { margin: 0 0 16px; font-size: 24px; }",
        "    table { border-collapse: collapse; width: 100%; max-width: 1200px; }",
        "    th, td { border: 1px solid #d1d5db; padding: 8px 10px; text-align: left; }",
        "    th { background: #e5e7eb; }",
        "    tbody tr:nth-child(even) { background: #f9fafb; }",
        "    tbody tr:nth-child(odd) { background: #ffffff; }",
        "  </style>",
        "</head>",
        "<body>",
        "  <h1>Tildelte eksamensopgaver</h1>",
        "  <table>",
        "    <thead>",
        "      <tr><th>Nummer</th><th>Navn</th><th>Opgave</th></tr>",
        "    </thead>",
        "    <tbody>",
    ]

    student_assignments = []

    for i, line in enumerate(lines[1:]):
        student_number = line[number_index].strip() if number_index < len(line) else ""
        student_name = line[name_index].strip() if name_index < len(line) else ""
        assigned_task = assignments[i]
        student_assignments.append({
            "student_number_sha256": sha256_text(student_number),
            "student_name": student_name,
            "assigned_task": assigned_task,
        })
        html_lines.append(
            "      <tr>"
            f"<td>{html.escape(student_number)}</td>"
            f"<td>{html.escape(student_name)}</td>"
            f"<td>{html.escape(assigned_task)}</td>"
            "</tr>"
        )

    html_lines.extend([
        "    </tbody>",
        "  </table>",
        "</body>",
        "</html>",
    ])

    with open(output_path, mode='w', encoding='utf-8-sig', newline='') as file:
        file.write("\n".join(html_lines) + "\n")

    assignment_counts = Counter(assignments)
    all_task_counts = {task: assignment_counts.get(task, 0) for task in sorted(task_files)}

    sig_path = write_audit_log(
        audit_path,
        input_csv_path,
        tasks_path,
        output_path,
        task_files,
        all_task_counts,
        student_assignments,
    )

    return output_path, audit_path, sig_path, all_task_counts


def run_assign_mode(base_filename, tasks_dir):
    if not base_filename.lower().endswith('.csv'):
        raise ValueError("Input file must be a .csv file")

    output_path, audit_path, sig_path, all_task_counts = assign_tasks(base_filename, tasks_dir)
    print(f"Assigned tasks to students: {output_path}")
    print(f"Audit trail written to: {audit_path}")
    print(f"Audit signature written to: {sig_path}")
    print("\nAssignment count per task (alphabetical):")
    for task_name, count in all_task_counts.items():
        print(f"- {task_name}: {count}")


def run_verify_mode(tasks_dir):
    audit_path = Path(tasks_dir).resolve() / "assigned_tasks_audit.json"
    if not audit_path.exists():
        raise ValueError(f"Audit file not found: {audit_path}")

    is_valid, message = verify_audit_file(audit_path)
    if is_valid:
        print(f"OK: {message}")
    else:
        print(f"FAILED: {message}")
        sys.exit(2)


def main():
    try:
        # Backward compatible mode: script.py <students.csv> <tasks_folder>
        if len(sys.argv) == 3 and sys.argv[1].lower().endswith('.csv'):
            run_assign_mode(sys.argv[1], sys.argv[2])
            return

        if len(sys.argv) == 4 and sys.argv[1] == "assign":
            run_assign_mode(sys.argv[2], sys.argv[3])
            return

        if len(sys.argv) == 3 and sys.argv[1] == "verify":
            run_verify_mode(sys.argv[2])
            return

        print("Usage:")
        print("  task-assigninator.py <students.csv> <tasks_folder>")
        print("  task-assigninator.py assign <students.csv> <tasks_folder>")
        print("  task-assigninator.py verify <tasks_folder>")
        print("Environment variable required: TASK_ASSIGNMENT_AUDIT_KEY")
        sys.exit(1)
    except ValueError as error:
        print(error)
        sys.exit(1)


if __name__ == "__main__":
    main()
