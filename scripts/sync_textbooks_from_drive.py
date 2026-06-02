"""
scripts/sync_textbooks_from_drive.py

One-time (or periodic) script that downloads NCERT chapter PDFs
from Google Drive into the correct q-matrix-kb textbook folder structure.

Drive structure:
    NCERT Books/{Grade}/{Subject}/{chapter_number}.{CHAPTER NAME}.pdf

KB target structure:
    textbooks/CBSE/{Subject}/{Grade}/Chapter{N}_{Chapter_Name}/chapter.pdf

Requirements:
    pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

Setup:
    1. Go to https://console.cloud.google.com
    2. Create a project → Enable Google Drive API
    3. Create OAuth 2.0 credentials (Desktop app)
    4. Download credentials.json → place in q-matrix-agents/ root
    5. Run this script — it will open a browser to authenticate on first run
    6. token.json will be saved for future runs (add to .gitignore)
"""

import os
import re
import io
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

load_dotenv()

KB_ROOT         = os.getenv("KB_ROOT")
BOARD           = "CBSE"
SCOPES          = ["https://www.googleapis.com/auth/drive.readonly"]
CREDENTIALS     = "credentials.json"
TOKEN           = "token.json"

# Drive folder IDs discovered from the NCERT Books structure
GRADE_FOLDER_IDS = {
    "Grade 1":  "1TJIMK6z4a6IxVfkgcUiUT3APXszl-OGo",
    "Grade 5":  "1_uaJG0S-F1XyeskUaHwpUUaVDGv3fUJJ",
    "Grade 6":  "195AxAOSPVtrL7FcAvsLT61MXWqzJvSnw",
    "Grade 7":  "16SeYWqZbFfnpgnXdjWnFjueXJnIdJ77M",
    "Grade 8":  "1MyDBhqkzMDi7ovxiqq0e_JGB_RlwjaXM",
    "Grade 9":  "11f7eOH72L8TjCvEglavDtgIBhiEQikM1",
    "Grade 10": "1LUv8F-l2WBRr-oCDL2QEI4dnWvBGRBgL",
    "Grade 11": "13PRpKPEKROnmJK8a9PXPGg7CNZ7TmM2u",
    "Grade 12": "1Ex4JtrLfhAihJTOLWtiVM5OmZQE3aPWr",
}

# Normalize subject names from Drive to KB
SUBJECT_NAME_MAP = {
    "Maths":          "Maths",
    "Science":        "Science",
    "English":        "English",
    "Hindi":          "Hindi",
    "Scoial Science": "Social_Science",  # typo in Drive — handled here
    "Social Science": "Social_Science",
    "History":        "History",
    "Geography":      "Geography",
    "Civics":         "Civics",
    "Economics":      "Economics",
    "Physics":        "Physics",
    "Chemistry":      "Chemistry",
    "Biology":        "Biology",
    "Accountancy":    "Accountancy",
    "Business":       "Business_Studies",
}


def get_drive_service():
    """Authenticate and return a Drive API service instance."""
    creds = None

    if os.path.exists(TOKEN):
        creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS):
                raise FileNotFoundError(
                    "credentials.json not found.\n"
                    "Download it from Google Cloud Console → APIs & Services → Credentials.\n"
                    "Place it in the q-matrix-agents/ root directory."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN, "w") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def list_folder_contents(service, folder_id: str) -> list[dict]:
    """List all files and folders inside a Drive folder."""
    results = []
    page_token = None

    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType)",
            pageToken=page_token
        ).execute()

        results.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return results


def parse_chapter_folder_name(filename: str) -> str:
    """
    Convert a Drive PDF filename to a KB chapter folder name.

    Examples:
        "9.FRICTION.pdf"                    → "Chapter9_Friction"
        "1.Crop Production And Management.pdf" → "Chapter1_Crop_Production_And_Management"
        "2.Microorganisms : Friend And Foe.pdf" → "Chapter2_Microorganisms_Friend_And_Foe"
    """
    # Strip extension
    name = os.path.splitext(filename)[0]

    # Extract chapter number from start
    match = re.match(r"^(\d+)[.\s]+(.+)$", name)
    if not match:
        # Can't parse — use sanitized filename as fallback
        safe = re.sub(r"[^\w\s-]", "", name).strip()
        safe = re.sub(r"[\s]+", "_", safe)
        return safe

    chapter_num = match.group(1)
    chapter_name = match.group(2).strip()

    # Sanitize: remove special chars, replace spaces with underscores, title-case
    chapter_name = re.sub(r"[^\w\s]", "", chapter_name)   # remove : / etc.
    chapter_name = re.sub(r"\s+", "_", chapter_name.strip())
    chapter_name = chapter_name.title().replace("_", "_")  # normalize

    return f"Chapter{chapter_num}_{chapter_name}"


def download_pdf(service, file_id: str, dest_path: str) -> None:
    """Download a PDF from Drive to a local path."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(dest_path, "wb")
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()


def sync(grades: list[str] = None, subjects: list[str] = None, dry_run: bool = False):
    """
    Sync PDFs from Drive to the KB textbooks directory.

    Args:
        grades:   List of grade strings to sync (e.g. ["Grade8", "Grade9"]).
                  If None, syncs all grades.
        subjects: List of subject names to sync (e.g. ["Science", "Maths"]).
                  If None, syncs all subjects.
        dry_run:  If True, print what would be downloaded without downloading.
    """
    service = get_drive_service()
    total_downloaded = 0
    total_skipped    = 0

    target_grades = {
        k: v for k, v in GRADE_FOLDER_IDS.items()
        if grades is None or k in grades
    }

    for grade, grade_folder_id in target_grades.items():
        print(f"\n📁 {grade}")

        subject_folders = [
            f for f in list_folder_contents(service, grade_folder_id)
            if f["mimeType"] == "application/vnd.google-apps.folder"
        ]

        for subject_folder in subject_folders:
            drive_subject_name = subject_folder["name"]
            kb_subject_name    = SUBJECT_NAME_MAP.get(drive_subject_name, drive_subject_name)

            if subjects and kb_subject_name not in subjects:
                continue

            print(f"  📚 {drive_subject_name} → {kb_subject_name}")

            pdfs = [
                f for f in list_folder_contents(service, subject_folder["id"])
                if f["mimeType"] == "application/pdf"
            ]

            for pdf in pdfs:
                chapter_folder = parse_chapter_folder_name(pdf["name"])
                dest_path = os.path.join(
                    KB_ROOT, "textbooks", BOARD,
                    kb_subject_name, grade, chapter_folder, "chapter.pdf"
                )

                if os.path.exists(dest_path):
                    print(f"    ⏭  skipped (exists): {chapter_folder}")
                    total_skipped += 1
                    continue

                if dry_run:
                    print(f"    🔍 would download: {pdf['name']} → {dest_path}")
                else:
                    print(f"    ⬇  downloading: {pdf['name']} → {chapter_folder}")
                    download_pdf(service, pdf["id"], dest_path)
                    print(f"    ✓  saved: {dest_path}")
                    total_downloaded += 1

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  Downloaded: {total_downloaded}")
    print(f"  Skipped (already exists): {total_skipped}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sync NCERT PDFs from Google Drive to q-matrix-kb")
    parser.add_argument("--grades",   nargs="+", help="Grades to sync e.g. Grade8 Grade9")
    parser.add_argument("--subjects", nargs="+", help="Subjects to sync e.g. Science Maths")
    parser.add_argument("--dry-run",  action="store_true", help="Preview without downloading")
    args = parser.parse_args()

    sync(grades=args.grades, subjects=args.subjects, dry_run=args.dry_run)