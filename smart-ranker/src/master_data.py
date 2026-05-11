from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid5

from smart_ranker.feature_pipeline import LabelResolverConfig, MechanicalRule, PersonLabelConfig
from smart_ranker.storage.repository import StorageRepository

DEFAULT_REVIEW_THRESHOLD = 0.5
DEFAULT_REVIEW_POLICY_KEY = "review-policy"
DEFAULT_REVIEW_DESTINATION_KEY = "review-album"
DEFAULT_DESCRIPTION_DESTINATION_KEY = "asset-description"
DEFAULT_DESCRIPTION_RESOURCE_ID = "asset-description"
IMMICH_USER_ID_ENV = "SMART_RANKER_IMMICH_USER_ID"
REVIEW_ALBUM_ID_ENV = "SMART_RANKER_REVIEW_ALBUM_ID"
REVIEW_THRESHOLD_ENV = "SMART_RANKER_REVIEW_THRESHOLD"

_MASTER_DATA_NAMESPACE = uuid5(NAMESPACE_URL, "smart-ranker/master-data")


@dataclass(frozen=True)
class RuntimeSettings:
    label_resolver_config: LabelResolverConfig
    review_album_resource_id: str | None
    review_threshold: float
    update_description: bool


def deterministic_id(profile_id: str, scope: str, key: str) -> str:
    return str(uuid5(_MASTER_DATA_NAMESPACE, f"{profile_id}:{scope}:{key}"))


def resolve_seed_inputs(
    *,
    immich_user_id: str | None = None,
    review_album_resource_id: str | None = None,
    review_threshold: float | None = None,
) -> tuple[str, str | None, float]:
    resolved_user_id = (immich_user_id or os.getenv(IMMICH_USER_ID_ENV) or "").strip()
    if not resolved_user_id:
        raise ValueError(f"Missing runtime configuration: {IMMICH_USER_ID_ENV}")

    resolved_review_album_id = review_album_resource_id
    if resolved_review_album_id is None:
        raw_album_id = os.getenv(REVIEW_ALBUM_ID_ENV)
        resolved_review_album_id = raw_album_id.strip() if raw_album_id else None

    if review_threshold is not None:
        resolved_threshold = float(review_threshold)
    else:
        raw_threshold = os.getenv(REVIEW_THRESHOLD_ENV)
        resolved_threshold = DEFAULT_REVIEW_THRESHOLD
        if raw_threshold:
            try:
                resolved_threshold = float(raw_threshold)
            except ValueError as error:
                raise ValueError(f"Invalid {REVIEW_THRESHOLD_ENV}: {raw_threshold}") from error

    return resolved_user_id, resolved_review_album_id, resolved_threshold


def build_default_master_data(
    *,
    profile_id: str,
    review_album_resource_id: str | None = None,
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
) -> dict[str, Any]:
    return {
        "personGroups": [
            {
                "groupKey": "family",
                "displayName": "家族",
                "groupType": "person_set",
                "aliases": ["family"],
                "enabled": True,
                "members": [],
            },
            {
                "groupKey": "child",
                "displayName": "我が子",
                "groupType": "person_set",
                "aliases": ["child"],
                "enabled": True,
                "members": [],
            },
        ],
        "categories": [
            {
                "categoryKey": "landscape",
                "displayName": "風景",
                "categoryType": "core",
                "mediaScope": "all",
                "aliases": ["nature"],
                "enabled": True,
            },
            {
                "categoryKey": "person",
                "displayName": "人物",
                "categoryType": "person",
                "mediaScope": "all",
                "aliases": [],
                "enabled": True,
            },
            {
                "categoryKey": "document",
                "displayName": "書類",
                "categoryType": "core",
                "mediaScope": "all",
                "aliases": ["receipt"],
                "enabled": True,
            },
            {
                "categoryKey": "screenshot",
                "displayName": "スクリーンショット",
                "categoryType": "core",
                "mediaScope": "all",
                "aliases": ["screen_capture"],
                "enabled": True,
            },
            {
                "categoryKey": "pet",
                "displayName": "ペット",
                "categoryType": "core",
                "mediaScope": "all",
                "aliases": ["animal"],
                "enabled": True,
            },
            {
                "categoryKey": "other",
                "displayName": "その他",
                "categoryType": "fallback",
                "mediaScope": "all",
                "aliases": [],
                "enabled": True,
            },
            {
                "categoryKey": "family",
                "displayName": "家族",
                "categoryType": "person",
                "mediaScope": "all",
                "aliases": [],
                "enabled": True,
            },
            {
                "categoryKey": "child",
                "displayName": "我が子",
                "categoryType": "person",
                "mediaScope": "all",
                "aliases": [],
                "enabled": True,
            },
        ],
        "routingRules": [
            {
                "id": deterministic_id(profile_id, "routing-rule", "child-person-membership"),
                "categoryKey": "child",
                "ruleName": "child-person-membership",
                "priority": 10,
                "assignmentMode": "person_group",
                "stopAfterMatch": False,
                "enabled": True,
                "match": {"type": "person_group", "groupKey": "child"},
            },
            {
                "id": deterministic_id(profile_id, "routing-rule", "family-person-membership"),
                "categoryKey": "family",
                "ruleName": "family-person-membership",
                "priority": 20,
                "assignmentMode": "person_group",
                "stopAfterMatch": False,
                "enabled": True,
                "match": {"type": "person_group", "groupKey": "family"},
            },
            {
                "id": deterministic_id(profile_id, "routing-rule", "document-ocr"),
                "categoryKey": "document",
                "ruleName": "document-ocr",
                "priority": 40,
                "assignmentMode": "mechanical",
                "stopAfterMatch": False,
                "enabled": True,
                "match": {
                    "type": "mechanical",
                    "source": "ocr_text",
                    "keywords": ["invoice", "receipt", "領収書", "請求書", "書類"],
                },
            },
            {
                "id": deterministic_id(profile_id, "routing-rule", "document-path"),
                "categoryKey": "document",
                "ruleName": "document-path",
                "priority": 50,
                "assignmentMode": "mechanical",
                "stopAfterMatch": False,
                "enabled": True,
                "match": {
                    "type": "mechanical",
                    "source": "original_path",
                    "keywords": ["/document", "/docs", "/scan", "receipt", "invoice"],
                },
            },
            {
                "id": deterministic_id(profile_id, "routing-rule", "screenshot-file-name"),
                "categoryKey": "screenshot",
                "ruleName": "screenshot-file-name",
                "priority": 60,
                "assignmentMode": "mechanical",
                "stopAfterMatch": False,
                "enabled": True,
                "match": {
                    "type": "mechanical",
                    "source": "file_name",
                    "keywords": ["screenshot", "screen shot", "スクリーンショット"],
                },
            },
            {
                "id": deterministic_id(profile_id, "routing-rule", "screenshot-path"),
                "categoryKey": "screenshot",
                "ruleName": "screenshot-path",
                "priority": 70,
                "assignmentMode": "mechanical",
                "stopAfterMatch": False,
                "enabled": True,
                "match": {
                    "type": "mechanical",
                    "source": "original_path",
                    "keywords": ["screenshot", "screen_shot", "screen-shot"],
                },
            },
            {
                "id": deterministic_id(profile_id, "routing-rule", "landscape-smart-search"),
                "categoryKey": "landscape",
                "ruleName": "landscape-smart-search",
                "priority": 80,
                "assignmentMode": "smart_search",
                "stopAfterMatch": False,
                "enabled": True,
                "match": {
                    "type": "smart_search",
                    "queries": ["landscape", "nature", "風景", "自然"],
                },
            },
            {
                "id": deterministic_id(profile_id, "routing-rule", "pet-smart-search"),
                "categoryKey": "pet",
                "ruleName": "pet-smart-search",
                "priority": 90,
                "assignmentMode": "smart_search",
                "stopAfterMatch": False,
                "enabled": True,
                "match": {
                    "type": "smart_search",
                    "queries": ["pet", "dog", "cat", "犬", "猫", "ペット"],
                },
            },
            {
                "id": deterministic_id(profile_id, "routing-rule", "other-fallback"),
                "categoryKey": "other",
                "ruleName": "other-fallback",
                "priority": 999,
                "assignmentMode": "fallback",
                "stopAfterMatch": True,
                "enabled": True,
                "match": {"type": "fallback"},
            },
        ],
        "policies": [
            {
                "policyKey": DEFAULT_REVIEW_POLICY_KEY,
                "displayName": "Review Policy",
                "executionMode": "manual",
                "display": {
                    "reviewThreshold": review_threshold,
                    "updateDescription": True,
                },
                "enabled": True,
            },
        ],
        "destinations": [
            {
                "destinationKey": DEFAULT_REVIEW_DESTINATION_KEY,
                "destinationType": "album",
                "immichResourceId": review_album_resource_id or "",
                "config": {},
                "enabled": bool(review_album_resource_id),
            },
            {
                "destinationKey": DEFAULT_DESCRIPTION_DESTINATION_KEY,
                "destinationType": "asset_description",
                "immichResourceId": DEFAULT_DESCRIPTION_RESOURCE_ID,
                "config": {},
                "enabled": True,
            },
        ],
        "schedules": [
            {
                "jobType": "collect",
                "runMode": "manual",
                "cronExpr": None,
                "dryRun": False,
                "batchSize": 1000,
                "enabled": True,
            },
            {
                "jobType": "train",
                "runMode": "manual",
                "cronExpr": None,
                "dryRun": False,
                "batchSize": 1000,
                "enabled": True,
            },
            {
                "jobType": "score",
                "runMode": "manual",
                "cronExpr": None,
                "dryRun": True,
                "batchSize": 1000,
                "enabled": True,
            },
            {
                "jobType": "apply",
                "runMode": "manual",
                "cronExpr": None,
                "dryRun": False,
                "batchSize": 1000,
                "enabled": True,
            },
        ],
    }


def load_master_data(repository: StorageRepository, profile_id: str) -> dict[str, Any]:
    person_groups = [dict(row) for row in repository.list_person_groups(profile_id)]
    members_by_group_id: dict[str, list[dict[str, Any]]] = {}
    for row in repository.list_person_group_members(profile_id):
        item = dict(row)
        members_by_group_id.setdefault(str(item["person_group_id"]), []).append(
            {
                "id": item["id"],
                "immichPersonId": item["immich_person_id"],
                "immichPersonName": item["immich_person_name"],
                "sortOrder": item["sort_order"],
                "enabled": bool(item["enabled"]),
            }
        )

    normalized_person_groups = []
    for group in person_groups:
        normalized_person_groups.append(
            {
                "id": group["id"],
                "groupKey": group["group_key"],
                "displayName": group["display_name"],
                "groupType": group["group_type"],
                "aliases": _parse_json_array(group["aliases_json"]),
                "enabled": bool(group["enabled"]),
                "members": members_by_group_id.get(str(group["id"]), []),
            }
        )

    categories = []
    for row in repository.list_categories(profile_id):
        item = dict(row)
        categories.append(
            {
                "id": item["id"],
                "categoryKey": item["category_key"],
                "displayName": item["display_name"],
                "categoryType": item["category_type"],
                "mediaScope": item["media_scope"],
                "aliases": _parse_json_array(item["aliases_json"]),
                "enabled": bool(item["enabled"]),
            }
        )

    routing_rules = []
    for row in repository.list_routing_rules(profile_id):
        item = dict(row)
        routing_rules.append(
            {
                "id": item["id"],
                "categoryId": item["category_id"],
                "categoryKey": item["category_key"],
                "ruleName": item["rule_name"],
                "priority": item["priority"],
                "assignmentMode": item["assignment_mode"],
                "stopAfterMatch": bool(item["stop_after_match"]),
                "enabled": bool(item["enabled"]),
                "match": _parse_json_object(item["match_json"]),
            }
        )

    policies = []
    for row in repository.list_action_policies(profile_id):
        item = dict(row)
        policies.append(
            {
                "id": item["id"],
                "policyKey": item["policy_key"],
                "displayName": item["display_name"],
                "executionMode": item["execution_mode"],
                "display": _parse_json_object(item["display_json"]),
                "enabled": bool(item["enabled"]),
            }
        )

    destinations = []
    for row in repository.list_action_destinations(profile_id):
        item = dict(row)
        destinations.append(
            {
                "id": item["id"],
                "destinationKey": item["destination_key"],
                "destinationType": item["destination_type"],
                "immichResourceId": item["immich_resource_id"],
                "config": _parse_json_object(item["config_json"]),
                "enabled": bool(item["enabled"]),
            }
        )

    schedules = []
    for row in repository.list_execution_schedules(profile_id):
        item = dict(row)
        schedules.append(
            {
                "id": item["id"],
                "jobType": item["job_type"],
                "runMode": item["run_mode"],
                "cronExpr": item["cron_expr"],
                "dryRun": bool(item["dry_run"]),
                "batchSize": item["batch_size"],
                "enabled": bool(item["enabled"]),
            }
        )

    return {
        "personGroups": normalized_person_groups,
        "categories": categories,
        "routingRules": routing_rules,
        "policies": policies,
        "destinations": destinations,
        "schedules": schedules,
    }


def save_person_groups(
    repository: StorageRepository,
    *,
    profile_id: str,
    immich_user_id: str,
    groups: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    repository.ensure_profile(profile_id=profile_id, immich_user_id=immich_user_id)
    saved: list[dict[str, Any]] = []
    for item in groups:
        group_key = _required_string(item, "groupKey")
        display_name = _string_value(item, "displayName", default=group_key)
        group_type = _string_value(item, "groupType", default="person_set")
        aliases = _string_list(item.get("aliases"))
        enabled = _bool_value(item.get("enabled"), default=True)
        group_id = repository.upsert_person_group(
            group_id=str(item.get("id") or deterministic_id(profile_id, "person-group", group_key)),
            profile_id=profile_id,
            group_key=group_key,
            display_name=display_name,
            group_type=group_type,
            aliases=aliases,
            enabled=enabled,
        )
        members = _normalize_members(group_id, item.get("members"), profile_id, group_key)
        repository.replace_person_group_members(group_id, members)
        saved.append(
            {
                "id": group_id,
                "groupKey": group_key,
                "displayName": display_name,
                "groupType": group_type,
                "aliases": aliases,
                "enabled": enabled,
                "members": [
                    {
                        "id": member[0],
                        "immichPersonId": member[1],
                        "immichPersonName": member[2],
                        "sortOrder": member[3],
                        "enabled": bool(member[4]),
                    }
                    for member in members
                ],
            }
        )
    return saved


def save_categories_and_routing(
    repository: StorageRepository,
    *,
    profile_id: str,
    immich_user_id: str,
    categories: Sequence[dict[str, Any]],
    routing_rules: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    repository.ensure_profile(profile_id=profile_id, immich_user_id=immich_user_id)
    category_ids_by_key: dict[str, str] = {}
    saved_categories: list[dict[str, Any]] = []
    for item in categories:
        category_key = _required_string(item, "categoryKey")
        display_name = _string_value(item, "displayName", default=category_key)
        category_type = _string_value(item, "categoryType", default="core")
        media_scope = _string_value(item, "mediaScope", default="all")
        aliases = _string_list(item.get("aliases"))
        enabled = _bool_value(item.get("enabled"), default=True)
        category_id = repository.upsert_category(
            category_id=str(item.get("id") or deterministic_id(profile_id, "category", category_key)),
            profile_id=profile_id,
            category_key=category_key,
            display_name=display_name,
            category_type=category_type,
            media_scope=media_scope,
            aliases=aliases,
            enabled=enabled,
        )
        category_ids_by_key[category_key] = category_id
        saved_categories.append(
            {
                "id": category_id,
                "categoryKey": category_key,
                "displayName": display_name,
                "categoryType": category_type,
                "mediaScope": media_scope,
                "aliases": aliases,
                "enabled": enabled,
            }
        )

    saved_rules: list[dict[str, Any]] = []
    for item in routing_rules:
        category_key = _required_string(item, "categoryKey")
        category_id = category_ids_by_key.get(category_key)
        if category_id is None:
            raise ValueError(f"Unknown categoryKey for routing rule: {category_key}")
        rule_name = _required_string(item, "ruleName")
        priority = _int_value(item.get("priority"), default=100)
        assignment_mode = _string_value(item, "assignmentMode", default="mechanical")
        stop_after_match = _bool_value(item.get("stopAfterMatch"), default=False)
        enabled = _bool_value(item.get("enabled"), default=True)
        match = _object_value(item.get("match"))
        rule_id = str(item.get("id") or deterministic_id(profile_id, "routing-rule", f"{category_key}:{rule_name}"))
        repository.upsert_routing_rule(
            rule_id=rule_id,
            profile_id=profile_id,
            category_id=category_id,
            rule_name=rule_name,
            priority=priority,
            match=match,
            assignment_mode=assignment_mode,
            stop_after_match=stop_after_match,
            enabled=enabled,
        )
        saved_rules.append(
            {
                "id": rule_id,
                "categoryId": category_id,
                "categoryKey": category_key,
                "ruleName": rule_name,
                "priority": priority,
                "assignmentMode": assignment_mode,
                "stopAfterMatch": stop_after_match,
                "enabled": enabled,
                "match": match,
            }
        )

    return {"categories": saved_categories, "routingRules": saved_rules}


def save_policies(
    repository: StorageRepository,
    *,
    profile_id: str,
    immich_user_id: str,
    policies: Sequence[dict[str, Any]],
    destinations: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    repository.ensure_profile(profile_id=profile_id, immich_user_id=immich_user_id)
    saved_policies: list[dict[str, Any]] = []
    for item in policies:
        policy_key = _required_string(item, "policyKey")
        display_name = _string_value(item, "displayName", default=policy_key)
        execution_mode = _string_value(item, "executionMode", default="manual")
        enabled = _bool_value(item.get("enabled"), default=True)
        display = _object_value(item.get("display"))
        policy_id = repository.upsert_action_policy(
            policy_id=str(item.get("id") or deterministic_id(profile_id, "policy", policy_key)),
            profile_id=profile_id,
            policy_key=policy_key,
            display_name=display_name,
            execution_mode=execution_mode,
            display=display,
            enabled=enabled,
        )
        saved_policies.append(
            {
                "id": policy_id,
                "policyKey": policy_key,
                "displayName": display_name,
                "executionMode": execution_mode,
                "display": display,
                "enabled": enabled,
            }
        )

    saved_destinations: list[dict[str, Any]] = []
    for item in destinations:
        destination_key = _required_string(item, "destinationKey")
        destination_type = _string_value(item, "destinationType", default="album")
        immich_resource_id = _string_value(item, "immichResourceId", default="")
        config = _object_value(item.get("config"))
        enabled = _bool_value(item.get("enabled"), default=True)
        destination_id = repository.upsert_action_destination(
            destination_id=str(item.get("id") or deterministic_id(profile_id, "destination", destination_key)),
            profile_id=profile_id,
            destination_key=destination_key,
            destination_type=destination_type,
            immich_resource_id=immich_resource_id,
            config=config,
            enabled=enabled,
        )
        saved_destinations.append(
            {
                "id": destination_id,
                "destinationKey": destination_key,
                "destinationType": destination_type,
                "immichResourceId": immich_resource_id,
                "config": config,
                "enabled": enabled,
            }
        )

    return {"policies": saved_policies, "destinations": saved_destinations}


def save_schedules(
    repository: StorageRepository,
    *,
    profile_id: str,
    immich_user_id: str,
    schedules: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    repository.ensure_profile(profile_id=profile_id, immich_user_id=immich_user_id)
    saved: list[dict[str, Any]] = []
    for item in schedules:
        job_type = _required_string(item, "jobType")
        run_mode = _string_value(item, "runMode", default="manual")
        cron_expr = item.get("cronExpr")
        batch_size = _int_value(item.get("batchSize"), default=1000)
        dry_run = _bool_value(item.get("dryRun"), default=(job_type == "score"))
        enabled = _bool_value(item.get("enabled"), default=True)
        schedule_id = repository.upsert_execution_schedule(
            schedule_id=str(item.get("id") or deterministic_id(profile_id, "schedule", job_type)),
            profile_id=profile_id,
            job_type=job_type,
            run_mode=run_mode,
            cron_expr=str(cron_expr) if cron_expr not in (None, "") else None,
            dry_run=dry_run,
            batch_size=batch_size,
            enabled=enabled,
        )
        saved.append(
            {
                "id": schedule_id,
                "jobType": job_type,
                "runMode": run_mode,
                "cronExpr": str(cron_expr) if cron_expr not in (None, "") else None,
                "dryRun": dry_run,
                "batchSize": batch_size,
                "enabled": enabled,
            }
        )
    return saved


def seed_master_data(
    repository: StorageRepository,
    *,
    profile_id: str,
    immich_user_id: str,
    review_album_resource_id: str | None = None,
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
) -> dict[str, Any]:
    defaults = build_default_master_data(
        profile_id=profile_id,
        review_album_resource_id=review_album_resource_id,
        review_threshold=review_threshold,
    )
    save_person_groups(
        repository,
        profile_id=profile_id,
        immich_user_id=immich_user_id,
        groups=defaults["personGroups"],
    )
    save_categories_and_routing(
        repository,
        profile_id=profile_id,
        immich_user_id=immich_user_id,
        categories=defaults["categories"],
        routing_rules=defaults["routingRules"],
    )
    save_policies(
        repository,
        profile_id=profile_id,
        immich_user_id=immich_user_id,
        policies=defaults["policies"],
        destinations=defaults["destinations"],
    )
    save_schedules(
        repository,
        profile_id=profile_id,
        immich_user_id=immich_user_id,
        schedules=defaults["schedules"],
    )
    return load_master_data(repository, profile_id)


def load_runtime_settings(
    repository: StorageRepository,
    *,
    profile_id: str,
    default_review_album_resource_id: str | None = None,
    default_review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
) -> RuntimeSettings:
    bundle = load_master_data(repository, profile_id)
    if not bundle["categories"] and not bundle["routingRules"] and not bundle["personGroups"]:
        return RuntimeSettings(
            label_resolver_config=LabelResolverConfig(),
            review_album_resource_id=default_review_album_resource_id,
            review_threshold=default_review_threshold,
            update_description=True,
        )

    family_person_ids: set[str] = set()
    child_person_ids: set[str] = set()
    for group in bundle["personGroups"]:
        if not group["enabled"]:
            continue
        target = None
        if group["groupKey"] == "family":
            target = family_person_ids
        elif group["groupKey"] == "child":
            target = child_person_ids
        if target is None:
            continue
        for member in group["members"]:
            if member["enabled"]:
                target.add(str(member["immichPersonId"]))

    enabled_categories = {item["categoryKey"]: item for item in bundle["categories"] if item["enabled"]}
    mechanical_rules: list[MechanicalRule] = []
    smart_search_category_keys: list[str] = []
    for rule in sorted(bundle["routingRules"], key=lambda item: (int(item["priority"]), str(item["ruleName"]))):
        if not rule["enabled"]:
            continue
        category_key = str(rule["categoryKey"])
        if category_key not in enabled_categories:
            continue
        match = rule["match"]
        match_type = str(match.get("type", ""))
        if match_type == "mechanical":
            source = str(match.get("source") or "").strip()
            keywords = tuple(_string_list(match.get("keywords")))
            if source and keywords:
                mechanical_rules.append(
                    MechanicalRule(
                        category_key=category_key,
                        source=source,
                        keywords=keywords,
                    )
                )
        elif match_type == "smart_search":
            if category_key not in smart_search_category_keys:
                smart_search_category_keys.append(category_key)

    other_category_key = "other"
    for category in bundle["categories"]:
        if category["enabled"] and category["categoryType"] == "fallback":
            other_category_key = str(category["categoryKey"])
            break

    review_threshold = default_review_threshold
    update_description = True
    for policy in bundle["policies"]:
        if policy["enabled"] and policy["policyKey"] == DEFAULT_REVIEW_POLICY_KEY:
            display = policy["display"]
            if display.get("reviewThreshold") is not None:
                review_threshold = float(display["reviewThreshold"])
            update_description = _bool_value(display.get("updateDescription"), default=True)
            break

    review_album_resource_id = default_review_album_resource_id
    for destination in bundle["destinations"]:
        if destination["enabled"] and destination["destinationKey"] == DEFAULT_REVIEW_DESTINATION_KEY:
            candidate = str(destination["immichResourceId"] or "").strip()
            review_album_resource_id = candidate or None
            break

    label_resolver_config = LabelResolverConfig(
        person_labels=PersonLabelConfig(
            family_person_ids=frozenset(family_person_ids),
            child_person_ids=frozenset(child_person_ids),
        ),
        mechanical_rules=tuple(mechanical_rules),
        smart_search_category_keys=tuple(smart_search_category_keys),
        other_category_key=other_category_key,
    )
    return RuntimeSettings(
        label_resolver_config=label_resolver_config,
        review_album_resource_id=review_album_resource_id,
        review_threshold=review_threshold,
        update_description=update_description,
    )


def _normalize_members(
    group_id: str,
    raw_members: Any,
    profile_id: str,
    group_key: str,
) -> list[tuple[str, str, str, int, int]]:
    if not isinstance(raw_members, Sequence) or isinstance(raw_members, (str, bytes, bytearray, dict)):
        return []

    members: list[tuple[str, str, str, int, int]] = []
    for index, item in enumerate(raw_members):
        if not isinstance(item, dict):
            continue
        person_id = _required_string(item, "immichPersonId")
        person_name = _string_value(item, "immichPersonName", default=person_id)
        sort_order = _int_value(item.get("sortOrder"), default=index)
        enabled = 1 if _bool_value(item.get("enabled"), default=True) else 0
        member_id = str(
            item.get("id")
            or deterministic_id(profile_id, "person-group-member", f"{group_key}:{person_id}")
        )
        members.append((member_id, person_id, person_name, sort_order, enabled))
    return members


def _parse_json_array(value: Any) -> list[str]:
    parsed = _parse_json_object_or_array(value)
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _parse_json_object(value: Any) -> dict[str, Any]:
    parsed = _parse_json_object_or_array(value)
    return parsed if isinstance(parsed, dict) else {}


def _parse_json_object_or_array(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {} if value.lstrip().startswith("{") else []
    return {} if isinstance(value, str) else value


def _required_string(item: dict[str, Any], key: str) -> str:
    value = _string_value(item, key, default="")
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _string_value(item: dict[str, Any], key: str, *, default: str) -> str:
    value = item.get(key)
    if value is None:
        return default
    return str(value).strip()


def _object_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    raise ValueError("Expected object value")


def _int_value(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _bool_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    lowered = str(value).strip().casefold()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Sequence):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError("Expected string list")
