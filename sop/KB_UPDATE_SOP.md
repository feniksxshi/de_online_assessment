# Knowledge Base (KB) Update SOP

**Purpose:** Add new or revised documents to the KB with the correct version and full traceability, while preventing superseded rules from appearing in normal search. This SOP applies to all documents submitted by clients for addition, revision, or withdrawal.

## Frequency and Responsibilities

| Item | Requirement |
|---|---|
| **Standard updates** | Review requests every business day; combine and release updates once per week. |
| **Urgent updates** | Release effective policy, security, or SOP changes within four business hours after approval. |
| **Periodic review** | Review expired documents, owners, and active revisions quarterly. |

| Role | Checks performed |
|---|---|
| **Document Owner** | Content, effective date, approver, and the document being superseded. |
| **KB Operator** | Format, metadata, version, build, and artifact release. |
| **Business/QA Reviewer** | Expected answers, citations, and exclusion of superseded revisions. |
| **Technical Reviewer** | Tests, SQLite integrity, manifest, and rollback readiness. |

## Procedure

1. **Receive:** Create a ticket and retain the original submission. Record the `doc_id`, document owner, approver, effective date, and superseded revision. Do not overwrite or delete an older revision.
2. **Validate:** Confirm that the file is UTF-8, its H1 follows `# DOC-ID — Title`, its version/date is valid, and it contains at least one `##` section. Reject unapproved documents, unauthorized secrets/PII, or ambiguous versions.
3. **Resolve the version:** Assign a new `doc_id` to a new document. For a revision, retain the existing `doc_id`, use a newer version/month, and identify the revision it replaces. Keep the old revision for audit, but exclude it from normal active search.
4. **Update evaluation:** Add or revise cases in `kb/eval_questions.json`, including the question, expected source/version and answer terms, maximum acceptable rank, and forbidden superseded version.
5. **Build and test:** Run:

   ```bash
   python3 kb/build_kb.py
   python3 kb/evaluate_kb.py
   python3 kb/smoke_test.py
   python3 -m unittest discover -s kb -p 'test_*.py' -v
   ```

6. **Approve:** QA tests at least one question for every changed fact and confirms the correct citation/version. A superseded revision may appear only with `--include-inactive`. The Technical Reviewer confirms that all tests pass, the manifest is correct, and SQLite validation succeeds.
7. **Release:** Publish `knowledge_base.db`, `chunks.jsonl`, and `build_manifest.json` together. Record results and approvals in the ticket, then run one production verification query.
8. **Rollback:** If retrieval returns an incorrect source or a runtime failure occurs, restore the latest known-good artifact set and correct the source/evaluation before rebuilding. Never edit a released database directly.

## Completion Criteria

The document is approved; every `doc_id` has exactly one active revision; all required tests and evaluations pass; citations are correct; and the ticket and manifest provide complete traceability.
