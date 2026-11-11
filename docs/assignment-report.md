# Assignment 6

The completed formatted report is available at
`output/doc/Assignment_6_Zhalgasov_Adilbek_CSE-2602M.docx` (15 pages with 9 local Compass
screenshots). This Markdown file retains the earlier report outline.

## Designing the data layer and backend for a NoSQL recommendation platform

**Project:** Edge Drowsiness Model Catalog.

This file provides the report content. The assignment PDF does not specify page margins,
font, a title-page template, or a submission format. Those institutional formatting details
and the student's title-page information must be applied when preparing the final submission.
Actual screenshots of the demonstrated workflow must be inserted in that formatted report.

## 1. Goals and objectives

The goal was to design and implement the data layer and core backend of a NoSQL recommendation
platform related to edge time-series analysis for drowsiness detection. The objectives were
to identify users, items and interactions; design efficient documents and indexes; implement
registration, authentication, catalog management, search and history; populate the database;
and document setup, API operations and the planned recommendation method.

## 2. Project proposal and dissertation connection

The platform supports selecting model versions that match an input signal and constraints
of an edge device. Users are researchers and developers, items are model versions, and
interactions are views, saves, selections and ratings. The detailed proposal, including
the “Relevance to the dissertation” section, is provided in `proposal.md`.

The dissertation topic is “Intelligent methods of edge time-series analysis for drowsiness
detection”. The platform organizes candidate methods and their experimental metadata.
Its synthetic values demonstrate database behavior; they are not evidence of detector quality.

## 3. Implementation sequence

### 3.1. Data-layer design

MongoDB was selected after considering document, key-value and graph models. Three collections
were created: `users`, `models`, `interactions`. Bounded attributes are embedded; growing
interaction histories reference parent entities. Event snapshots preserve model names and
versions at the time of the action. Exact fields and design trade-offs appear in `database.md`.

### 3.2. Validation and indexes

Collection-level JSON Schema validation enforces document shape, types, ranges and event
rating semantics. Unique indexes protect email, catalog version identity and idempotency.
Compound indexes support catalog filters, user histories and event analytics. A text index
supports word-based search. Model removal is implemented as archival to retain references.

### 3.3. Backend and API

The FastAPI backend implements registration, Argon2id password hashing, short-lived JWT
authentication, profiles, role-restricted catalog CRUD, filtered search, append-only interactions,
cursor history, analytics and deterministic constraint-based recommendations.
Interactive OpenAPI documentation is available at `/docs`; endpoint contracts are in `api.md`.

### 3.4. Test data and demonstrations

The generator populated 100 synthetic users, 60 synthetic models and 100 000 interaction
events. Deterministic identifiers make repeated seeding non-destructive and repeatable.
The CLI uses the HTTP API and demonstrates login, catalog queries, insertion of a view,
history retrieval, recommendations and analytics. Running this demonstration increases
the event count by one, as expected.

### 3.5. Validation results

All 18 automated tests passed against the implemented code, including integration checks
using a real MongoDB server. Tests verify permission boundaries, unique constraints,
direct-write validation, concurrent retries, stable private history, aggregation semantics,
repeatable data generation and indexed-query equivalence.

### 3.6. Query-plan experiment

Five executions of the latest-20-events query were compared using a natural scan and
the `user_recent` index. Both paths returned the same documents. The natural scan inspected
100 000 documents and required a sort; the indexed path inspected 20 documents and used
the index order. Median reported execution times were 62 ms and 0 ms respectively.
The latter is the server's millisecond-resolution statistic, not zero elapsed work.
Raw plans, statistics and index sizes were saved to `output/benchmark.json`.

### 3.7. Full Docker verification

The complete API and MongoDB stack was subsequently started using Docker Compose,
with host ports 8001 and 27018. All 18 tests passed inside the application image against
MongoDB 8.0.34 in a separate container. The CLI completed a real HTTP demonstration.
After restarting both services, collection counts remained 100 users, 60 models and
100 001 events, including the single CLI view. A separate container benchmark inspected
100 000 versus 20 documents and recorded median server times of 38 ms versus 0 ms.
The original results are stored separately in `output/docker/`; full details are in
`docker-verification.md`. These container results are distinct from the earlier local run.

## 4. Screenshots to include in the formatted submission

Capture real results in this order:

1. MongoDB Compass: the three collections and sample documents, with password hashes hidden.
2. Collection validators and the unique/compound indexes.
3. Swagger UI: authentication and catalog operations.
4. A successful filtered catalog response and a recorded interaction.
5. User history and one aggregation result.
6. The successful test summary and the two explain plans/statistics.

These screenshots document the order of work and obtained results required by the assignment.
They have not been embedded into this Markdown draft.

## 5. Results and limitations

A functioning NoSQL backend with documented setup and API contracts was produced.
The experiment demonstrates reduced document examination for a specific indexed workload.
It does not establish a universal performance improvement. The present recommender is
a transparent compatibility baseline; the planned content-based ranker belongs to the
Final Project. No drowsiness model was trained or evaluated on real participant data.

## 6. References

1. Assignment 6: Designing the data layer and backend for a NoSQL recommendation platform.
2. [MongoDB Data Modeling](https://www.mongodb.com/docs/manual/data-modeling/)
3. [MongoDB Schema Validation](https://www.mongodb.com/docs/manual/core/schema-validation/)
4. [MongoDB Explain Results](https://www.mongodb.com/docs/manual/reference/explain-results/)
5. [MongoDB Aggregation Operations](https://www.mongodb.com/docs/manual/aggregation/)
6. [FastAPI OAuth2, JWT and password hashing](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
