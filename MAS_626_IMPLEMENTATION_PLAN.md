# MAS Notice 626 — Implementation Plan
## CounterAI AML Platform

**Last Updated:** 2026-05-25  
**Regulatory Reference:** MAS Notice 626 (Anti-Money Laundering and Countering the Financing of Terrorism)  
**Platform:** Streamlit multipage app — `app.py` + `pages/` + `utils/` + `data/`

---

## Current Compliance Status

| MAS 626 Requirement Area | Current Status | Gap Severity |
|---|---|---|
| Basic KYC enrolment (name, address, contact) | Partial | — |
| Iran sanctions name screening (fuzzy) | Done | — |
| Demo watchlist screening (account ID) | Partial | — |
| RF-based transaction flagging + alert queue | Done | — |
| STR workflow (Draft → L1 → L2 → Archive) | Done | — |
| Dual audit log (v1 legacy + v2 structured) | Done | — |
| AI governance / model drift monitoring | Done | — |
| Individual ID completeness (DOB, nationality, aliases, gov ID) | **Missing** | High |
| Legal entity type + incorporation data | **Missing** | High |
| Connected parties & beneficial ownership | **Missing** | High |
| Purpose of account / business relationship | **Missing** | High |
| PEP screening + ECDD senior management approval | **Missing** | Critical |
| Source of Wealth / Source of Funds fields | **Missing** | High |
| Verification deadline enforcement (30 / 120-day) | **Missing** | High |
| Travel Rule compliance (cross-border wire > S$1,500) | **Missing** | High |
| Periodic and update-triggered re-screening | **Missing** | Medium |
| 5-year record retention enforcement | **Missing** | Medium |
| Parameter change audit trail | **Missing** | Medium |
| Technology risk assessment record | **Missing** | Medium |

---

## Delivery Phases

| # | Phase | Priority | Effort | MAS Risk if Skipped |
|---|---|---|---|---|
| 1 | Complete Individual & Entity Identification | **P0** | Medium | Critical — invalid identity records break all downstream CDD |
| 2 | Connected Parties & Beneficial Ownership | **P0** | High | Critical — UBO identification is a core CDD obligation |
| 3 | PEP Identification & ECDD Approval Workflow | **P0** | Medium | Critical — PEP onboarding without SM approval is a direct breach |
| 4 | Enhanced Screening (Fuzzy Match + Re-screening) | **P1** | Low–Medium | High — periodic re-screening and name fuzzy match required |
| 5 | Verification Deadline Enforcement (30 / 120-day) | **P1** | Low | High — enforceable timeline rules |
| 6 | Travel Rule Compliance (Wire > S$1,500 + Digital Tokens) | **P1** | Medium | High for cross-border scope |
| 7 | Parameter Change Audit Trail & Technology Risk Assessment | **P2** | Low | Medium — governance and audit readiness |
| 8 | 5-Year Record Retention | **P2** | Medium | Medium — 5-year rule applies after relationships end |

---

## Phase 1 — Complete Individual & Entity Identification

**MAS 626 Reference:** §1 Individual Identification + Legal Entity Identification + Purpose of Account

### What Is Missing

| Required Field | Individual | Legal Entity | Current State |
|---|---|---|---|
| Full name | ✅ | ✅ | `FullName` — done |
| Aliases | Required | Required | **Missing** |
| Unique government ID (NRIC / passport / reg. no.) | Required | Required | **Missing** (only internal account no.) |
| Residential / registered address | Required | Required | `Address` — done |
| Date of birth | Required | N/A | **Missing** |
| Nationality | Required | N/A | **Missing** |
| Registration number | N/A | Required | **Missing** |
| Principal place of business | N/A | Required | **Missing** |
| Date and place of incorporation | N/A | Required | **Missing** |
| Constitution / powers | N/A | Required | **Missing** |
| Customer type (Individual / Legal Entity) | — | — | Hardcoded `Individual` — **Missing** |
| Purpose of account / business relationship | Required | Required | Only generic `Comments` — **Missing** |

### Files to Change

#### `utils/kyc_store.py`
- **Expand `KYC_COLUMNS`** from 7 to 20+ columns:

```python
KYC_COLUMNS = [
    "id",
    "customer_type",           # "Individual" | "Legal Entity"
    "FullName",
    "aliases",                 # comma-separated alternate names
    "national_id",             # NRIC / passport number / company reg. number
    "national_id_type",        # "NRIC" | "Passport" | "Registration Number" | "Other"
    "date_of_birth",           # ISO date string (individuals only)
    "nationality",             # individuals only
    "AccountNo",
    "Address",                 # residential (individual) or registered address (entity)
    "ContactNo",
    "purpose_of_relationship", # required free text
    # Legal entity fields (null for individuals)
    "registration_number",
    "principal_place_of_business",
    "date_of_incorporation",   # ISO date string
    "place_of_incorporation",
    "legal_form",              # constitution / powers summary
    # Risk and status
    "RiskStatus",
    "kyc_verification_status", # "Pending" | "Verified" | "Suspended" | "Terminated"
    "kyc_initiated_at",        # when KYC process was started
    "kyc_verified_at",         # when identity verification was completed
    "Comments",
]
```

- Update `enrol_customer()` to validate required fields per `customer_type`.
- Add schema migration: on `get_kyc_customers()`, if loaded DataFrame is missing new columns, add them with empty defaults (preserves existing 13 mock rows).

#### `pages/1_KYC_Screening.py`
- Replace the flat enrolment dialog with a **two-path form** driven by `customer_type`:
  - **Individual path**: Full Name, Aliases, National ID (type + number), DOB, Nationality, Address, Contact, Purpose of Relationship, Comments.
  - **Legal Entity path**: Company Full Name, Aliases, Registration Number, Registered Address, Principal Place of Business, Date + Place of Incorporation, Legal Form summary, Contact, Purpose of Relationship, Comments.
- Make `purpose_of_relationship` a required field (block submission if empty).
- Run sanctions screening on aliases as well as primary name.

#### `data/kyc_customers.csv`
- Schema migration handled in code at read time — no manual CSV edit required.

---

## Phase 2 — Connected Parties & Beneficial Ownership

**MAS 626 Reference:** §1 Connected Parties + Beneficial Ownership (cascading process)

### What Is Missing
- No connected party tracking of any kind.
- No beneficial ownership (UBO) identification or cascading logic.
- No link between a legal entity customer and its directors / executives / natural-person controllers.

### New Data Store

#### `data/connected_parties.csv`

```
party_id, parent_customer_id, party_type, full_name, aliases, national_id,
national_id_type, nationality, date_of_birth, ownership_pct, control_type,
sanctions_flag, pep_flag, added_at, added_by
```

| Column | Values |
|---|---|
| `party_type` | `Director` / `Executive` / `UBO` / `Nominee` / `Close Associate` |
| `control_type` | `Ownership` / `Voting Rights` / `Executive Authority` / `Other` |
| `ownership_pct` | 0–100 (null if control is non-ownership) |
| `sanctions_flag` | boolean |
| `pep_flag` | boolean |

### New Utility

#### `utils/connected_party_store.py`
- `add_connected_party(parent_customer_id, party_data)` — append to CSV, run sanctions + PEP check on `full_name` and `aliases`.
- `get_connected_parties(parent_customer_id)` — retrieve all parties for a customer.
- `remove_connected_party(party_id, actor_id)` — soft-delete with audit log.
- `check_ubo_completeness(parent_customer_id)` — cascading UBO logic:
  1. Find all parties with `control_type = Ownership` and `ownership_pct >= 25`.
  2. If no such party exists, check for executive authority (`control_type = Executive Authority`).
  3. If still none found, return `ubo_incomplete = True` (flag for analyst resolution).
- `screen_all_connected_parties(parent_customer_id)` — runs name-based sanctions screening against each party; returns list of matches.

### Pages to Change

#### `pages/1_KYC_Screening.py`
- Below each customer's detail card, add a **"Connected Parties & Beneficial Owners"** expander:
  - Table of existing connected parties with columns: Name, Type, Ownership %, Control Type, Sanctions, PEP.
  - "Add Connected Party" button → modal form collecting all `connected_parties.csv` fields.
  - UBO completeness indicator: green check if ≥1 UBO identified; amber warning if no natural person with ≥25% found (with "Identify Executive Authority" prompt).
- Run `screen_all_connected_parties()` when a new party is added; surface any sanctions hits inline.
- Log `connected_party_added` audit event (module: `kyc_screening`).

#### `utils/aml_services.py`
- Add `screen_connected_parties(parent_customer_id)` — thin wrapper that calls `connected_party_store.screen_all_connected_parties()` and writes any hits to the customer's `sanctions_flag` with `sanctions_reason` noting the implicated party.

---

## Phase 3 — PEP Identification & ECDD Approval Workflow

**MAS 626 Reference:** §3 PEP Determination + Senior Management Approval + Source of Wealth / Source of Funds

### What Is Missing
- No PEP flag on customer or connected party records.
- No Senior Management approval gate for PEP or high-risk relationships.
- No Source of Wealth or Source of Funds fields anywhere in the workflow.
- Enhanced monitoring for high-risk does not automatically increase scrutiny beyond setting `cdd_level = Enhanced`.

### Changes to Existing Files

#### `utils/kyc_store.py` — Add PEP fields to `KYC_COLUMNS`

```python
"is_pep",            # boolean
"pep_category",      # "Domestic PEP" | "Foreign PEP" | "International Organisation" | "Close Associate of PEP" | None
"pep_verified_at",   # timestamp when PEP status was confirmed
"pep_verified_by",   # actor_id who confirmed
```

- When `is_pep = True`, automatically set `RiskStatus = High` and `cdd_level = Enhanced` in the enrolment flow.

#### `utils/data_store.py` — Add SM approval fields to `CASE_COLUMNS`

```python
"sm_approval_required",   # boolean — True when cdd_level=Enhanced or is_pep=True
"sm_approval_status",     # "Pending" | "Approved" | "Rejected"
"sm_approver_id",         # actor_id of Senior Management approver
"sm_approved_at",         # timestamp
"sm_rejection_reason",    # free text if rejected
"source_of_wealth",       # free text declared at case level
"sow_verification_means", # "Documentary" | "Independent Cross-check" | "Reasonable Inference"
"source_of_funds",        # free text for the specific transaction
"sof_verification_means", # same enum as above
```

#### `pages/4_Case_Investigation.py` — Senior Management Approval Gate

- When the case has `sm_approval_required = True` and `sm_approval_status = Pending`:
  - Show an **amber banner**: "Senior Management approval required before this relationship can be established or continued."
  - If the logged-in `current_actor_role` is `Senior Management`, show **Approve** and **Reject** buttons with a reason text field.
  - Disable the "Escalate to STR" button until `sm_approval_status = Approved`.
- Add **Source of Wealth** and **Source of Funds** text areas to the CDD workspace, with a dropdown for verification means.
- Log `sm_approval_granted` / `sm_approval_rejected` events (module: `cdd_module`).

#### `pages/1_KYC_Screening.py` — PEP Screening in Enrolment

- Add a "PEP Check" section in the enrolment form:
  - Toggle: "Is this customer a PEP or close associate of a PEP?"
  - If toggled on: show `pep_category` dropdown.
  - Placeholder note for future integration with external PEP list (MAS TFS / World-Check).
- On enrolment of a PEP customer, immediately create a `sm_approval_required = True, sm_approval_status = Pending` record in the case store.

#### `utils/constants.py` — Add new constants

```python
PEP_CATEGORIES = [
    "Domestic PEP",
    "Foreign PEP",
    "International Organisation",
    "Close Associate of PEP",
]
SM_APPROVAL_PENDING   = "Pending"
SM_APPROVAL_APPROVED  = "Approved"
SM_APPROVAL_REJECTED  = "Rejected"
SOW_VERIFICATION_MEANS = ["Documentary", "Independent Cross-check", "Reasonable Inference"]
```

---

## Phase 4 — Enhanced Screening (Fuzzy Matching + Periodic Re-screening)

**MAS 626 Reference:** §4 Relevant Information Sources + Timing + Fuzzy Matching

### Gaps

1. `screen_customer_against_watchlist()` in `utils/aml_services.py` matches only on exact `account_id` — no name matching against the broader watchlist.
2. No periodic re-screening: `last_screened_at` is not tracked.
3. No re-screening trigger when the sanctions watchlist file is updated.

### Changes

#### `utils/aml_services.py` — Extend `screen_customer_against_watchlist()`

```python
# Current: only exact account_id match
# New: add name-based fuzzy matching reusing the existing pattern from kyc_store.py

def screen_customer_against_watchlist(customer_name, account_id, aliases=None):
    watchlist = read_csv_store("reference/sanctions_watchlist.csv")
    hits = []
    # 1. Exact account ID match (existing)
    acct_hit = watchlist[watchlist["account_id"] == account_id]
    hits.extend(acct_hit.to_dict("records"))
    # 2. Fuzzy name match on customer_name + aliases
    names_to_check = [customer_name] + (aliases.split(",") if aliases else [])
    for name in names_to_check:
        name_hits = _fuzzy_name_match(name, watchlist["name"].tolist())
        hits.extend(name_hits)
    return hits
```

- Reuse the fuzzy logic from `name_on_un_sanctions_list()` in `kyc_store.py`.
- Return a list of `{watchlist_id, name, match_type, match_score}` dicts.

#### `utils/kyc_store.py` — Add `last_screened_at` to `KYC_COLUMNS`

- Set `last_screened_at` at enrolment and update on every re-screening run.

#### `pages/1_KYC_Screening.py` — Re-screening Controls

- Add a **"Re-screen All Customers"** button (visible to `Admin` and `Compliance Officer` roles only).
- On click: iterate all enrolled customers, run `screen_customer_against_watchlist()` for each, update `sanctions_flag` and `last_screened_at`, log a `bulk_rescreening_run` audit event with `{customer_count, hits_found, screened_at}`.
- Show "Last screened: {date}" label per customer in the customer table.

#### `pages/7_Management_Dashboard.py` — Screening Staleness Widget

- Add a "Screening Due" metric: count of customers where `last_screened_at` is older than 90 days (configurable via `utils/constants.py` as `RESCREENING_INTERVAL_DAYS = 90`).

#### `app.py` — Watchlist Update Detection

```python
# On startup, compare watchlist file mtime against stored value in
# data/reference/watchlist_meta.json. If changed, set session flag.
watchlist_meta = load_watchlist_meta()  # {"last_known_mtime": "..."}
current_mtime = os.path.getmtime("data/reference/sanctions_watchlist.csv")
if current_mtime > watchlist_meta["last_known_mtime"]:
    st.session_state["watchlist_updated"] = True
    save_watchlist_meta(current_mtime)
```

- When `watchlist_updated = True`, show a banner on Page 1 prompting an immediate re-screening run.

---

## Phase 5 — Verification Deadline Enforcement (30 / 120-Day Rule)

**MAS 626 Reference:** §2 Verification Timelines

### What Is Missing
- No `kyc_initiated_at` or `kyc_verified_at` tracking.
- No automated suspension at 30 days or termination at 120 days.
- No dashboard alerting for overdue customers.

### Changes

#### `utils/constants.py`

```python
KYC_SUSPENSION_DAYS  = 30
KYC_TERMINATION_DAYS = 120
KYC_STATUS_PENDING    = "Pending"
KYC_STATUS_VERIFIED   = "Verified"
KYC_STATUS_SUSPENDED  = "Suspended"
KYC_STATUS_TERMINATED = "Terminated"
```

#### `utils/kyc_store.py`
- `kyc_initiated_at` and `kyc_verified_at` already added in Phase 1.
- `kyc_verification_status` already added in Phase 1.
- Add `mark_kyc_verified(customer_id, actor_id)` — sets `kyc_verified_at`, `kyc_verification_status = Verified`, logs `kyc_verified` event.

#### `utils/aml_services.py` — New `check_verification_deadlines()`

```python
def check_verification_deadlines():
    customers = get_kyc_customers()
    today = date.today()
    for _, row in customers.iterrows():
        if row["kyc_verification_status"] == KYC_STATUS_VERIFIED:
            continue
        initiated = parse_date(row["kyc_initiated_at"])
        if initiated is None:
            continue
        days_elapsed = (today - initiated).days
        if days_elapsed >= KYC_TERMINATION_DAYS and row["kyc_verification_status"] != KYC_STATUS_TERMINATED:
            update_kyc_status(row["id"], KYC_STATUS_TERMINATED)
            log_action("kyc_terminated_overdue", entity_id=row["id"], payload={"days": days_elapsed})
        elif days_elapsed >= KYC_SUSPENSION_DAYS and row["kyc_verification_status"] == KYC_STATUS_PENDING:
            update_kyc_status(row["id"], KYC_STATUS_SUSPENDED)
            log_action("kyc_suspended_overdue", entity_id=row["id"], payload={"days": days_elapsed})
```

- Call `check_verification_deadlines()` from `app.py` on every startup.

#### `pages/1_KYC_Screening.py`
- Add a **"Mark as Verified"** button on each customer card (Compliance Officer / Admin only).
- Show verification status badge (Pending / Verified / Suspended / Terminated) with color coding.

#### `pages/7_Management_Dashboard.py` — CDD Deadline Alerts
- Add **"CDD Deadline Alerts"** section with two metrics:
  - Customers approaching 30 days (warning — days remaining shown).
  - Customers past 120 days (critical — terminated, relationship should cease).
- Expandable table listing each at-risk customer with days elapsed.

---

## Phase 6 — Travel Rule Compliance (Wire Transfers > S$1,500)

**MAS 626 Reference:** §5 Wire Transfer Information (Travel Rule) + Digital Token Transfers

### What Is Missing
- No Travel Rule threshold check.
- No originator information capture for cross-border wires.
- No compliance flag on individual transactions.
- No digital token transfer handling.

### Changes

#### `utils/constants.py`

```python
TRAVEL_RULE_THRESHOLD = 1500          # SGD
TRAVEL_RULE_INFO_TYPES = ["Address", "National ID", "Date of Birth"]
DIGITAL_TOKEN_PAYMENT_TYPES = ["Digital Token", "Crypto", "CBDC"]  # extend as needed
```

#### `utils/feature_engineering.py` — New Derived Flag

```python
# In engineer_features():
df["travel_rule_applicable"] = (
    (df["cross_border"] == 1) &
    (df["Amount"] > TRAVEL_RULE_THRESHOLD)
).astype(int)

df["is_digital_token"] = df["Payment_type"].isin(DIGITAL_TOKEN_PAYMENT_TYPES).astype(int)
```

- Add `travel_rule_applicable` and `is_digital_token` to `ENGINEERED_FEATURES`.

#### New Data Store: `data/travel_rule_records.csv`

```
record_id, transaction_id, originator_name, originator_account,
originator_info_type, originator_info_value, is_compliant,
missing_fields, created_at, created_by
```

| Column | Notes |
|---|---|
| `originator_info_type` | `Address` / `National ID` / `Date of Birth` (one of the three required) |
| `is_compliant` | True only when name + account + one of the three info fields are all present |
| `missing_fields` | comma-separated list of missing required fields |

#### `pages/4_Case_Investigation.py` — Travel Rule Section

- When the transaction has `travel_rule_applicable = 1`, render a **"Travel Rule Compliance"** expander:
  - Display pre-filled originator name and account (from transaction sender data).
  - Dropdown: select which supplementary info was provided (`Address` / `National ID` / `Date of Birth`).
  - Text input for the selected info value.
  - "Mark Compliant" button — saves to `travel_rule_records.csv`, logs `travel_rule_recorded` event.
  - Compliance status badge shown on subsequent loads.

- When `is_digital_token = 1`, show a stricter banner: "Digital token transfer — originator and beneficiary information must be submitted immediately and securely to the receiving institution." Require both originator and beneficiary info before the case can be resolved.

#### `pages/3_Alert_Queue.py` — Travel Rule Badge
- Add a `TR` badge (amber) on alert cards where `travel_rule_applicable = 1` and no compliance record exists yet.
- Add a `DT` badge (red) for digital token transactions.

---

## Phase 7 — Parameter Change Audit Trail & Technology Risk Assessment

**MAS 626 Reference:** §6 Parameter Validation + New Technology Assessment

### Parameter Audit Trail

#### `pages/2_Data_Upload.py`
- The risk threshold slider currently does not emit an audit event on change.
- Add `on_change` callback:

```python
def _on_threshold_change():
    actor_id, actor_role = get_current_analyst()
    log_action(
        action="threshold_changed",
        module="risk_scoring",
        event_type="threshold_changed",
        entity_type="parameter",
        entity_id="risk_threshold",
        payload={
            "old_value": st.session_state.get("_prev_threshold"),
            "new_value": st.session_state["risk_threshold_slider"],
        },
        analyst_id=actor_id,
        actor_role=actor_role,
    )
    st.session_state["_prev_threshold"] = st.session_state["risk_threshold_slider"]
```

#### `pages/8_AI_Governance.py` — Parameter Change History Tab
- Add a **"Parameter History"** tab:
  - Filter audit_log_v2 for `event_type = threshold_changed`.
  - Table: Timestamp, Parameter, Old Value, New Value, Changed By, Role.
  - Download button for governance export.

#### `utils/constants.py` — Document Validated Thresholds

```python
# These thresholds require independent validation per MAS Notice 626 §6.
# Any change must be logged via the threshold_changed audit event.
ALERT_THRESHOLDS = {
    "Critical": 0.85,
    "High":     0.70,
    "Medium":   0.50,
}
HIGH_VALUE_THRESHOLD    = 10_000
OFF_HOURS_START         = 6
OFF_HOURS_END           = 22
RESCREENING_INTERVAL_DAYS = 90
```

### Technology Risk Assessment

#### `pages/8_AI_Governance.py` — Technology Risk Assessment Tab
- Add a **"Technology Risk Assessment"** tab (Admin / Compliance Officer only):
  - Structured checklist rendered as a form:
    - [ ] Anonymity risk: does any `Payment_type` value in the current dataset favour anonymity? (auto-check: flag if any `DIGITAL_TOKEN_PAYMENT_TYPES` present in loaded data)
    - [ ] Model opacity risk: XAI coverage check — verify CART + Logit explanations are available for all scored transactions.
    - [ ] Data integrity risk: audit log continuity check — detect gaps in `event_id` sequence.
    - [ ] Access control adequacy: display role distribution from audit_log_v2 (counts by `actor_role`).
    - [ ] Threshold validation: confirm all `ALERT_THRESHOLDS` have been reviewed and are not at default values without documented rationale.
  - "Export Assessment" button — downloads a dated CSV snapshot of the checklist state for regulatory submission.
  - `assessment_completed_at` and `completed_by` fields stored in `data/model_registry.json`.

---

## Phase 8 — 5-Year Record Retention

**MAS 626 Reference:** §6 5-Year Retention + Transaction Reconstruction

### What Is Missing
- No `retention_expires_at` tracking on any record type.
- No archival workflow or deletion prevention within the retention window.
- No structured export for legal reconstruction.

### Changes

#### `utils/constants.py`

```python
RETENTION_YEARS = 5
```

#### `utils/data_store.py` — Add Retention Fields
- Add `retention_expires_at` (ISO date) to all column schemas:
  - `KYC_COLUMNS` — set to `kyc_verified_at + 5 years` when relationship ends.
  - `CASE_COLUMNS` — set to `closed_at + 5 years`.
  - `STR_CASE_COLUMNS` — set to `archived_at + 5 years`.
  - `AUDIT_COLUMNS` (v2) — set to `timestamp_utc + 5 years` (transaction records) or to `relationship_end_date + 5 years`.

- Add `get_records_due_for_purge(cutoff_date)` — returns records where `retention_expires_at` is not null and is before `cutoff_date`.
- Add `get_records_approaching_expiry(warning_days=90)` — returns records expiring within `warning_days`.

#### New Page: `pages/9_Records_Management.py`

- **Access control**: Admin and Compliance Officer roles only.
- **Three sections**:
  1. **Approaching Expiry** — table of records expiring within 90 days (customer, case, STR records). Export button per record type.
  2. **Overdue for Archival** — records past `retention_expires_at`. "Export for External Archival" button generates a structured ZIP: CDD data + transaction history + all audit events for that customer.
  3. **Purge Log** — records already marked as archived externally (read-only).
- Add **"Mark as Archived Externally"** confirmation dialog — requires actor_id, external archive reference, and confirmation checkbox before setting `archived_externally = True`.
- Log `record_archived_externally` and `record_purge_blocked` (if someone attempts to delete within retention window) audit events.
- **Deletion prevention**: add a check in `data_store.py` write functions — raise a warning if any operation would remove a record with `retention_expires_at` in the future.

---

## New Files Summary

| File | Purpose | Phase |
|---|---|---|
| `data/connected_parties.csv` | Connected party and UBO records | 2 |
| `data/travel_rule_records.csv` | Travel Rule originator info per transaction | 6 |
| `data/reference/watchlist_meta.json` | Watchlist file modification timestamp | 4 |
| `utils/connected_party_store.py` | CRUD + UBO cascading logic | 2 |
| `pages/9_Records_Management.py` | 5-year retention archival workflow | 8 |

## Modified Files Summary

| File | Changes | Phase(s) |
|---|---|---|
| `utils/constants.py` | PEP categories, SM approval statuses, travel rule threshold, retention years, screening interval, KYC deadline constants | 1–8 |
| `utils/kyc_store.py` | Expand `KYC_COLUMNS` (DOB, nationality, aliases, national ID, customer type, purpose, PEP, verification status/dates, last_screened_at) | 1, 3, 4, 5 |
| `utils/data_store.py` | Add SM approval + SoW/SoF fields to `CASE_COLUMNS`; add `retention_expires_at` to all schemas | 3, 8 |
| `utils/aml_services.py` | Extend watchlist screening (name fuzzy), add `check_verification_deadlines()`, add `screen_connected_parties()` | 2, 4, 5 |
| `utils/feature_engineering.py` | Add `travel_rule_applicable`, `is_digital_token` derived flags | 6 |
| `app.py` | Call `check_verification_deadlines()` and watchlist mtime check on startup | 4, 5 |
| `pages/1_KYC_Screening.py` | Two-path enrolment form, connected parties sub-section, PEP toggle, re-screen button, verification status badges | 1, 2, 3, 4, 5 |
| `pages/2_Data_Upload.py` | Threshold change audit callback | 7 |
| `pages/3_Alert_Queue.py` | Travel Rule (TR) and Digital Token (DT) badges on alert cards | 6 |
| `pages/4_Case_Investigation.py` | SM approval gate, SoW/SoF fields, Travel Rule compliance section | 3, 6 |
| `pages/7_Management_Dashboard.py` | Screening staleness widget, CDD deadline alerts section | 4, 5 |
| `pages/8_AI_Governance.py` | Parameter history tab, technology risk assessment tab | 7 |

---

## Audit Events to Add

| Event Type | Module | Trigger | Payload |
|---|---|---|---|
| `connected_party_added` | `kyc_screening` | New connected party enrolled | `{party_type, party_name, parent_customer_id, sanctions_hit}` |
| `ubo_identified` | `kyc_screening` | UBO marked on connected party | `{party_id, ownership_pct, control_type}` |
| `sm_approval_granted` | `cdd_module` | SM approves PEP / high-risk relationship | `{case_id, customer_id, approver_id}` |
| `sm_approval_rejected` | `cdd_module` | SM rejects relationship | `{case_id, customer_id, rejection_reason}` |
| `bulk_rescreening_run` | `kyc_screening` | Compliance officer runs re-screen all | `{customer_count, hits_found, screened_at}` |
| `kyc_suspended_overdue` | `kyc_screening` | 30-day deadline passed without verification | `{customer_id, days_elapsed}` |
| `kyc_terminated_overdue` | `kyc_screening` | 120-day deadline passed | `{customer_id, days_elapsed}` |
| `kyc_verified` | `kyc_screening` | Analyst marks KYC as verified | `{customer_id, verified_by}` |
| `travel_rule_recorded` | `str_workflow` | Travel Rule originator info captured | `{transaction_id, info_type, is_compliant}` |
| `threshold_changed` | `risk_scoring` | Risk threshold slider moved | `{parameter, old_value, new_value}` |
| `record_archived_externally` | `governance` | Record marked as archived for retention | `{entity_type, entity_id, external_ref}` |
| `technology_assessment_completed` | `governance` | Technology risk assessment exported | `{completed_by, assessment_date}` |

---

*Generated from MAS Notice 626 gap analysis against CounterAI AML Platform v1.0 (commit fad5acb).*
