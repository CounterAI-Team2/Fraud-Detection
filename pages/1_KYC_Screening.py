from __future__ import annotations

from pathlib import Path

import streamlit as st

from utils.audit_logger import log_action
from utils.kyc_store import (
    SANCTIONS_REVIEW_PENDING,
    enrol_customer,
    ensure_kyc_database,
    get_kyc_customers,
)
from utils.mas_sanctions_sync import (
    MAS_INDEX_URL,
    get_last_sync,
    import_uploaded_list,
    list_catalog_entries,
    screen_name,
    sync_mas_sanctions,
)
from utils.session_utils import get_current_analyst

st.title("1. KYC & Customer Registry")
st.caption(
    "Enrol customers, screen names against the MAS Targeted Financial Sanctions lists, "
    "and track KYC risk and CDD level before transaction upload."
)

ensure_kyc_database()
actor_id, actor_role = get_current_analyst()


def _render_sanctions_status() -> None:
    """Show the latest MAS sync result, catalog, and a manual upload form."""
    sync = st.session_state.get("mas_sync_result") or get_last_sync() or {}
    status = sync.get("status", "unknown")
    fetched_at = sync.get("fetched_at", "")
    error = sync.get("error")
    name_count = sync.get("name_count", 0)
    lists_updated = sync.get("lists_updated", [])

    catalog = list_catalog_entries()
    needs_upload = [entry for entry in catalog if entry["needs_manual_upload"]]

    with st.container(border=True):
        cols = st.columns([3, 2, 1])
        with cols[0]:
            st.markdown(f"**MAS sanctions list status:** `{status}`")
            st.caption(f"Source: [{MAS_INDEX_URL}]({MAS_INDEX_URL})")
            if fetched_at:
                st.caption(f"Last sync: {fetched_at}")
        cols[1].metric("Screened names", f"{name_count:,}")
        if cols[2].button("Refresh now"):
            st.session_state["mas_sync_result"] = sync_mas_sanctions(force=True).to_dict()
            st.rerun()

        if status == "ok" and lists_updated:
            st.success(f"Updated lists: {', '.join(lists_updated)}")
        elif status == "skipped":
            st.info("MAS lists already up to date; no changes pulled.")
        elif status in {"failed", "partial", "needs_upload"}:
            st.warning(
                (error or "MAS sync incomplete.")
                + " Screening continues against the most recent cached names."
            )

        if catalog:
            with st.expander(f"MAS catalog ({len(catalog)} lists)", expanded=bool(needs_upload)):
                catalog_view = [
                    {
                        "List": entry["label"] or entry["key"],
                        "Category": entry["category"],
                        "MAS Last Updated": entry["last_updated"],
                        "Names": entry["name_count"],
                        "Source": entry["source"] or "-",
                        "Needs Upload": "Yes" if entry["needs_manual_upload"] else "",
                    }
                    for entry in catalog
                ]
                st.dataframe(catalog_view, use_container_width=True, hide_index=True)

        _render_manual_upload(catalog)


def _render_manual_upload(catalog: list[dict]) -> None:
    """Form to manually drop in one or more sanctions HTML files."""
    with st.expander("Manually upload sanctions list HTML(s)", expanded=False):
        st.caption(
            "If MAS or a UN sanctions page does not expose a clean alphabetical HTML, "
            "download the list yourself and upload it here. Each file is parsed for "
            "names and merged into the screening list."
        )
        uploaded = st.file_uploader(
            "HTML file(s)",
            type=["html", "htm"],
            accept_multiple_files=True,
            key="mas_manual_upload",
        )

        existing_keys = [entry["key"] for entry in catalog]
        target_options = ["Auto from filename", "New custom list", *existing_keys]
        target = st.selectbox(
            "Assign uploaded files to",
            target_options,
            help=(
                "Pick an existing catalog entry to overwrite that list, choose "
                "'New custom list' to create your own (e.g. an internal watchlist), "
                "or use 'Auto from filename' to derive the key from each filename."
            ),
        )

        custom_key = ""
        custom_label = ""
        custom_category = ""
        custom_last_updated = ""
        if target == "New custom list":
            custom_label = st.text_input("List label", placeholder="e.g. UN 1737 (Iran) - manual")
            custom_key = st.text_input(
                "List key",
                placeholder="e.g. un-1737-list",
                help="Used as the catalog id; spaces and punctuation are normalised.",
            )
            custom_category = st.text_input("Category", placeholder="e.g. Iran")
            custom_last_updated = st.text_input(
                "Last Updated label",
                placeholder="e.g. 27 Sep 2025",
            )

        if uploaded and st.button("Import uploaded files", type="primary"):
            actor_id, actor_role = get_current_analyst()
            results: list[dict] = []
            errors: list[str] = []
            for upload in uploaded:
                try:
                    raw_html = upload.read().decode("utf-8", errors="replace")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{upload.name}: decode failed ({exc})")
                    continue

                if target == "Auto from filename":
                    key_hint = Path(upload.name).stem
                    label_hint = key_hint.replace("-", " ").title()
                    category_hint = ""
                    last_updated_hint = ""
                elif target == "New custom list":
                    key_hint = custom_key or Path(upload.name).stem
                    label_hint = custom_label
                    category_hint = custom_category
                    last_updated_hint = custom_last_updated
                else:
                    key_hint = target
                    catalog_match = next((e for e in catalog if e["key"] == target), {})
                    label_hint = catalog_match.get("label", "")
                    category_hint = catalog_match.get("category", "")
                    last_updated_hint = catalog_match.get("last_updated", "")

                result = import_uploaded_list(
                    html=raw_html,
                    key=key_hint,
                    label=label_hint,
                    category=category_hint,
                    last_updated=last_updated_hint,
                )
                results.append({"filename": upload.name, **result})
                log_action(
                    action="mas_list_manual_upload",
                    details=(
                        f"key={result['key']}; file={upload.name}; "
                        f"name_count={result['name_count']}"
                    ),
                    analyst_id=actor_id,
                    module="kyc_screening",
                    event_type="mas_list_manual_upload",
                    entity_type="sanctions_list",
                    entity_id=result["key"],
                    actor_role=actor_role,
                    payload={
                        "filename": upload.name,
                        "name_count": result["name_count"],
                        "total_names": result["total_names"],
                        "label": label_hint,
                        "category": category_hint,
                    },
                )

            if results:
                for r in results:
                    st.success(
                        f"Imported `{r['filename']}` -> `{r['key']}` "
                        f"({r['name_count']} names; consolidated total: {r['total_names']:,})"
                    )
            for err in errors:
                st.error(err)
            if results:
                st.rerun()


def _complete_enrolment(pending: dict) -> None:
    row, match_info = enrol_customer(
        full_name=pending["FullName"],
        account_no=pending["AccountNo"],
        address=pending["Address"],
        contact_no=pending["ContactNo"],
        comments=pending.get("Comments", ""),
        sanctions_match=pending.get("sanctions_match"),
    )
    log_action(
        action="kyc_customer_enrolled",
        details=(
            f"customer_id={row['id']}; account={row['AccountNo']}; "
            f"sanctions_match={match_info.get('matched', False)}"
        ),
        analyst_id=actor_id,
        module="kyc_screening",
        event_type="kyc_customer_enrolled",
        entity_type="customer",
        entity_id=row["id"],
        actor_role=actor_role,
        payload={
            "id": row["id"],
            "FullName": row["FullName"],
            "AccountNo": row["AccountNo"],
            "sanctions_match": match_info,
            "sanctions_warning_acknowledged": pending.get("sanctions_warning_acknowledged", False),
        },
    )
    st.session_state.pop("kyc_pending_enrol", None)
    success = f"Customer **{row['FullName']}** enrolled successfully (ID: `{row['id']}`)."
    if match_info.get("matched"):
        success += " Sanctions review flagged as **Pending** for follow-up CDD."
    st.session_state["kyc_enrol_success"] = success


@st.dialog("Enrol New Customer")
def enrol_customer_dialog() -> None:
    st.caption("Customer ID is assigned automatically (10 digits).")

    pending = st.session_state.get("kyc_pending_enrol")
    if pending:
        match = pending.get("sanctions_match", {})
        list_key = match.get("list_key") or "MAS Targeted Financial Sanctions list"
        st.warning(
            f"**Warning:** Potential match to **{list_key}** "
            f"(matched name: `{match.get('matched_name', '')}`). "
            "Additional customer due diligence checks are required before this "
            "relationship can proceed."
        )
        st.write(
            f"Pending enrolment: **{pending['FullName']}** - Account **{pending['AccountNo']}**"
        )
        col1, col2 = st.columns(2)
        if col1.button("Register with Pending sanctions review", type="primary", use_container_width=True):
            pending["sanctions_warning_acknowledged"] = True
            try:
                _complete_enrolment(pending)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if col2.button("Cancel", use_container_width=True):
            st.session_state.pop("kyc_pending_enrol", None)
            st.session_state.pop("kyc_open_enrol_dialog", None)
            st.rerun()
        return

    with st.form("enrol_customer_form", clear_on_submit=False):
        full_name = st.text_input("Full Name", placeholder="Legal name as on ID")
        account_no = st.text_input("Account Number", placeholder="Sender account used in transactions")
        address = st.text_input("Address")
        contact_no = st.text_input("Contact Number")
        comments = st.text_area("Comments", height=80, placeholder="Optional notes")
        submitted = st.form_submit_button("Enrol Customer", type="primary", use_container_width=True)

    if not submitted:
        return

    if not full_name.strip():
        st.error("Full Name is required.")
        return
    if not account_no.strip():
        st.error("Account Number is required.")
        return
    if not address.strip():
        st.error("Address is required.")
        return
    if not contact_no.strip():
        st.error("Contact Number is required.")
        return

    payload = {
        "FullName": full_name.strip(),
        "AccountNo": account_no.strip(),
        "Address": address.strip(),
        "ContactNo": contact_no.strip(),
        "Comments": comments.strip(),
    }

    match_info = screen_name(full_name)
    if match_info.get("matched"):
        payload["sanctions_match"] = match_info
        st.session_state["kyc_pending_enrol"] = payload
        st.session_state["kyc_open_enrol_dialog"] = True
        st.rerun()
        return

    try:
        _complete_enrolment(payload)
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))


_render_sanctions_status()

customers = get_kyc_customers()

success_msg = st.session_state.pop("kyc_enrol_success", None)
if success_msg:
    st.success(success_msg)

metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
metric_col1.metric("Enrolled Customers", len(customers))
metric_col2.metric("Low Risk", int(customers["RiskStatus"].astype(str).str.lower().eq("low").sum()))
metric_col3.metric("Medium Risk", int(customers["RiskStatus"].astype(str).str.lower().eq("medium").sum()))
metric_col4.metric(
    "Sanctions Pending",
    int(customers["SanctionsReview"].astype(str).eq(SANCTIONS_REVIEW_PENDING).sum()),
)

if st.button("Enrol New Customer", type="primary"):
    enrol_customer_dialog()

if st.session_state.pop("kyc_open_enrol_dialog", False):
    enrol_customer_dialog()

search = st.text_input("Search by name, ID, or account number", value="")
view = customers.copy()
if search.strip():
    needle = search.strip().lower()
    view = view[
        view["FullName"].astype(str).str.lower().str.contains(needle)
        | view["id"].astype(str).str.lower().str.contains(needle)
        | view["AccountNo"].astype(str).str.lower().str.contains(needle)
    ]

st.subheader("Customer Database")
if view.empty:
    st.info("No customers match your search.")
else:
    if search.strip():
        st.caption(f"Showing {len(view)} of {len(customers)} customers")
    st.dataframe(
        view.rename(
            columns={
                "id": "ID",
                "FullName": "Full Name",
                "AccountNo": "Account No",
                "ContactNo": "Contact No",
                "RiskStatus": "Risk Status",
                "CDDLevel": "CDD Level",
                "SanctionsReview": "Sanctions Review",
                "LastCDDReviewAt": "Last CDD Review",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

st.caption(
    "This MVP registry simulates a bank's KYC feed and overlays MAS sanctions screening "
    "so the AML workflow is end-to-end demonstrable. In production it would consume the "
    "bank's existing customer master and vendor screening data via API."
)
