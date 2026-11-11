from pymongo import IndexModel, MongoClient

SIGNALS = ["eeg", "ecg", "eog", "imu", "video_features"]
CATEGORIES = ["classical_ml", "deep_learning", "hybrid"]
NUMBER = ["double", "int", "long", "decimal"]


def string(max_length=200, **extra):
    return {"bsonType": "string", "minLength": 1, "maxLength": max_length, **extra}


def number(minimum=0.001, maximum=1_000_000):
    return {"bsonType": NUMBER, "minimum": minimum, "maximum": maximum}


def document(properties):
    return {
        "bsonType": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def validators():
    oid, date = {"bsonType": "objectId"}, {"bsonType": "date"}
    device = document(
        {
            "signal": {"enum": SIGNALS},
            "memory_budget_mb": number(),
            "max_latency_ms": number(),
            "reference_device": string(100),
        }
    )
    device["bsonType"] = ["object", "null"]
    users = document(
        {
            "_id": oid,
            "email": string(254),
            "display_name": string(80),
            "password_hash": string(500),
            "role": {"enum": ["user", "admin"]},
            "device": device,
            "created_at": date,
            "updated_at": date,
        }
    )
    models = document(
        {
            "_id": oid,
            "name": string(120),
            "slug": string(120, pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$"),
            "version": string(30),
            "description": string(4000),
            "category": {"enum": CATEGORIES},
            "signals": {
                "bsonType": "array",
                "minItems": 1,
                "maxItems": 5,
                "uniqueItems": True,
                "items": {"enum": SIGNALS},
            },
            "tags": {"bsonType": "array", "maxItems": 15, "uniqueItems": True, "items": string(40)},
            "requirements": document(
                {"memory_mb": number(), "latency_ms": number(), "reference_device": string(100)}
            ),
            "evaluation": document(
                {"f1": number(0, 1), "dataset": string(100), "protocol": string(200)}
            ),
            "synthetic": {"bsonType": "bool"},
            "active": {"bsonType": "bool"},
            "created_at": date,
            "updated_at": date,
        }
    )
    interactions = document(
        {
            "_id": oid,
            "user_id": oid,
            "model_id": oid,
            "type": {"enum": ["view", "save", "select", "rating"]},
            "rating": {"bsonType": ["int", "null"], "minimum": 1, "maximum": 5},
            "request_id": string(36, pattern="^[0-9a-f-]{36}$"),
            "model_snapshot": document(
                {"name": string(120), "slug": string(120), "version": string(30)}
            ),
            "created_at": date,
        }
    )
    interactions["oneOf"] = [
        {"properties": {"type": {"enum": ["rating"]}, "rating": {"bsonType": "int"}}},
        {
            "properties": {
                "type": {"enum": ["view", "save", "select"]},
                "rating": {"bsonType": "null"},
            }
        },
    ]
    return {"users": users, "models": models, "interactions": interactions}


def connect(uri):
    return MongoClient(
        uri,
        tz_aware=True,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        appname="edge-catalog",
        retryWrites=True,
    )


def initialize(db):
    existing = set(db.list_collection_names())
    for name, schema in validators().items():
        options = {
            "validator": {"$jsonSchema": schema},
            "validationLevel": "strict",
            "validationAction": "error",
        }
        if name in existing:
            db.command({"collMod": name, **options})
        else:
            db.create_collection(name, **options)
    db.users.create_indexes(
        [
            IndexModel([("email", 1)], unique=True, name="unique_email"),
        ]
    )
    db.models.create_indexes(
        [
            IndexModel([("slug", 1), ("version", 1)], unique=True, name="unique_slug_version"),
            IndexModel([("active", 1), ("created_at", -1), ("_id", -1)], name="catalog_recent"),
            IndexModel(
                [("active", 1), ("category", 1), ("created_at", -1), ("_id", -1)],
                name="category_recent",
            ),
            IndexModel(
                [
                    ("active", 1),
                    ("signals", 1),
                    ("requirements.reference_device", 1),
                    ("requirements.memory_mb", 1),
                ],
                name="signal_device_memory",
            ),
            IndexModel(
                [("name", "text"), ("description", "text"), ("tags", "text")],
                name="catalog_text",
                default_language="english",
                weights={"name": 5, "tags": 3, "description": 1},
            ),
        ]
    )
    db.interactions.create_indexes(
        [
            IndexModel([("user_id", 1), ("created_at", -1), ("_id", -1)], name="user_recent"),
            IndexModel([("model_id", 1), ("type", 1), ("created_at", -1)], name="model_type_time"),
            IndexModel(
                [("user_id", 1), ("request_id", 1)], unique=True, name="unique_user_request"
            ),
            IndexModel([("created_at", 1), ("type", 1)], name="analytics_time"),
        ]
    )
