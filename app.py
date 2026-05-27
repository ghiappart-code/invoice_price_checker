from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
import subprocess

import pandas as pd
import streamlit as st

from invoice_price_checker.database import load_product_database
from invoice_price_checker.odoo_articles import (
    config_from_env,
    config_from_mapping,
    database_status,
    default_database_path,
    refresh_articles_database,
)
from invoice_price_checker.odoo_update import prepare_odoo_update_rows, update_odoo_prices
from invoice_price_checker.matching import compare_invoice_to_database
from invoice_price_checker.models import MatchConfig
from invoice_price_checker.suppliers import detect_supplier_from_text, get_parser, list_suppliers, supplier_label
from invoice_price_checker.text import extract_pdf_text


APP_VERSION = "2026-05-20-1"

st.set_page_config(page_title="Invoice Price Checker", layout="wide")


def _download_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def _download_excel(df: pd.DataFrame, sheet_name: str = "price_changes") -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
        _format_workbook(writer)
    return buffer.getvalue()


def _download_workbook(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        _calculation_notes().to_excel(writer, index=False, sheet_name="calculation_notes")
        for name, sheet in sheets.items():
            sheet.to_excel(writer, index=False, sheet_name=name[:31])
        _format_workbook(writer)
    return buffer.getvalue()


def _git_commit_short() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    commit = result.stdout.strip()
    return commit or None


def _calculation_notes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"column": "Article_ID_Fournisseur", "calculation": "Supplier article reference used as the primary matching key."},
            {"column": "Article_Ref_EAN", "calculation": "Article reference from the database."},
            {"column": "ID_Fournisseur", "calculation": "Supplier ID from the database."},
            {"column": "Fact_Designation", "calculation": "Product designation read from the invoice."},
            {"column": "Fact_PU_Net", "calculation": "Net supplier unit price read from the invoice before fuel surcharge."},
            {"column": "Fact_PU_Net_GZ", "calculation": "Fact_PU_Net * (1 + GAZOLE / 100). Equal to Fact_PU_Net when there is no GAZOLE surcharge."},
            {"column": "Fact_PU_unitaire", "calculation": "Fact_PU_Net_GZ * DB_Fournisseur_Unit_Ratio. This is the invoice price converted to the database unit."},
            {"column": "DB_Prix_Net", "calculation": "Current net purchase price from the database."},
            {"column": "Ecart_Prix", "calculation": "Fact_PU_unitaire - DB_Prix_Net."},
            {"column": "Ecart_Prix_percent", "calculation": "Ecart_Prix / DB_Prix_Net."},
            {"column": "prix_de_vente", "calculation": "Fact_PU_unitaire * (1 + margin_rate / 100) * (1 + TVA / 100), plus consigne when applicable."},
            {"column": "PU_Modif", "calculation": "TRUE when Ecart_Prix < borne_inf or Ecart_Prix > borne_sup, unless the modification is blocked."},
            {"column": "remise_temp", "calculation": "Generic temporary-discount flag. For RELAIS VERT: 1 when Q*, P, or E is non-zero; G is not included."},
            {"column": "Blocage_Modif", "calculation": "TRUE when a price decrease is blocked because remise_temp = 1."},
            {"column": "Ecart_Prix_Anormal", "calculation": "TRUE when abs(Ecart_Prix_percent) > abnormal_ratio and the price is changed, or when an invoice line must be reviewed manually, for example a duplicate supplier reference."},
            {"column": "Raison_du_Blocage", "calculation": "Reason explaining why a modification was blocked or requires manual review, when applicable. ligne_dupliquee_facture means the same supplier reference appears more than once on the invoice; only the first occurrence is used for automatic update. remise_non_appliquee means a price decrease was blocked because a temporary discount is present. ecart de prix > xx% means the price change exceeds the abnormal ratio. reference differente a verifier means the invoice line matched by product designation, not supplier reference."},
            {"column": "DB_Fournisseur_Unit_Ratio", "calculation": "Conversion ratio from the supplier invoice unit to the database article unit."},
            {"column": "Detail_Remise", "calculation": "Human-readable source of remise_temp, for example Q*=12 or E=4."},
            {"column": "TVA", "calculation": "Sales tax rate from the database, used to compute prix_de_vente."},
            {"column": "Taux_de_Marque", "calculation": "Margin category from the database, used to compute prix_de_vente."},
            {"column": "Monnaie", "calculation": "Invoice or database currency."},
            {"column": "Match_Fact_DB", "calculation": "TRUE when the invoice line was matched to a database article."},
            {"column": "Match_Methode", "calculation": "Matching method used, for example supplier article code or description fallback."},
            {"column": "ID_externe", "calculation": "Odoo external ID from the database, kept at the end because it is mainly used for technical checks."},
            {"column": "DB_Designation", "calculation": "Product designation from the database, kept at the end for traceability."},
            {"column": "Coût / Fournisseurs/Prix", "calculation": "For Odoo update review: Coût = Fact_PU_unitaire; Fournisseurs/Prix = Fact_PU_Net_GZ."},
        ]
    )


def _format_workbook(writer: pd.ExcelWriter) -> None:
    numeric_formats = {
        "DB_Prix_Net": "0.000",
        "Fact_PU_Net": "0.000",
        "Fact_PU_Net_GZ": "0.000",
        "DB_Fournisseur_Unit_Ratio": "0.000000000000",
        "Fact_PU_unitaire": "0.000",
        "Ecart_Prix": "0.000",
        "Ecart_Prix_percent": "0.000%",
        "TVA": "0.000",
        "prix_de_vente": "0.00",
        "Coût": "0.000",
        "Fournisseurs/Prix": "0.000",
        "Prix de vente": "0.00",
    }
    for ws in writer.book.worksheets:
        ws.freeze_panes = "A2"
        headers = [cell.value for cell in ws[1]]
        for idx, header in enumerate(headers, start=1):
            if header in numeric_formats:
                for column_cell in ws.iter_cols(min_col=idx, max_col=idx, min_row=2):
                    for cell in column_cell:
                        cell.number_format = numeric_formats[header]
            width = max(12, min(42, len(str(header or "")) + 2))
            ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = width


st.title("Invoice Price Checker")
if status_message := st.session_state.pop("app_status_message", None):
    st.info(status_message)




def _invoice_stem(uploaded_file) -> str:
    name = getattr(uploaded_file, "name", "invoice") or "invoice"
    return Path(name).stem or "invoice"


def _uploaded_file_signature(uploaded_file) -> tuple[str, int] | None:
    if uploaded_file is None:
        return None
    return (
        getattr(uploaded_file, "name", "") or "",
        int(getattr(uploaded_file, "size", 0) or 0),
    )


def _analysis_signature(
    invoice_file,
    database_file,
    supplier_id: str,
    database_source: str,
    data_path: Path,
    status: dict[str, object],
    borne_inf: float,
    borne_sup: float,
    abnormal_ratio: float,
) -> tuple[object, ...]:
    database_signature: object
    if database_source == "Chargement manuel" or not status["exists"]:
        database_signature = ("upload", _uploaded_file_signature(database_file))
    else:
        database_signature = (
            "default",
            str(data_path),
            status.get("modified_at"),
        )

    return (
        _uploaded_file_signature(invoice_file),
        database_signature,
        supplier_id,
        float(borne_inf),
        float(borne_sup),
        float(abnormal_ratio),
    )


def _format_timestamp(value: float | None) -> str:
    if value is None:
        return "n/a"
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def _odoo_config_from_streamlit():
    if "odoo" in st.secrets:
        return config_from_mapping(st.secrets["odoo"])
    return config_from_env()


def _validate_invoice_supplier(uploaded_file, selected_supplier_id: str) -> None:
    try:
        text = extract_pdf_text(uploaded_file)
    except Exception as exc:
        st.error(f"Impossible de lire le texte de la facture PDF: {exc}")
        st.stop()
    finally:
        uploaded_file.seek(0)

    detected_supplier_id = detect_supplier_from_text(text)
    if detected_supplier_id is None:
        st.error(
            "Fournisseur non reconnu. Cette facture ne correspond a aucun fournisseur "
            "actuellement pris en charge."
        )
        st.stop()

    if detected_supplier_id != selected_supplier_id:
        st.error(
            "Le fournisseur selectionne ne correspond pas a la facture. "
            f"Cette facture semble correspondre a {supplier_label(detected_supplier_id)}."
        )
        st.stop()


def _render_odoo_update_controls(odoo_update_rows: pd.DataFrame, invoice_stem: str) -> None:
    st.subheader("Automatic Odoo update")
    if odoo_update_rows.empty:
        st.info("Price changes were found, but no rows are eligible for automatic Odoo update.")
        return

    st.warning(
        f"{len(odoo_update_rows)} changed-price row(s) are eligible for Odoo update. "
        "Review the workbook or the Odoo update tab before applying changes."
    )
    update_report_displayed = False
    confirmation = st.checkbox(
        "I have reviewed the rows above and I want to update Odoo prices",
        key=f"confirm_odoo_update_{invoice_stem}",
    )
    if st.button("Update Odoo prices", disabled=not confirmation, key=f"update_odoo_prices_{invoice_stem}"):
        try:
            with st.spinner("Updating Odoo prices..."):
                summary = update_odoo_prices(odoo_update_rows, _odoo_config_from_streamlit())
            st.session_state["odoo_update_summary"] = summary
            st.success(
                f"Update finished: {summary.success} success, "
                f"{summary.warnings} warning, {summary.errors} error."
            )
            st.dataframe(summary.results, use_container_width=True, hide_index=True)
            st.download_button(
                "Download Odoo update report CSV",
                data=_download_csv(summary.results),
                file_name="odoo_price_update_report.csv",
                mime="text/csv",
                key=f"download_odoo_update_report_{invoice_stem}",
            )
            update_report_displayed = True
        except Exception as exc:
            st.error(f"Could not update Odoo prices: {exc}")

    stored_summary = st.session_state.get("odoo_update_summary")
    if stored_summary is not None and not update_report_displayed:
        st.info(
            f"Last Odoo update report: {stored_summary.success} success, "
            f"{stored_summary.warnings} warning, {stored_summary.errors} error."
        )
        st.dataframe(stored_summary.results, use_container_width=True, hide_index=True)
        st.download_button(
            "Download last Odoo update report CSV",
            data=_download_csv(stored_summary.results),
            file_name="odoo_price_update_report.csv",
            mime="text/csv",
            key=f"download_last_odoo_update_report_{invoice_stem}",
        )


with st.sidebar:
    st.header("Paramètres")
    st.caption(f"Version application : {APP_VERSION}")
    if commit := _git_commit_short():
        st.caption(f"Commit : {commit}")

    supplier_id = st.selectbox(
        "Fournisseur de la facture",
        list_suppliers(include_generic=False),
        format_func=supplier_label,
    )

    st.subheader("Base de données articles")
    data_path = default_database_path()
    status = database_status(data_path)
    if status["exists"]:
        st.caption(f"Base de données actuelle : `{data_path.name}`")
        st.caption(f"Créée le : {_format_timestamp(status['created_at'])}")
        st.caption(f"Modifiée le : {_format_timestamp(status['modified_at'])}")
    else:
        st.warning(
            "Base articles locale absente. Sur Streamlit Community Cloud, cliquez sur "
            "Charger la base articles depuis Odoo avant de traiter une facture, ou chargez une base manuellement."
        )

    database_source = st.radio(
        "Source de la base articles",
        ["Base locale actuelle", "Chargement manuel"],
        disabled=not status["exists"],
    )
    refresh_database = st.button("Charger la base articles depuis Odoo")
    if refresh_database:
        try:
            with st.spinner("Chargement de la base articles depuis Odoo..."):
                refreshed = refresh_articles_database(_odoo_config_from_streamlit(), data_path)
            st.session_state["app_status_message"] = (
                f"Chargement terminé : {len(refreshed)} articles chargés depuis Odoo."
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Impossible de charger la base articles depuis Odoo : {exc}")

    database_file = None
    if database_source == "Chargement manuel" or not status["exists"]:
        database_file = st.file_uploader("Base de données articles", type=["csv", "xlsx", "xls", "data"])
    invoice_file = st.file_uploader("Facture fournisseur PDF", type=["pdf"])

    st.header("Conditions")
    borne_inf = st.number_input(
        "Écart minimum à la baisse en €",
        value=-0.10,
        step=0.01,
        format="%.2f",
        help="Une baisse de prix est traitée comme un changement seulement en dessous de cette valeur.",
    )
    borne_sup = st.number_input(
        "Écart minimum à la hausse en €",
        value=0.05,
        step=0.01,
        format="%.2f",
        help="Une hausse de prix est traitée comme un changement seulement au-dessus de cette valeur.",
    )
    abnormal_ratio = st.number_input(
        "Ratio Écart/Prix actuel anormal",
        min_value=0.0,
        value=0.30,
        step=0.05,
        format="%.2f",
        help="Les lignes au-dessus de ce ratio absolu sont isolées pour revue manuelle.",
    )
    analysis_disabled = not invoice_file or (
        (database_source == "Chargement manuel" or not status["exists"]) and database_file is None
    )
    current_analysis_signature = _analysis_signature(
        invoice_file,
        database_file,
        supplier_id,
        database_source,
        data_path,
        status,
        borne_inf,
        borne_sup,
        abnormal_ratio,
    )
    if st.session_state.get("analysis_signature") != current_analysis_signature:
        st.session_state["analysis_started"] = False
        st.session_state["analysis_signature"] = current_analysis_signature
        st.session_state.pop("odoo_update_summary", None)

    launch_analysis = st.button(
        "Lancer l'analyse",
        type="primary",
        disabled=analysis_disabled,
    )
    if launch_analysis:
        st.session_state["analysis_started"] = True
        st.session_state.pop("odoo_update_summary", None)


if not invoice_file:
    if not status["exists"] and database_file is None:
        st.info("Rafraichissez d'abord la base depuis Odoo ou chargez une base articles, puis ajoutez une facture PDF.")
    else:
        st.info("Téléchargez la facture à traiter.")
    st.stop()

if not st.session_state.get("analysis_started", False):
    st.info("Choisissez la facture, la base articles et le fournisseur, puis cliquez sur Lancer l'analyse.")
    st.stop()

_validate_invoice_supplier(invoice_file, supplier_id)

try:
    if database_source == "Base locale actuelle" and status["exists"]:
        with data_path.open("rb") as handle:
            products = load_product_database(handle)
    elif database_file:
        products = load_product_database(database_file)
    else:
        st.info("Choisissez une source de base articles avant de lancer l'analyse.")
        st.stop()
except Exception as exc:
    st.error(f"Impossible de lire la base articles : {exc}")
    st.stop()

parser = get_parser(supplier_id)

try:
    invoice = parser.parse(invoice_file)
except Exception as exc:
    st.error(f"Could not parse invoice with parser '{supplier_id}': {exc}")
    st.stop()

config = MatchConfig(
    supplier_code=parser.supplier_code,
    borne_inf=borne_inf,
    borne_sup=borne_sup,
    abnormal_ratio=abnormal_ratio,
    allow_description_fallback=True,
)
result = compare_invoice_to_database(products, invoice.lines, config)
invoice_stem = _invoice_stem(invoice_file)
changed = result[result["PU_Modif"]].copy()
odoo_update_rows = prepare_odoo_update_rows(changed)

summary_cols = st.columns(7)
summary_cols[0].metric("Invoice lines", len(invoice.lines))
summary_cols[1].metric("Matched", int(result["Match_Fact_DB"].sum()))
summary_cols[2].metric("Price changes", int(result["PU_Modif"].sum()))
summary_cols[3].metric("Odoo changes", len(odoo_update_rows))
summary_cols[4].metric("Unmatched", int((~result["Match_Fact_DB"]).sum()))
summary_cols[5].metric("Abnormal", int(result["Ecart_Prix_Anormal"].sum()))
summary_cols[6].metric("Blocked", int(result["Blocage_Modif"].sum()))

st.subheader("Invoice Metadata")
metadata_df = pd.DataFrame(
    [{"field": key, "value": value} for key, value in invoice.metadata.items()]
)
st.dataframe(metadata_df, use_container_width=True, hide_index=True)

unmatched = result[~result["Match_Fact_DB"]].copy()
abnormal = result[result["Ecart_Prix_Anormal"]].copy()
blocked = result[result["Blocage_Modif"]].copy()
workbook_sheets = {
    "price_changes": changed,
    "odoo_update_review": odoo_update_rows,
    "unmatched": unmatched,
    "abnormal_changes": abnormal,
    "blocked_or_manual_review": blocked,
    "all_checked": result,
}

st.download_button(
    "Download complete review workbook",
    data=_download_workbook(workbook_sheets),
    file_name=f"{invoice_stem}_price_review.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

tab_all, tab_changed, tab_update, tab_unmatched, tab_abnormal, tab_blocked = st.tabs(
    [
        "All invoice lines",
        "Changed prices",
        "Odoo update",
        "Unmatched",
        "Abnormal",
        "Blocked / manual review",
    ]
)

with tab_all:
    st.dataframe(result, use_container_width=True, hide_index=True)

with tab_changed:
    if changed.empty:
        st.success("No price changes found.")
    else:
        st.dataframe(changed, use_container_width=True, hide_index=True)
        col_csv, col_xlsx = st.columns(2)
        col_csv.download_button(
            "Download changed prices CSV",
            data=_download_csv(changed),
            file_name="price_changes.csv",
            mime="text/csv",
        )
        col_xlsx.download_button(
            "Download changed prices Excel",
            data=_download_excel(changed, "price_changes"),
            file_name="price_changes.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


with tab_update:
    st.subheader("Odoo update review")
    if odoo_update_rows.empty:
        st.info("No eligible changed-price rows to update in Odoo.")
    else:
        st.warning("Review these rows carefully before updating Odoo. Only eligible changed prices are listed here.")
        st.dataframe(odoo_update_rows, use_container_width=True, hide_index=True)
        col_csv, col_xlsx = st.columns(2)
        col_csv.download_button(
            "Download Odoo update CSV",
            data=_download_csv(odoo_update_rows),
            file_name="odoo_price_update_review.csv",
            mime="text/csv",
        )
        col_xlsx.download_button(
            "Download Odoo update Excel",
            data=_download_excel(odoo_update_rows, "odoo_update_review"),
            file_name="odoo_price_update_review.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

with tab_unmatched:
    if unmatched.empty:
        st.success("All invoice lines matched a database article.")
    else:
        st.warning("Review unmatched lines before uploading price changes.")
        st.dataframe(unmatched, use_container_width=True, hide_index=True)
        st.download_button(
            "Download unmatched CSV",
            data=_download_csv(unmatched),
            file_name="unmatched_invoice_lines.csv",
            mime="text/csv",
        )

with tab_abnormal:
    if abnormal.empty:
        st.success("No abnormal price changes or manually flagged rows found.")
    else:
        st.warning(
            f"Ces articles notes ont change de plus de {abnormal_ratio:.0%} en prix "
            "ou bien ont d'autres problemes notes dans Raison_du_Blocage."
        )
        st.dataframe(abnormal, use_container_width=True, hide_index=True)
        st.download_button(
            "Download abnormal changes CSV",
            data=_download_csv(abnormal),
            file_name="abnormal_price_changes.csv",
            mime="text/csv",
        )

with tab_blocked:
    if blocked.empty:
        st.success("No blocked or manually flagged rows found.")
    else:
        st.warning("These rows are not applied automatically. Check Raison_du_Blocage before updating Odoo.")
        st.dataframe(blocked, use_container_width=True, hide_index=True)
        st.download_button(
            "Download blocked/manual review CSV",
            data=_download_csv(blocked),
            file_name="blocked_or_manual_review.csv",
            mime="text/csv",
        )

if not changed.empty:
    st.divider()
    _render_odoo_update_controls(odoo_update_rows, invoice_stem)

st.caption(
    "Database upload is intentionally staged: review and download the changed-price file before applying updates."
)
