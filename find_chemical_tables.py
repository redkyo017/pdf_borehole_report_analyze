import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import pdfplumber

CHEMICAL_KEYWORDS = [
    r'mg/kg',
    r'ppm',
    r'µg/l',
    r'ug/l',
    r'\bbox\b',
    r'\bchemical\b',
    r'\bdetermin',
    r'\bthreshold\b',
    r'\blaboratory\b',
    r'\btc\b',
    r'\bph\b',
    r'\bpah\b',
    r'\btph\b',
    r'\bbtex\b',
]

LIMIT_LABELS = ["inert_limit", "snrhw_limit", "hazardous_limit"]

UNIT_HINTS = {"%", "mg/kg", "mg/l", "ug/l", "µg/l", "units"}
VALUE_CAPTURE_PATTERN = re.compile(r"(<\s*)?-?\d+(?:\.\d+)?|-")


def load_pages(pdf_path: str):
    """
    Extract text and tables for every page once so downstream parsing
    does not reopen the PDF repeatedly.
    """
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            try:
                tables = page.extract_tables()
            except Exception:
                tables = []
            pages.append(
                {
                    "page": idx,
                    "text": text,
                    "tables": tables,
                }
            )
    return pages


def clean_value_token(token: Optional[str]):
    if token is None:
        return None
    raw = token.strip()
    if not raw or raw == "-":
        return None
    operator = None
    if raw.startswith(("<", ">")):
        parts = raw.split(None, 1)
        operator = parts[0]
        raw_value = parts[1] if len(parts) > 1 else ""
    else:
        raw_value = raw
    try:
        value = float(raw_value.replace(",", ""))
    except ValueError:
        value = None
    return {"raw": raw, "operator": operator, "value": value}


def normalize_text_token(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped and stripped != "-" else None


def to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def clean_table_preview(table, max_rows=5):
    rows = []
    for row in table:
        cleaned_row = [str(cell).strip() if cell else "" for cell in row]
        if any(cleaned_row):
            rows.append(cleaned_row)
    if not rows:
        return []

    # drop empty columns
    max_len = max(len(row) for row in rows)
    cols_to_keep = [
        idx for idx in range(max_len) if any(row[idx] if idx < len(row) else "" for row in rows)
    ]
    trimmed = []
    for row in rows[:max_rows]:
        trimmed.append(
            [
                row[idx] if idx < len(row) else ""
                for idx in cols_to_keep
            ]
        )
    return trimmed


def combine_operators(tokens: List[str]) -> List[str]:
    combined = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"<", ">", "<=", ">="} and i + 1 < len(tokens):
            combined.append(f"{token} {tokens[i + 1]}")
            i += 2
        else:
            combined.append(token)
            i += 1
    return combined


def extract_site_info(all_text: str) -> Dict[str, str]:
    def grab(pattern):
        match = re.search(pattern, all_text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    info = {
        "project_title": grab(r"Report Title:\s*(.+)"),
        "site_address": grab(r"Site Address\s+([^\n]+)"),
        "project_reference": grab(r"Project Reference\s*-\s*([^\n]+)"),
        "job_number": grab(r"Job No:\s*([^\n]+)"),
        "report_date": grab(r"Date:\s*([^\n]+)"),
        "client": grab(r"For:\s*([^\n]+)"),
        "site_area": grab(r"Site Area\s*([^\n]+)"),
        "national_grid": grab(r"National Grid[^\n]*\s+([EWN:\s0-9,]+)"),
    }

    return {k: v for k, v in info.items() if v}


def extract_lab_summary(pages):
    for entry in pages:
        if "Analytical Test Report" not in entry["text"]:
            continue
        lines = [line.strip() for line in entry["text"].splitlines() if line.strip()]

        def line_value(label):
            lower = label.lower()
            for line in lines:
                if line.lower().startswith(lower):
                    value = line[len(label) :].strip(" :-")
                    return value if value and value != "-" else None
            return None

        summary = {
            "lab_report_reference": line_value("Analytical Test Report"),
            "project_reference": line_value("Your Project Reference"),
            "order_number": None,
            "samples_received": None,
            "samples_instructed": None,
            "sample_tested_range": None,
            "samples_analysed": None,
            "report_issue": None,
            "report_issued": None,
        }

        sr_line = None
        order_line = line_value("Your Order Number")
        if order_line:
            split_marker = "Samples Received / Instructed:"
            if split_marker in order_line:
                order_part, sr_part = order_line.split(split_marker, 1)
                summary["order_number"] = order_part.strip()
                sr_line = sr_part.strip()
            else:
                summary["order_number"] = order_line.strip()
        if not sr_line:
            sr_line = line_value("Samples Received / Instructed")

        if sr_line and " / " in sr_line:
            received, instructed = [part.strip() for part in sr_line.split(" / ", 1)]
            summary["samples_received"] = received or None
            summary["samples_instructed"] = instructed or None

        issue_line = line_value("Report Issue Number")
        if issue_line:
            parts = issue_line.split(" Sample Tested:", 1)
            summary["report_issue"] = parts[0].strip()
            if len(parts) > 1:
                summary["sample_tested_range"] = parts[1].strip()
        else:
            summary["sample_tested_range"] = line_value("Sample Tested")

        analysed_line = line_value("Samples Analysed")
        if analysed_line:
            parts = analysed_line.split(" Report issued:", 1)
            summary["samples_analysed"] = parts[0].strip()
            if len(parts) > 1:
                summary["report_issued"] = parts[1].strip()
        else:
            summary["report_issued"] = line_value("Report issued")

        return {k: v for k, v in summary.items() if v}

    return {}


def extract_sample_descriptions(pages):
    for entry in pages:
        if "Sample Descriptions" not in entry["text"]:
            continue
        lines = entry["text"].splitlines()
        start_idx = None
        for idx, line in enumerate(lines):
            if "Number (%) (%) sieve (%)" in line:
                start_idx = idx + 1
                break

        if start_idx is None:
            continue

        samples = []
        current = None

        for line in lines[start_idx:]:
            stripped = line.strip()
            if not stripped or stripped.startswith("Page "):
                continue
            if stripped.startswith("Client") or stripped.startswith("Determinant"):
                continue

            if re.match(r"^\d{6}\b", stripped):
                parts = stripped.split(" - ", 2)
                lab_ref = normalize_text_token(parts[0].strip())
                id_block = parts[1].strip() if len(parts) > 1 else ""
                remainder = parts[2].strip() if len(parts) > 2 else ""

                id_tokens = id_block.split()
                sample_id = normalize_text_token(id_tokens[0]) if id_tokens else None
                sample_type = (
                    normalize_text_token(id_tokens[-1]) if len(id_tokens) >= 2 else None
                )
                location = (
                    normalize_text_token(" ".join(id_tokens[1:-1]))
                    if len(id_tokens) > 2
                    else None
                )

                value_matches = list(VALUE_CAPTURE_PATTERN.finditer(remainder))
                if len(value_matches) >= 3:
                    last_three = value_matches[-3:]
                    description = remainder[: last_three[0].start()].strip()
                    moisture = normalize_text_token(last_three[0].group().strip())
                    stone = normalize_text_token(last_three[1].group().strip())
                    sieve = normalize_text_token(last_three[2].group().strip())
                else:
                    description = remainder.strip()
                    moisture = stone = sieve = None

                current = {
                    "lab_reference": lab_ref or None,
                    "sample_id": sample_id,
                    "location": location,
                    "sample_type": sample_type,
                    "description": description or None,
                    "moisture_content_percent": moisture,
                    "stone_content_percent": stone,
                    "passing_2mm_percent": sieve,
                }
                samples.append(current)
            elif current:
                current["description"] = " ".join(
                    filter(None, [current.get("description"), stripped])
                ).strip()

        return samples

    return []


def parse_analysis_line(line: str):
    tokens = line.split()
    unit_idx = None

    for idx, token in enumerate(tokens):
        normalized = token.lower()
        if (
            token in UNIT_HINTS
            or "/" in token
            or "%" in token
            or normalized == "units"
        ):
            unit_idx = idx
            break

    if unit_idx is None or unit_idx == 0 or len(tokens) <= unit_idx + 2:
        return None

    analyte = " ".join(tokens[:unit_idx])
    unit = tokens[unit_idx]
    accreditation = tokens[unit_idx + 1]
    value_tokens = combine_operators(tokens[unit_idx + 2 :])
    if not value_tokens:
        return None

    entry = {
        "analyte": analyte.strip(),
        "unit": unit.strip(),
        "accreditation": accreditation.strip(),
        "result": clean_value_token(value_tokens[0]),
        "limits": {},
        "threshold_flags": {},
    }

    for label, token in zip(LIMIT_LABELS, value_tokens[1:]):
        entry["limits"][label] = clean_value_token(token)

    result_value = entry["result"]["value"] if entry["result"] else None
    result_operator = entry["result"]["operator"] if entry["result"] else None

    for label, limit in entry["limits"].items():
        if (
            result_value is not None
            and limit
            and limit["value"] is not None
            and result_operator != "<"
        ):
            entry["threshold_flags"][label] = result_value > limit["value"]
        else:
            entry["threshold_flags"][label] = None

    return entry


def extract_certificates(pages):
    certificates = []
    for entry in pages:
        if "Certificate Of Analysis" not in entry["text"]:
            continue

        lines = [line.strip() for line in entry["text"].splitlines() if line.strip()]

        def get_value(label):
            lower = label.lower()
            for line in lines:
                if line.lower().startswith(lower):
                    value = line[len(label) :].strip(" :-")
                    return value if value and value != "-" else None
            return None

        certificate = {
            "page": entry["page"],
            "lab_reference": get_value("Lab Reference"),
            "client_sample_id": get_value("Client Sample ID"),
            "client_sample_location": get_value("Client Sample Location"),
            "client_sample_type": get_value("Client Sample Type"),
            "client_sample_number": get_value("Client Sample Number"),
            "depth_top_m": to_float(get_value("Depth - Top (m)")),
            "depth_bottom_m": to_float(get_value("Depth - Bottom (m)")),
            "date_of_sampling": get_value("Date of Sampling"),
            "time_of_sampling": get_value("Time of Sampling"),
            "sample_description": get_value("Sample Description"),
            "sample_matrix": get_value("Sample Matrix"),
            "moisture_content_percent": to_float(get_value("Moisture Content (%)")),
            "stone_content_percent": to_float(get_value("Stone content (%)")),
            "solid_analysis": [],
            "eluate_analysis": [],
        }

        section = None
        for line in lines:
            normalized = line.lower()
            if normalized.startswith("solid analysis"):
                section = "solid_analysis"
                continue
            if normalized.startswith("eluate analysis"):
                section = "eluate_analysis"
                continue
            if normalized.startswith("page "):
                continue

            if section in ("solid_analysis", "eluate_analysis"):
                parsed = parse_analysis_line(line)
                if parsed:
                    certificate[section].append(parsed)

        certificates.append(certificate)

    return certificates


def summarize_chemical_pages(pages):
    indicators = re.compile("|".join(CHEMICAL_KEYWORDS), re.IGNORECASE)
    highlights = []

    for entry in pages:
        text = entry["text"]
        if not text:
            continue
        matches = indicators.findall(text)
        if not matches:
            continue
        table_count = len(entry["tables"])
        if not table_count:
            continue

        table_previews = [
            clean_table_preview(table) for table in entry["tables"][:2]
        ]

        highlights.append(
            {
                "page": entry["page"],
                "keyword_matches": len(matches),
                "table_count": table_count,
                "preview": text[:400],
                "tables_preview": table_previews,
            }
        )

    return highlights


def find_chemical_data_pages(pdf_path):
    """
    Build a structured summary of the report so downstream systems can
    plan a data model (site info, lab certificates, chemical tables, etc.).
    """
    pages = load_pages(pdf_path)
    combined_text = "\n".join(page["text"] for page in pages if page["text"])

    data = {
        "filename": Path(pdf_path).name,
        "pages": len(pages),
        "site_information": extract_site_info(combined_text),
        "lab_report_summary": extract_lab_summary(pages),
        "sample_descriptions": extract_sample_descriptions(pages),
        "certificates": extract_certificates(pages),
        "chemical_table_pages": summarize_chemical_pages(pages),
    }

    return data


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python find_chemical_tables.py <pdf_path> [output_json]")
        sys.exit(1)

    pdf_arg = Path(sys.argv[1])
    output_path = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else pdf_arg.with_name(f"{pdf_arg.stem}_chemical_summary.json")
    )

    result = find_chemical_data_pages(str(pdf_arg))
    with open(output_path, "w") as fh:
        json.dump(result, fh, indent=2)

    print(json.dumps(result, indent=2))
    print(f"\nWrote structured chemical summary to {output_path}")
