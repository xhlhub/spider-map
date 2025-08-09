import io
import json
from typing import List, Dict, Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from gmaps_scraper import scrape_maps

app = FastAPI(title="SpiderMap - Google Maps Scraper")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request},
    )


@app.post("/scrape", response_class=HTMLResponse)
def scrape(
    request: Request,
    region: str = Form(...),
    category: str = Form(...),
    max_results: int = Form(50),
):
    rows = scrape_maps(region, category, max_results=max_results, headless=True)
    rows_json = json.dumps(rows, ensure_ascii=False)
    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "region": region,
            "category": category,
            "max_results": max_results,
            "rows": rows,
            "rows_json": rows_json,
        },
    )


def build_excel(rows: List[Dict[str, Optional[str]]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    headers = [
        "name",
        "address",
        "phone",
        "website",
        "category",
        "rating",
        "reviews_count",
        "latitude",
        "longitude",
        "gmaps_url",
    ]
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h, "") or "" for h in headers])
    data = io.BytesIO()
    wb.save(data)
    data.seek(0)
    return data.read()


@app.post("/download-excel")
def download_excel(rows_json: str = Form(...)):
    rows = json.loads(rows_json)
    content = build_excel(rows)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=results.xlsx",
        },
    )


@app.post("/download-csv")
def download_csv(rows_json: str = Form(...)):
    import csv

    rows = json.loads(rows_json)
    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        "name",
        "address",
        "phone",
        "website",
        "category",
        "rating",
        "reviews_count",
        "latitude",
        "longitude",
        "gmaps_url",
    ]
    writer.writerow(headers)
    for r in rows:
        writer.writerow([r.get(h, "") or "" for h in headers])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=results.csv",
        },
    )

