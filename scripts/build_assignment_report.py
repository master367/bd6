"""Build the assignment report using captured local Compass screenshots and actual test data.

Run with the bundled document runtime Python, not the backend virtual environment.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "output" / "report"
ASSETS = WORK / "assets"
CROPS = WORK / "crops"
DEST = ROOT / "output" / "doc" / "Assignment_6_Zhalgasov_Adilbek_CSE-2602M.docx"
local = json.loads((WORK / "local-benchmark.json").read_text(encoding="utf-8"))
container = json.loads((ROOT / "output/docker/benchmark.json").read_text(encoding="utf-8"))
api = json.loads((WORK / "local-api-responses.json").read_text(encoding="utf-8"))

doc = Document()
section = doc.sections[0]
section.page_width, section.page_height = Cm(21), Cm(29.7)
section.top_margin, section.bottom_margin = Cm(1.8), Cm(1.8)
section.left_margin, section.right_margin = Cm(2), Cm(2)
section.footer_distance = Cm(0.7)
WIDTH = 6.69


def font(style, size, bold=False):
    style.font.name = "Times New Roman"
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor(0, 0, 0)
    for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:" + attr), "Times New Roman")


font(doc.styles["Normal"], 12)
normal = doc.styles["Normal"].paragraph_format
normal.line_spacing = 1.15
normal.space_after = Pt(6)
normal.widow_control = True
for name, size in (("Title", 17), ("Subtitle", 12), ("Heading 1", 14), ("Heading 2", 12)):
    font(doc.styles[name], size, name != "Subtitle")
    pf = doc.styles[name].paragraph_format
    pf.space_before, pf.space_after = Pt(7), Pt(8)
    pf.keep_with_next = True
    pf.line_spacing = 1.05
font(doc.styles["Caption"], 10.5)
doc.styles["Caption"].paragraph_format.space_after = Pt(8)
doc.styles["Caption"].paragraph_format.line_spacing = 1.05
doc.styles["Caption"].font.italic = True

footer = section.footer.paragraphs[0]
footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
field = OxmlElement("w:fldSimple")
field.set(qn("w:instr"), "PAGE")
footer._p.append(field)
footer.paragraph_format.space_after = Pt(0)
doc.core_properties.author = "Zhalgasov Adilbek"
doc.core_properties.title = "Assignment 6 Report Edge Drowsiness Model Catalog"
doc.core_properties.subject = "Advanced Databases CSE-2602M"
doc.core_properties.keywords = "MongoDB, NoSQL, FastAPI, recommendation platform, edge analysis"
doc.core_properties.created = datetime.now(UTC)
doc.core_properties.modified = datetime.now(UTC)


def p(text, *, bold=False, size=None, align=None):
    paragraph = doc.add_paragraph()
    paragraph.alignment = align or WD_ALIGN_PARAGRAPH.JUSTIFY
    run = paragraph.add_run(text)
    run.bold = bold
    if size:
        run.font.size = Pt(size)
    return paragraph


def h(text, level=1):
    return doc.add_heading(text, level=level)


def new_page(title):
    doc.add_page_break()
    h(title)


def code(text):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.line_spacing = 1.0
    paragraph.paragraph_format.space_after = Pt(8)
    paragraph.paragraph_format.keep_together = True
    paragraph.paragraph_format.left_indent = Cm(0.25)
    run = paragraph.add_run(text)
    run.font.name, run.font.size = "Consolas", Pt(9)
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:ascii"), "Consolas")
    run._element.rPr.rFonts.set(qn("w:hAnsi"), "Consolas")
    return paragraph


def table(headers, rows, widths, size=10.5):
    t = doc.add_table(rows=1, cols=len(headers))
    t.autofit = False
    for col, width in zip(t.columns, widths, strict=True):
        col.width = Inches(width)
    for i, value in enumerate(headers):
        t.rows[0].cells[i].text = str(value)
    header_repeat = OxmlElement("w:tblHeader")
    t.rows[0]._tr.get_or_add_trPr().append(header_repeat)
    for row in rows:
        cells = t.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = str(value)
    for r_index, row in enumerate(t.rows):
        no_split = OxmlElement("w:cantSplit")
        row._tr.get_or_add_trPr().append(no_split)
        for i, cell in enumerate(row.cells):
            cell.width = Inches(widths[i])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            props = cell._tc.get_or_add_tcPr()
            borders = OxmlElement("w:tcBorders")
            for side in ("top", "left", "bottom", "right"):
                border = OxmlElement("w:" + side)
                for key, value in (("val", "single"), ("sz", "4"), ("color", "D9D9D9")):
                    border.set(qn("w:" + key), value)
                borders.append(border)
            props.append(borders)
            margins = OxmlElement("w:tcMar")
            for side, amount in (("top", "65"), ("bottom", "65"), ("left", "85"), ("right", "85")):
                node = OxmlElement("w:" + side)
                node.set(qn("w:w"), amount)
                node.set(qn("w:type"), "dxa")
                margins.append(node)
            props.append(margins)
            shade = OxmlElement("w:shd")
            shade.set(qn("w:fill"), "E7EEF6" if r_index == 0 else ("F7F9FB" if r_index % 2 == 0 else "FFFFFF"))
            props.append(shade)
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = 1.05
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                for run in paragraph.runs:
                    run.font.size = Pt(size)
                    run.font.bold = r_index == 0
                    run.font.color.rgb = RGBColor(0, 0, 0)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


figure_number = 0


def figure(filename, crop, caption, width=WIDTH):
    global figure_number
    figure_number += 1
    CROPS.mkdir(parents=True, exist_ok=True)
    image_path = CROPS / (Path(filename).stem + ".png")
    with Image.open(ASSETS / filename) as source:
        source.crop(crop).save(image_path)
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.keep_with_next = True
    paragraph.paragraph_format.space_after = Pt(4)
    shape = paragraph.add_run().add_picture(str(image_path), width=Inches(width))
    shape._inline.docPr.set("descr", caption)
    cap = doc.add_paragraph(f"Figure {figure_number}  {caption}", style="Caption")
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER


# Page 1
doc.add_paragraph("Assignment 6 Report", style="Title")
doc.add_paragraph(
    "Designing the data layer and backend for a NoSQL recommendation platform", style="Subtitle"
)
p("Zhalgasov Adilbek    CSE-2602M", bold=True, align=WD_ALIGN_PARAGRAPH.LEFT)
p("Advanced Databases    11 November 2026", size=11, align=WD_ALIGN_PARAGRAPH.LEFT)
h("1 Goals and project scope")
p("The project implements Edge Drowsiness Model Catalog, a NoSQL platform for selecting versions of drowsiness detection models under edge device constraints. The completed backend provides user profiles, a model catalog, search, interaction history, analytics and an initial recommendation mechanism. Local and Docker executions were verified against real MongoDB servers.")
p("The assignment goals are to apply NoSQL storage principles, design documents around common queries, and implement a working backend and API [1]. The design therefore starts with three entities: researchers who make choices, model versions that can be selected, and timestamped actions connecting them. The database is the main technical focus of the work.")
table(["Component", "Implementation"], [
    ("Database", "MongoDB with three application collections"),
    ("Backend", "Python 3.12, FastAPI and PyMongo"),
    ("Authentication", "Argon2id password hashing and 30 minute JWT access tokens"),
    ("Demonstration", "HTTP API, Swagger UI and a Python CLI"),
    ("Execution", "Local Windows setup and a Docker Compose stack"),
], [1.45, 5.24])
h("Objectives", 2)
p("The implementation covers registration and login, profile management, catalog CRUD, recording of views and ratings, filtered search, test data generation and documentation. Database objectives include collection validation, unique and compound indexes, stable history pagination, aggregation pipelines and measurement of query execution plans.")
p("The catalog contains synthetic demonstration entries. No detection model was trained, and the stored F1, memory and latency values are simulated. They demonstrate database operations and selection rules; they do not establish the effectiveness of a real detector. The current application organizes and recommends methods rather than analysing sensor streams in real time.")

# Page 2
new_page("2 Relevance to the dissertation")
p("The dissertation topic is Intelligent methods of edge time series analysis for drowsiness detection. The platform supports the comparison and selection stage of this research by maintaining structured information about candidate methods, their versions, input signals and resource requirements. A searchable catalog can help organize methods before they are implemented and evaluated on a target device.")
p("Edge deployment places explicit constraints on model selection. A method may accept the available signal while requiring more memory or processing time than a device can provide. The database stores a user device profile containing the signal, memory budget, latency threshold and reference device. These fields make compatibility criteria explicit and allow reproducible filtering of the candidate methods.")
p("Model quality also requires experimental context. Each catalog entry contains the evaluation dataset and protocol alongside the F1 score. Resource characteristics include a reference device identifier. This structure keeps the description of a result together with its conditions. In subsequent dissertation experiments, preprocessing, window length, participant splitting, hardware and runtime must also be controlled before quality or latency values are compared.")
p("The interaction collection records how researchers use the catalog. Views, saves, selections and ratings provide preference signals that may later support personalization. A stored event identifies both the user and the chosen model version, includes a timestamp, and preserves a small model snapshot. The resulting history can be inspected without changing its historical meaning when a catalog name is edited.")
p("The current synthetic dataset supports verification of schema constraints, query plans, API behaviour and recommendation logic. It cannot support claims about actual drowsiness detection accuracy or real user satisfaction. As research experiments become available, measured records can be added with their dataset, protocol and device context. The platform can then support comparison tables and explain why a method was considered compatible with a particular deployment scenario.")
p("The implemented constraint based selector provides a transparent baseline for this future research. A more advanced content based ranker can be evaluated against the same eligibility rules. This gives the dissertation a clear separation between storing experimental evidence, selecting feasible models and assessing whether personalized ranking improves the usefulness of the catalog.")
h("Expected research use", 2)
p("The platform can serve as a registry of model versions and evaluation settings, a reproducible way to query deployment constraints, and a source of interaction data for recommendation experiments. Its present results concern database correctness and query efficiency. Detector training and validation on real participant data remain separate research work.")

# Page 3
new_page("3 NoSQL choice and data modeling")
p("MongoDB was selected because model metadata forms natural documents with nested attributes and bounded arrays. The workload combines catalog filtering, chronological user histories and grouped analytics. MongoDB provides document validation, indexes and aggregation pipelines for these operations [2, 3].")
table(["NoSQL model", "Fit for the workload", "Main trade off"], [
    ("Document model", "Nested model metadata, filters and event analytics", "The application manages references between collections"),
    ("Key value model", "Direct access by key and possible future caching", "Catalog search and analytical access patterns need additional design"),
    ("Graph model", "Potential future traversal of user and model relationships", "Current queries mainly filter documents and time ranges"),
], [1.25, 2.65, 2.79])
p("Only MongoDB is used in the implemented storage layer. Adding another database would require an additional consistency and deployment strategy without a required workload in this version. The comparison above describes the fit of the data models rather than claiming that another database cannot implement these functions.")
table(["Collection", "Document responsibility", "Relationship"], [
    ("users", "Identity, role and bounded device profile", "One user has many interaction events"),
    ("models", "One catalog model version and its characteristics", "One model receives many interaction events"),
    ("interactions", "One timestamped user action", "References one user and one model"),
], [1.05, 2.85, 2.79])
p("Device settings are embedded in users because they are small and normally read with the profile. Resource requirements and evaluation context are embedded in models for the same reason. These fields can be read in a single document operation.")
p("Interaction history is stored separately because it grows continuously and connects many users with many models. Embedding the entire history in a user would create an expanding array, larger updates and less convenient independent indexes. Each event instead contains references and a bounded name, slug and version snapshot. This deliberate duplication supports historical display without joining the catalog on every history request.")
p("Dates are BSON Date values stored in UTC; references are BSON ObjectId values. The API converts identifiers to hexadecimal strings and dates to ISO 8601 for JSON responses. The model therefore preserves database types while providing a simple client contract.")

# Page 4
new_page("4 Local setup and database creation")
p("The screenshots in this report were captured from MongoDB Compass connected to the local database. The local server runs MongoDB 8.3.11 at 127.0.0.1:27017. The local FastAPI application runs at http://127.0.0.1:8000. The Docker stack uses separate host ports 27018 and 8001, avoiding a conflict with this local setup.")
code("python -m app.manage init-db\npython -m app.manage seed --users 100 --models 60 --interactions 100000\npython -m uvicorn app.main:app --host 127.0.0.1 --port 8000")
p("Initialization creates the three collections with strict validators and their indexes. Repeating initialization updates the collection configuration and ensures the named indexes exist. Seeding uses deterministic identifiers and setOnInsert operations, so the same parameters do not erase records or duplicate the generated events.")
figure("01-collections.jpg", (280, 100, 1000, 290), "Local edge_catalog collections displayed in MongoDB Compass")
table(["Collection", "Current document count", "Indexes including the default index"], [
    ("users", "100", "2"), ("models", "60", "6"), ("interactions", "100 001", "5"),
], [1.4, 2.3, 2.99])
p("The generator created 100 000 events. An earlier CLI demonstration added one actual demonstration view, producing the current count of 100 001. Compass abbreviates this large count as 100K in some views; the full count is visible when reading the collection. These counts refer to the local dataset used for the screenshots.")
p("Secrets are read from the local environment file, which is excluded from version control. Random demo credentials are kept in a separate ignored file for demonstration. Public registration always creates an ordinary user; administrative accounts are created by the management command or the demonstration generator.")

# Page 5
new_page("5 Catalog documents and model versions")
p("A catalog item represents one version of a candidate detection model. Its identity is the pair of slug and version, protected by a unique index. Other fields include name, description, category, supported signals, tags, resource requirements and evaluation context. A new version is a separate item, allowing user choices to refer to a specific version.")
figure("03-model-requirements.jpg", (417, 365, 1195, 729), "A model document with its embedded resource requirements expanded")
p("The displayed EEG example requires 88.31 MB of memory and has a simulated latency of 34.42 ms on synthetic-edge-v1. These are demonstration values, not measured results. The synthetic flag is visible in the same document and the description identifies the record as simulated.")
table(["Field group", "Meaning"], [
    ("category and signals", "Method category and accepted signal types"),
    ("requirements", "Memory in MB, latency in ms and reference device"),
    ("evaluation", "F1 in the interval 0 to 1, dataset and evaluation protocol"),
    ("active and timestamps", "Catalog visibility, creation time and last update"),
], [1.8, 4.89])
p("Administrators create and update catalog entries through the API. Deletion sets active to false, removing the item from search and recommendations while preserving its identity for existing history records. New interactions require an active model. Historical snapshots remain unchanged when the catalog description is edited.")

# Page 6
new_page("6 Users authentication and profiles")
p("User documents contain a normalized email, display name, role, password hash and device profile. Email is converted to lowercase before storage and a unique index prevents duplicate canonical addresses. Passwords are hashed with Argon2id. The API never returns the password hash, and registration rejects a client supplied role.")
figure("08-user-profile.jpg", (415, 520, 1270, 780), "An embedded device profile shown with password_hash excluded by the query projection")
p("The profile in the screenshot specifies EEG input, a memory budget of 128 MB and a latency threshold of 100 ms on synthetic-edge-v1. The projection used for this capture was {password_hash: 0}; only display fields and the device constraints are shown.")
table(["Operation", "Access and behaviour"], [
    ("Register and log in", "Public endpoints; duplicate email is rejected"),
    ("Read or replace profile", "Authenticated user; only their own profile"),
    ("Change catalog records", "Administrator permission required"),
    ("Activity summary", "Administrator permission required"),
], [2.1, 4.59])
p("Login accepts an email and password and returns a bearer JWT valid for 30 minutes. The server validates the signature, expiration, issuer, audience and permitted signing algorithm. It reads the current role from MongoDB on each authenticated request. Invalid credentials or a missing or expired token return 401; an authenticated user without the required role receives 403 [6].")
p("Profile replacement updates the display name and device settings. Clearing the device profile is allowed, but recommendations then return a message requiring the profile to be configured. This makes the eligibility criteria explicit instead of silently using arbitrary device defaults.")

# Page 7
new_page("7 Interaction history and safe retries")
p("Each interaction is an append only event containing user_id, model_id, type, rating, request_id, model_snapshot and created_at. The server assigns the user from the authenticated identity and creates the timestamp. A caller cannot record an event on behalf of another user by supplying a different identifier.")
figure("06-interactions.jpg", (415, 347, 1260, 765), "Timestamped interaction documents with user and model references")
table(["Event type", "Stored meaning", "Rating value"], [
    ("view", "The user viewed an item", "null"),
    ("save", "The user saved an item", "null"),
    ("select", "The user selected a candidate", "null"),
    ("rating", "The user submitted an evaluation", "Integer from 1 to 5"),
], [1.05, 3.8, 1.84])
p("The compound unique key user_id plus request_id protects against duplicate insertion. An identical retry returns the original event with status 200. Reusing the same key with a different payload returns 409. The database enforces uniqueness even when concurrent requests arrive before the application sees the earlier insert.")
p("History is sorted by created_at and then _id, both descending. A cursor preserves both values so equal timestamps do not cause skipped records. The authenticated user filter is always applied, including when a client supplies a cursor. Archived catalog items remain readable through their stored history snapshots.")

# Page 8
new_page("8 Validation inside MongoDB")
p("Request validation in FastAPI is complemented by collection level JSON Schema validation. This protects the storage contract even when a direct database write bypasses the HTTP API. Validators require the expected fields, check BSON types and ranges, and reject additional fields [3].")
figure("05-validation.jpg", (395, 295, 1050, 760), "The model collection JSON Schema with required fields and BSON type constraints")
p("All three collections use strict validation with the error action. Model F1 values must remain between 0 and 1; resource values must be positive within the allowed bounds. Signal and category fields use defined enumerations, and bounded arrays reject duplicate values.")
p("Interaction validation also checks a condition across fields: rating events require an integer from 1 to 5, while view, save and select events require a null rating. Integration tests attempted invalid direct writes and observed MongoDB error code 121. Unique email, model version and idempotency constraints are enforced by indexes rather than by schema validation alone.")

# Page 9
new_page("9 Indexes designed around queries")
p("Ten application indexes supplement the three automatic _id indexes. Indexes are selected for actual filters, sort orders and uniqueness rules. Their storage and write cost is a reason to avoid indexing every field indiscriminately [7].")
table(["Collection", "Index", "Query or invariant"], [
    ("users", "unique_email", "Exact email login and uniqueness"),
    ("models", "unique_slug_version", "Unique catalog version"),
    ("models", "catalog_recent", "Active catalog ordered by time and _id"),
    ("models", "category_recent", "Category filter with recent order"),
    ("models", "signal_device_memory", "Signal, reference device and memory bound"),
    ("models", "catalog_text", "Word search in name, description and tags"),
    ("interactions", "user_recent", "Recent actions for one user"),
    ("interactions", "model_type_time", "Model events by type and period"),
    ("interactions", "unique_user_request", "Idempotency under concurrent retries"),
    ("interactions", "analytics_time", "Activity over a selected period"),
], [0.95, 2.05, 3.69], size=10)
figure("07-history-index.jpg", (378, 300, 1450, 780), "The history indexes with user_recent expanded to show its field order", width=6.25)
p("The history index is ordered as user_id ascending, created_at descending, _id descending. Equality on the first field identifies the user's records; the remaining fields provide the required order and deterministic tie breaker. Resource filtering can still require residual checks and sorting, so other filter combinations must be assessed with their own explain plans.")

# Page 10
new_page("10 Backend and API contract")
p("The backend exposes 17 operations on 13 OpenAPI paths. Synchronous endpoint functions use PyMongo for database calls. Swagger UI is available at /docs and the machine readable contract at /openapi.json. The following groups cover the assignment's API requirements.")
table(["Method", "Path", "Purpose"], [
    ("GET", "/health", "Verify database connectivity"),
    ("POST", "/auth/register", "Create an ordinary user"),
    ("POST", "/auth/token", "Authenticate and issue a token"),
    ("GET PUT", "/users/me", "Read or replace own profile"),
    ("GET POST", "/models", "Search or create catalog items"),
    ("GET PUT DELETE", "/models/{id}", "Read, update or archive an item"),
    ("GET", "/models/{id}/stats", "Event counts for an item"),
    ("POST", "/interactions", "Record an event safely"),
    ("GET", "/users/me/history", "Read private event history"),
    ("GET", "/recommendations", "Apply device constraints"),
    ("GET", "/analytics/popular", "Rank models by event counts"),
    ("GET", "/analytics/ratings", "Average latest user ratings"),
    ("GET", "/analytics/summary", "Activity by type and UTC date"),
], [1.15, 2.35, 3.19])
p("Registration and model editing accept JSON. Login uses form encoded username and password fields; username contains the email. The resulting token is sent in the Authorization header. Catalog modification and the activity summary require an administrator role; ordinary users can manage their own profile and interactions.")
code('POST /interactions\nAuthorization: Bearer <access token>\n{"model_id":"<24 character ObjectId>","type":"rating",\n "rating":4,"request_id":"<UUID reused for retries>"}')
p("The server returns 201 for a new record, 200 for a matching interaction retry and 204 after archival. Other documented outcomes include 404 for an unavailable active item, 409 for a duplicate or conflicting key, 422 for invalid input and 503 when a database operation is unavailable. Errors do not expose database connection strings.")

# Page 11
new_page("11 Search and recommendation approach")
p("Catalog search combines an active item condition with optional category, signal, memory, latency and reference device filters. The q parameter uses a MongoDB text index over name, description and tags. This is word based search with English stemming, rather than substring or fuzzy matching.")
figure("04-model-indexes.jpg", (380, 309, 1370, 790), "Catalog indexes including the compound resource index and the text search index", width=6.2)
code("GET /models?signal=eeg&max_memory_mb=128&limit=10\nGET /recommendations?limit=3")
p("The implemented recommendation baseline retains active items matching the profile's signal and exact reference device. Memory and latency must be within the user's bounds. Eligible items are ordered by lower latency, then lower memory use, with _id resolving ties. This is deterministic compatibility filtering rather than a learned recommender.")
recs = api["/recommendations?limit=3"]["items"]
table(["Returned EEG item", "Memory MB", "Latency ms"], [
    (item["name"], item["requirements"]["memory_mb"], item["requirements"]["latency_ms"])
    for item in recs
], [3.8, 1.45, 1.44])
p("For the Final Project, the planned content based ranker will first apply these hard constraints, then rank compatible candidates using normalized item features and explicit preference weights from saved, selected and rated items. Quality scores will be compared only within compatible evaluation settings. New users will retain the transparent baseline until enough preference information exists.")

# Page 12
new_page("12 Aggregation and analytical results")
p("Analytical calculations are performed in MongoDB pipelines. Popularity groups events by model, joins the current catalog and excludes archived items. Ratings first select the latest rating for each user and model pair, then average those values. Repeated ratings therefore do not give one person multiple votes [5].")
code('[\n  {"$group":{"_id":"$type","events":{"$sum":1}}},\n  {"$sort":{"events":-1}}\n]')
figure("09-aggregation-results.jpg", (414, 369, 930, 705), "Complete Compass aggregation results grouped by interaction type", width=4.8)
p("The aggregation was executed with Run against the complete local collection, producing four result documents. Counts were 64 959 views, 14 961 saves, 10 114 selections and 9 967 ratings. Their sum is 100 001, matching the collection count. These figures describe the demonstration workload, not behaviour observed from real research participants.")
p("The backend also uses a facet pipeline to report activity by event type and UTC day. Historical events remain the source of these computations; the application does not maintain separate counters on every write. This avoids coordinating several updates for each event. At a much larger workload, an explicitly maintained representation of latest ratings could be evaluated as a separate optimization.")

# Page 13
new_page("13 Functional testing and Docker verification")
p("All 18 automated tests passed in the local environment and again inside Docker. The integration tests use real MongoDB, create randomly named temporary test databases, and remove only those databases afterwards. The application database is retained. The local rerun for this report completed in 4.96 seconds; the Docker test run completed in 4.28 seconds.")
table(["Test area", "Verified result"], [
    ("Authentication", "Token signature, expiry and signing algorithm are enforced"),
    ("Roles and privacy", "Ordinary users cannot edit the catalog or read another user's history"),
    ("Database constraints", "Duplicate keys and invalid direct writes are rejected"),
    ("Concurrent retry", "Eight identical concurrent requests create one event"),
    ("History", "Equal timestamps paginate correctly; archival preserves snapshots"),
    ("Search and analytics", "Text filters, device constraints and latest rating averages are correct"),
    ("Seed and query plans", "Repeated seed keeps counts; indexed and scan results match"),
], [1.5, 5.19])
p("The single warning emitted by the test runner concerns a future Starlette test client dependency change; it is not a failed test. The code check with Ruff also completed successfully. Real HTTP calls verified the local /health response and the API responses used for profile, catalog and analytics examples.")
table(["Environment", "MongoDB", "API address", "Test result"], [
    ("Local", "8.3.11", "127.0.0.1:8000", "18 passed"),
    ("Docker", "8.0.34", "127.0.0.1:8001", "18 passed"),
], [1.2, 1.2, 2.55, 1.74])
p("Docker Compose runs the API and MongoDB in separate containers. The CLI completed a real HTTP demonstration: it logged in, read the catalog, recorded one view and requested history, recommendations and analytics. The MongoDB and API containers were restarted, after which counts remained 100 users, 60 models and 100 001 events. MongoDB data resides in the named volume bd6_mongo_data.")
code("docker compose up -d --build --wait\ndocker compose run --rm tests\ndocker compose exec api python -m app.cli demo")
p("The evidence files include JUnit results, API responses, index definitions, benchmark statistics and the persistence comparison. The screenshots were taken from the local Compass instance. Local and Docker measurements are reported as separate runs.")

# Page 14
new_page("14 Query execution experiment")
p("The measured workload requests the latest 20 actions for one user, ordered by created_at and _id. Five executions used a natural scan hint and five used user_recent. The management script compared all returned identifiers and confirmed identical results. Indexes were not dropped during the experiment [4].")
figure("10-explain-plan.jpg", (380, 270, 1455, 750), "Compass explain plan for the equivalent latest actions aggregation using user_recent")
table(["Local metric", "Natural scan", "Index user_recent"], [
    ("Documents returned", "20", "20"),
    ("Documents examined each run", "100 001", "20"),
    ("Index keys examined each run", "0", "20"),
    ("Median executionTimeMillis", str(local["results"]["natural_scan"]["median_execution_ms"]), str(local["results"]["indexed"]["median_execution_ms"])),
    ("Plan stages", "COLLSCAN and SORT", "IXSCAN FETCH LIMIT"),
], [2.95, 1.8, 1.94])
p("The local script ran against MongoDB 8.3.11 with 100 001 events. The indexed path examined only the 20 returned documents and used the index order. The screenshot is a separate Compass execution of the equivalent match, sort and limit pipeline; it reports 20 examined documents and 1 ms. Its single timing is not the median of the script runs.")
p(f"The earlier Docker measurement used MongoDB 8.0.34 and exactly 100 000 events, before the CLI view. It examined 100 000 versus 20 documents and recorded median times of {container['results']['natural_scan']['median_execution_ms']} ms and {container['results']['indexed']['median_execution_ms']} ms. A displayed 0 ms reflects the resolution of the server statistic, not zero elapsed work.")
p("These results establish a reduced amount of document examination for this specific query. They do not establish the same speedup for all operations. Cache state was not reset, hints forced the compared access paths, and write throughput or concurrent production load was not measured. Index size and write maintenance cost remain part of the design trade off.")

# Page 15
new_page("15 Assignment coverage and conclusions")
table(["Assignment requirement", "Completed implementation"], [
    ("Dissertation related topic", "Model selection for edge drowsiness research"),
    ("NoSQL storage", "MongoDB users, models and interactions"),
    ("Detailed proposal", "Scope, relevance, database design and planned ranker"),
    ("Modeling and indexes", "Embedding, references, alternatives and measured plans"),
    ("Registration and profiles", "Authentication and device profile management"),
    ("Item catalog", "Names, descriptions, categories and model attributes"),
    ("User history", "Timestamped views, saves, selections and ratings"),
    ("Search", "Text query and category or attribute filters"),
    ("API", "Documented authentication, CRUD and interaction operations"),
    ("Test data", "100 users, 60 items and 100 000 generated events"),
], [2.2, 4.49])
p("The completed backend meets the technical scope of Assignment 6. The database design keeps bounded model attributes together and separates growing interaction history. Validation and uniqueness are enforced inside MongoDB, and integration tests verify the API behaviour. The query experiment demonstrates the practical value of the history index on the selected workload.")
p("The current recommendation mechanism is a transparent constraint based baseline. The planned content based method belongs to the Final Project. Future dissertation work can replace simulated characteristics with measured experimental records and evaluate model selection under controlled signal, hardware and protocol conditions.")
h("References", 2)
references = [
    "[1] Assignment 6. Designing the data layer and backend for a NoSQL recommendation platform. Course assignment, 2 pages.",
    "[2] MongoDB. Data Modeling. https://www.mongodb.com/docs/manual/data-modeling/",
    "[3] MongoDB. Schema Validation. https://www.mongodb.com/docs/manual/core/schema-validation/",
    "[4] MongoDB. Explain Results. https://www.mongodb.com/docs/manual/reference/explain-results/",
    "[5] MongoDB. Aggregation Operations. https://www.mongodb.com/docs/manual/aggregation/",
    "[6] FastAPI. OAuth2 with JWT and password hashing. https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/",
    "[7] MongoDB. Indexes in PyMongo. https://www.mongodb.com/docs/languages/python/pymongo-driver/current/indexes/",
]
for reference in references:
    para = p(reference, size=10.5, align=WD_ALIGN_PARAGRAPH.LEFT)
    para.paragraph_format.line_spacing = 1.0
    para.paragraph_format.space_after = Pt(4)

# Keep all headings black and free of decorative paragraph borders.
for style_name in ("Title", "Subtitle", "Heading 1", "Heading 2"):
    props = doc.styles[style_name].element.get_or_add_pPr()
    for border in list(props.findall(qn("w:pBdr"))):
        props.remove(border)
DEST.parent.mkdir(parents=True, exist_ok=True)
doc.save(DEST)
print(DEST)
print(f"Embedded {figure_number} actual Compass screenshots; 15 planned pages.")
