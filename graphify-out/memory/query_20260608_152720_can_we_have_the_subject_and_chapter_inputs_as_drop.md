---
type: "query"
date: "2026-06-08T15:27:20.342281+00:00"
question: "Can we have the subject and chapter inputs as dropdowns in the dashboard? The options for these inputs should be the relevant folder/file names."
contributor: "graphify"
source_nodes: ["parse_chapter_folder_name()", "get_chapter_pdf_path()", "sync_textbooks_from_drive.py", "kb_access.py"]
---

# Q: Can we have the subject and chapter inputs as dropdowns in the dashboard? The options for these inputs should be the relevant folder/file names.

## Answer

Yes. Added GET /kb/subjects?board=&grade= and GET /kb/chapters?board=&subject=&grade= endpoints to api.py that read the KB textbooks directory structure (KB_ROOT/textbooks/<board>/<subject>/<grade>/<chapter>). Converted the subject and chapter free-text Input fields in dashboard/src/components/dashboard/run-form.tsx to cascading Select dropdowns. Board is also now a Select (CBSE/ICSE/State Board). Subjects reload when board or grade changes; chapters reload when subject changes. The Run Pipeline button is disabled until both subject and chapter are selected.

## Source Nodes

- parse_chapter_folder_name()
- get_chapter_pdf_path()
- sync_textbooks_from_drive.py
- kb_access.py