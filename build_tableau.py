"""Build a portable Tableau workbook with the validated synthetic CSV embedded."""

import csv
import xml.etree.ElementTree as ET
import zipfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).parent


def build():
    source = ROOT / "data" / "appointments_clean.csv"
    if not source.exists():
        raise SystemExit("Run python pipeline.py first.")
    destination = ROOT / "tableau"
    destination.mkdir(exist_ok=True)
    fields = next(csv.reader(source.open()))
    dimensions = {
        "appointment_id",
        "appointment_date",
        "provider",
        "appointment_type",
        "age_group",
        "outcome",
    }
    workbook = ET.Element(
        "workbook",
        {
            "source-platform": "mac",
            "version": "9.0",
            "xmlns:user": "http://www.tableausoftware.com/xml/user",
        },
    )
    ET.SubElement(workbook, "preferences")
    ET.SubElement(workbook, "style-theme", {"name": "clean"})
    datasources = ET.SubElement(workbook, "datasources")
    dsname = "textscan.careflow"
    ds = ET.SubElement(
        datasources,
        "datasource",
        {
            "caption": "Synthetic appointments",
            "inline": "true",
            "name": dsname,
            "version": "9.0",
        },
    )
    connection = ET.SubElement(
        ds,
        "connection",
        {
            "class": "textscan",
            "directory": "Data",
            "filename": source.name,
            "server": "",
            "password": "",
        },
    )
    relation = ET.SubElement(
        connection,
        "relation",
        {
            "name": "appointments_clean#csv",
            "table": "[appointments_clean#csv]",
            "type": "table",
        },
    )
    columns = ET.SubElement(
        relation,
        "columns",
        {
            "character-set": "UTF-8",
            "header": "yes",
            "locale": "en_US",
            "separator": ",",
        },
    )
    definitions = {}
    for i, name in enumerate(fields):
        datatype = (
            "string" if name in dimensions else ("real" if name == "wait_minutes" else "integer")
        )
        ET.SubElement(columns, "column", {"datatype": datatype, "name": name, "ordinal": str(i)})
        definitions[name] = ET.SubElement(
            ds,
            "column",
            {
                "caption": name.replace("_", " ").title(),
                "datatype": datatype,
                "name": f"[{name}]",
                "role": "dimension" if name in dimensions else "measure",
                "type": "nominal" if name in dimensions else "quantitative",
            },
        )
    definitions["no_show"].set("default-format", "p0.00%")
    sheets = ET.SubElement(workbook, "worksheets")
    specs = [
        ("No-show rate by visit type", "appointment_type", "no_show"),
        ("Attended wait by provider", "provider", "wait_minutes"),
        ("No-show rate by age group", "age_group", "no_show"),
    ]
    for title, dim, measure in specs:
        sheet = ET.SubElement(sheets, "worksheet", {"name": title})
        table = ET.SubElement(sheet, "table")
        view = ET.SubElement(table, "view")
        ET.SubElement(
            ET.SubElement(view, "datasources"),
            "datasource",
            {"caption": "Synthetic appointments", "name": dsname},
        )
        deps = ET.SubElement(view, "datasource-dependencies", {"datasource": dsname})
        for field in [dim, measure]:
            deps.append(deepcopy(definitions[field]))
        diminst = f"[none:{dim}:nk]"
        measureinst = f"[avg:{measure}:qk]"
        ET.SubElement(
            deps,
            "column-instance",
            {
                "column": f"[{dim}]",
                "derivation": "None",
                "name": diminst,
                "pivot": "key",
                "type": "nominal",
            },
        )
        ET.SubElement(
            deps,
            "column-instance",
            {
                "column": f"[{measure}]",
                "derivation": "Avg",
                "name": measureinst,
                "pivot": "key",
                "type": "quantitative",
            },
        )
        ET.SubElement(view, "aggregation", {"value": "true"})
        pane = ET.SubElement(ET.SubElement(table, "panes"), "pane")
        ET.SubElement(ET.SubElement(pane, "view"), "breakdown", {"value": "auto"})
        ET.SubElement(pane, "mark", {"class": "Bar"})
        enc = ET.SubElement(pane, "encodings")
        ET.SubElement(enc, "text", {"column": f"[{dsname}].{measureinst}"})
        rule = ET.SubElement(ET.SubElement(pane, "style"), "style-rule", {"element": "mark"})
        ET.SubElement(rule, "format", {"attr": "mark-labels-show", "value": "true"})
        ET.SubElement(rule, "format", {"attr": "mark-color", "value": "#7466a2"})
        ET.SubElement(table, "rows").text = f"[{dsname}].{diminst}"
        ET.SubElement(table, "cols").text = f"[{dsname}].{measureinst}"
    dashboards = ET.SubElement(workbook, "dashboards")
    dashboard = ET.SubElement(dashboards, "dashboard", {"name": "Synthetic operations overview"})
    ET.SubElement(dashboard, "style")
    ET.SubElement(
        dashboard,
        "size",
        {
            "maxheight": "780",
            "maxwidth": "960",
            "minheight": "780",
            "minwidth": "960",
        },
    )
    zones = ET.SubElement(dashboard, "zones")
    ET.SubElement(
        zones,
        "zone",
        {"h": "6500", "id": "4", "type-v2": "title", "w": "96000", "x": "2000", "y": "1000"},
    )
    for i, (title, _, _) in enumerate(specs):
        zone = ET.SubElement(
            zones,
            "zone",
            {
                "h": "27000",
                "id": str(i + 1),
                "name": title,
                "show-title": "true",
                "w": "96000",
                "x": "2000",
                "y": str(9000 + i * 30000),
            },
        )
        zs = ET.SubElement(zone, "zone-style")
        ET.SubElement(zs, "format", {"attr": "border-color", "value": "#dddddd"})
        ET.SubElement(zs, "format", {"attr": "margin", "value": "12"})
    windows = ET.SubElement(workbook, "windows")
    for title, _, _ in specs:
        window = ET.SubElement(windows, "window", {"class": "worksheet", "name": title})
        ET.SubElement(window, "viewpoint", {"value": "fit-width"})
    ET.SubElement(
        windows,
        "window",
        {"class": "dashboard", "name": "Synthetic operations overview"},
    )
    ET.indent(workbook)
    content = ET.tostring(workbook, encoding="utf-8", xml_declaration=True)
    # The unzipped workbook and CSV are useful for inspection and manual reconnection.
    (destination / "CareFlow.twb").write_bytes(content)
    (destination / "Data").mkdir(exist_ok=True)
    (destination / "Data" / source.name).write_bytes(source.read_bytes())
    with zipfile.ZipFile(destination / "CareFlow.twbx", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("CareFlow.twb", content)
        archive.write(source, "Data/" + source.name)
    print(destination / "CareFlow.twbx")


if __name__ == "__main__":
    build()
