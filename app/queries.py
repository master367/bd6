import base64
import binascii
import json
from datetime import UTC, datetime

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

RECENT = [("created_at", -1), ("_id", -1)]


def object_id(value):
    if not ObjectId.is_valid(value):
        raise HTTPException(422, "Invalid ObjectId")
    return ObjectId(value)


def public(doc):
    result = {k: v for k, v in doc.items() if k != "password_hash"}
    if "_id" in result:
        result["id"] = result.pop("_id")
    return jsonable_encoder(result, custom_encoder={ObjectId: str})


def cursor_for(doc):
    payload = {"time": doc["created_at"].isoformat(), "id": str(doc["_id"])}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def cursor_filter(cursor):
    try:
        if len(cursor) > 256:
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        moment = datetime.fromisoformat(data["time"])
        if moment.tzinfo is None:
            raise ValueError
        return {
            "$or": [
                {"created_at": {"$lt": moment}},
                {"created_at": moment, "_id": {"$lt": ObjectId(data["id"])}},
            ]
        }
    except (ValueError, TypeError, KeyError, InvalidId, binascii.Error):
        raise HTTPException(422, "Invalid pagination cursor") from None


def page(collection, query, limit, cursor=None):
    if cursor:
        query = {"$and": [query, cursor_filter(cursor)]}
    docs = list(collection.find(query).sort(RECENT).limit(limit + 1))
    more = len(docs) > limit
    docs = docs[:limit]
    return {
        "items": [public(doc) for doc in docs],
        "next_cursor": cursor_for(docs[-1]) if more else None,
    }


def popularity_pipeline(since, limit):
    return [
        {"$match": {"created_at": {"$gte": since}}},
        {
            "$group": {
                "_id": "$model_id",
                "events": {"$sum": 1},
                "views": {"$sum": {"$cond": [{"$eq": ["$type", "view"]}, 1, 0]}},
                "selections": {"$sum": {"$cond": [{"$eq": ["$type", "select"]}, 1, 0]}},
            }
        },
        {"$lookup": {"from": "models", "localField": "_id", "foreignField": "_id", "as": "model"}},
        {"$unwind": "$model"},
        {"$match": {"model.active": True}},
        {"$sort": {"events": -1, "_id": 1}},
        {"$limit": limit},
        {
            "$project": {
                "_id": 0,
                "model_id": "$_id",
                "name": "$model.name",
                "events": 1,
                "views": 1,
                "selections": 1,
            }
        },
    ]


def ratings_pipeline():
    # Each user's latest rating contributes once, even after multiple re-ratings.
    return [
        {"$match": {"type": "rating"}},
        {"$sort": {"created_at": -1, "_id": -1}},
        {
            "$group": {
                "_id": {"user": "$user_id", "model": "$model_id"},
                "rating": {"$first": "$rating"},
            }
        },
        {
            "$group": {
                "_id": "$_id.model",
                "average_rating": {"$avg": "$rating"},
                "voters": {"$sum": 1},
            }
        },
        {"$lookup": {"from": "models", "localField": "_id", "foreignField": "_id", "as": "model"}},
        {"$unwind": "$model"},
        {"$match": {"model.active": True}},
        {"$sort": {"average_rating": -1, "voters": -1, "_id": 1}},
        {"$limit": 100},
        {
            "$project": {
                "_id": 0,
                "model_id": "$_id",
                "name": "$model.name",
                "average_rating": 1,
                "voters": 1,
            }
        },
    ]


def utcnow():
    return datetime.now(UTC)
