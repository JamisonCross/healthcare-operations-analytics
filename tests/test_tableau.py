import csv
import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def test_packaged_workbook_references_only_synthetic_data():
    root = Path(__file__).resolve().parents[1]
    with zipfile.ZipFile(root / "tableau" / "CareFlow.twbx") as archive:
        workbook = ET.fromstring(archive.read("CareFlow.twb"))
        assert len(workbook.findall("worksheets/worksheet")) == 3
        assert len(workbook.findall("dashboards/dashboard")) == 1
        connection = workbook.find("datasources/datasource/connection")
        data_path = connection.attrib["directory"] + "/" + connection.attrib["filename"]
        packaged_data = archive.read(data_path)
        assert packaged_data == (root / "data" / "appointments_clean.csv").read_bytes()
        rows = list(csv.DictReader(io.StringIO(packaged_data.decode())))
        assert len(rows) == 3597
        assert all(r["provider"].startswith("Provider ") for r in rows)
        assert connection.attrib["server"] == "" and connection.attrib["password"] == ""
