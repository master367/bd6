# Project Proposal

**Assignment 6: Designing the data layer and backend for a NoSQL recommendation platform**

**Project:** Edge Drowsiness Model Catalog: a recommendation platform for selecting
time-series drowsiness-detection models under edge-device constraints.

## 1. Problem and scope

Researchers need to organize candidate drowsiness-detection methods and select versions
that match their available signals and device constraints. This project provides a searchable
catalog, user profiles, a history of choices, and a database foundation for recommendations.
It implements the data layer and backend. It does not train or deploy a drowsiness detector.

The platform's users are researchers and developers. Items are individual versions of
detection models. Interactions are views, saves, selections, and ratings. Model metadata
includes signal types, categories, resource requirements, evaluation context, and provenance
of synthetic demonstration values.

## 2. Relevance to the dissertation

The dissertation topic is “Intelligent methods of edge time-series analysis for drowsiness
detection” («Интеллектуальные методы периферийного анализа временных рядов для детекции
сонливости»). The proposed platform supports the comparison and selection stage of this
research. Its purpose is to maintain structured descriptions of candidate methods, their
versions, their input requirements, and their experimental characteristics. This makes the
database a supporting research instrument rather than a substitute for the detection method.

Edge deployment introduces explicit resource constraints into the selection problem.
A method may accept a particular signal type while requiring more memory or processing time
than the target device can provide. The platform represents those requirements as queryable
attributes and stores a device profile for each user. Its initial selection mechanism filters
the catalog using signal compatibility, memory budget, latency threshold, and an identical
reference-device identifier. This produces a transparent baseline that can later be compared
with more advanced ranking methods in the dissertation.

Evaluation results require context. Consequently, each catalog entry includes the evaluation
dataset and protocol as well as an F1 value. Resource values include a reference-device
identifier. This structure helps distinguish records measured under different conditions.
Future comparisons must additionally control signal preprocessing, window length, hardware,
runtime, and participant-level data splitting. Values from incompatible evaluation settings
should not be treated as directly comparable evidence of one model's superiority.

Interaction history provides a separate source of information about how researchers use the
catalog. Views, saves, selections, and ratings can support experiments with personalization.
Such behavior is a preference signal; it does not establish clinical validity or detection
accuracy. The database preserves timestamped events and the model identity at the time of
an action, enabling reproducible examination of recommendation inputs.

For Assignment 6, the platform is populated with explicitly labelled synthetic data.
These records are suitable for validating queries, indexes, constraints, and API behavior.
They cannot substantiate claims about real drowsiness-detection performance. As dissertation
experiments become available, measured model records can be added with their provenance and
evaluation context. The platform can then help organize comparison tables, reproduce model
selection criteria, and evaluate recommendation strategies against a documented baseline.

## 3. NoSQL selection and data modeling

MongoDB is selected for document-oriented model metadata, embedded bounded attributes,
query-specific indexes, and aggregation pipelines. Three collections are used:

- `users`: credentials, preferences, and an embedded device profile.
- `models`: versioned catalog items with embedded resource and evaluation details.
- `interactions`: an append-only event history referencing users and models.

Large interaction arrays are deliberately not embedded in users. A bounded model-name
snapshot in each event preserves historical display information. MongoDB validators enforce
document shape and value constraints. Unique indexes enforce email, model-version identity,
and event idempotency. Application-level checks and soft deletion manage references.

Document, key-value, and graph alternatives and the exact index workload are compared
in [database.md](database.md). MongoDB alone is sufficient for the current workload.

## 4. Backend and API

The backend uses Python, FastAPI, and the synchronous PyMongo driver. Blocking database calls
run in ordinary synchronous endpoint functions. Users register, authenticate with a short-lived
JWT, manage profiles, search items, and record interactions. Administrators manage the catalog
and access the activity summary. The API also exposes popularity and latest-rating analytics.
CLI and Swagger UI support demonstration without a separate frontend.

## 5. Recommendation method planned for the Final Project

The implemented baseline uses deterministic filtering: retain active models with a compatible
signal and matching reference device, enforce the memory and latency bounds, and order by
latency, then memory, with `_id` as a deterministic tie-breaker.

For the Final Project, a content-based ranking method is proposed:

1. Apply the same hard compatibility constraints.
2. Build normalized item features from resource usage, signal types, and evaluation metadata.
3. Restrict quality comparisons to a compatible dataset and evaluation protocol.
4. Derive preference features from saved, selected, and rated items, with explicit event weights.
5. Rank eligible candidates using a documented weighted score and return an explanation.

A new user receives the constraint-based baseline until sufficient preferences exist.
The advanced ranker has not yet been implemented. Candidate evaluation measures include
constraint-violation rate, catalog coverage, query latency, and, when meaningful held-out
interaction data exist, Precision@K and NDCG@K using a time-based split. Synthetic behavior
can validate the evaluation pipeline but cannot demonstrate real user satisfaction.

## 6. Data, validation and deliverables

The demonstration dataset contains 100 synthetic users, 60 synthetic model versions, and
100 000 generated interactions; running the CLI demonstration adds one real demonstration
event. Seed operations use deterministic identifiers and do not erase existing records.

Validation includes API authorization, user-history isolation, direct database validation,
concurrent idempotency, stable pagination, search, aggregation correctness, and repeatable
seeding. A separate `explain` experiment compares a natural scan and the history index on
the same collection, verifies identical query results, and records examined documents,
keys, execution statistics, and index storage.

Deliverables are the working backend, database initialization and data generator, CLI,
API documentation, setup instructions, this proposal, and the assignment report content.

## References

1. [MongoDB: Data Modeling](https://www.mongodb.com/docs/manual/data-modeling/)
2. [MongoDB: Schema Validation](https://www.mongodb.com/docs/manual/core/schema-validation/)
3. [MongoDB: Explain Results](https://www.mongodb.com/docs/manual/reference/explain-results/)
4. [MongoDB: Aggregation Operations](https://www.mongodb.com/docs/manual/aggregation/)
5. [FastAPI: OAuth2 with JWT and password hashing](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
